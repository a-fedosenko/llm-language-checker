"""Scoring: sub-scores, tiers, and honest uncertainty.

Support is not binary. With a handful of items per language the uncertainty is
wide, so every result carries an interval, and a result whose interval straddles
a tier boundary is reported as borderline rather than rounded (docs/01).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum


class Tier(str, Enum):
    NONE = "None"
    TOKEN = "Token"
    BASIC = "Basic"
    USABLE = "Usable"
    STRONG = "Strong"


class Availability(str, Enum):
    """How often the model was willing to answer at all.

    A separate axis from the tier on purpose. The tier says what the model can
    write; this says how often it will. Collapsing them would either call a
    capable-but-squeamish model incapable, or let "Strong -- light review" stand
    for a model that refuses one request in three.
    """

    RELIABLE = "reliable"
    INTERMITTENT = "intermittent"
    UNRELIABLE = "unreliable"
    REFUSED = "refused"


class Evidence(str, Enum):
    GOLD_REFERENCE = "gold-reference"
    FACT_RECALL = "fact-recall"
    DETERMINISTIC_NEGATIVE = "deterministic-negative"
    UNVERIFIED = "unverified"


ORDER = [Tier.NONE, Tier.TOKEN, Tier.BASIC, Tier.USABLE, Tier.STRONG]

# (minimum s_lang, minimum s_content) -- evaluated strongest first.
THRESHOLDS: list[tuple[Tier, float, float]] = [
    (Tier.STRONG, 0.95, 0.70),
    (Tier.USABLE, 0.90, 0.50),
    (Tier.BASIC, 0.80, 0.30),
    (Tier.TOKEN, 0.50, 0.00),
]

#: Minimum reliability for each availability band, evaluated best first.
AVAILABILITY: list[tuple[Availability, float]] = [
    (Availability.RELIABLE, 0.90),
    (Availability.INTERMITTENT, 0.60),
    (Availability.UNRELIABLE, 0.0),
]

#: What each band adds to the workflow sentence. Empty for the expected case.
AVAILABILITY_CAVEAT = {
    Availability.RELIABLE: "",
    Availability.INTERMITTENT: "expect retries",
    Availability.UNRELIABLE: "needs a fallback engine",
    Availability.REFUSED: "refused every attempt",
}

#: Workflow meaning for a TMS, carried alongside the tier so the number is actionable.
WORKFLOW = {
    Tier.NONE: "do not offer",
    Tier.TOKEN: "recognises it, cannot use it",
    Tier.BASIC: "MT-assist only, mandatory human pass",
    Tier.USABLE: "post-editing workflow",
    Tier.STRONG: "light review",
}


def availability_for(reliability: float, *, attempts: int = 0) -> Availability:
    """Band a reliability figure. `attempts` distinguishes "refused everything"
    from "nothing was attempted", which are not the same claim."""
    if attempts and reliability <= 0.0:
        return Availability.REFUSED
    for band, minimum in AVAILABILITY:
        if reliability >= minimum:
            return band
    return Availability.UNRELIABLE


def tier_for(s_lang: float, s_content: float) -> Tier:
    for tier, min_lang, min_content in THRESHOLDS:
        if s_lang >= min_lang and s_content >= min_content:
            return tier
    return Tier.NONE


def bootstrap_ci(values: list[float], *, confidence: float = 0.90,
                 iterations: int = 2000, seed: int = 0) -> tuple[float, float]:
    """Percentile bootstrap over per-item scores. Deterministic for reproducibility."""
    if not values:
        return (0.0, 0.0)
    if len(values) == 1:
        return (values[0], values[0])
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(iterations))
    lo = means[int((1 - confidence) / 2 * iterations)]
    hi = means[min(iterations - 1, int((1 + confidence) / 2 * iterations))]
    return (round(lo, 3), round(hi, 3))


@dataclass
class Score:
    tier: Tier
    s_lang: float
    s_content: float
    ci: tuple[float, float]
    borderline: bool
    evidence: Evidence
    n_items: int
    n_gated: int = 0
    contradictions: int = 0
    #: Share of attempts where the model was willing to try at all. Distinct from
    #: capability: a model that writes perfect Uyghur twice and refuses once is
    #: capable but unreliable, and calling that "recognises it, cannot use it"
    #: would be false. Refusals are excluded from s_lang and reported here.
    reliability: float = 1.0
    refusals: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def availability(self) -> Availability:
        return availability_for(self.reliability, attempts=self.n_items)

    @property
    def workflow(self) -> str:
        """The tier's workflow, qualified by availability.

        The tier alone was misleading in one direction we actually hit: `ug`
        reported "Strong -- light review" at reliability 0.33, true about the
        quality of what came back and quiet about how rarely it came back at
        all. The caveat rides on the sentence a planner reads; the tier itself
        stays a statement about capability.
        """
        base = WORKFLOW[self.tier]
        caveat = AVAILABILITY_CAVEAT[self.availability]
        if not caveat or self.tier is Tier.NONE:
            return base
        return f"{base} -- {caveat} ({self.refusals} refusal(s) of {self.n_items})"

    def as_dict(self) -> dict:
        return {
            "tier": self.tier.value,
            "workflow": self.workflow,
            "s_lang": round(self.s_lang, 3),
            "s_content": round(self.s_content, 3),
            "reliability": round(self.reliability, 3),
            "availability": self.availability.value,
            "refusals": self.refusals,
            "ci": list(self.ci),
            "borderline": self.borderline,
            "evidence": self.evidence.value,
            "n_items": self.n_items,
            "n_gated": self.n_gated,
            "contradictions": self.contradictions,
            "notes": self.notes,
        }


def _straddles_boundary(tier: Tier, s_lang: float, lo: float, hi: float) -> bool:
    """True when the interval spans a tier boundary, so the tier cannot be stated flatly."""
    return tier_for(s_lang, lo) is not tier_for(s_lang, hi)


def score(*, lang_pass: list[bool], content: list[float], evidence: Evidence,
          contradictions: int = 0, refusals: int = 0,
          notes: list[str] | None = None) -> Score:
    """Combine per-item outcomes into a tier with an interval.

    `lang_pass` covers items where the model produced text, including those the
    gate then rejected. `refusals` are counted separately: declining to answer is
    a willingness signal, not a capability one, and merging the two would let a
    model that writes a language perfectly be labelled unable to use it.
    """
    notes = list(notes or [])
    n = len(lang_pass)
    attempts = n + refusals
    reliability = (n / attempts) if attempts else 0.0
    s_lang = (sum(lang_pass) / n) if n else 0.0
    if refusals and n:
        notes.append(f"Refused {refusals} of {attempts} attempts; "
                     f"capability scored on the {n} it attempted.")
    s_content = (sum(content) / len(content)) if content else 0.0

    if evidence is Evidence.DETERMINISTIC_NEGATIVE:
        return Score(Tier.NONE, s_lang, 0.0, (0.0, 0.0), False, evidence,
                     n_items=attempts, n_gated=attempts - sum(lang_pass),
                     reliability=reliability, refusals=refusals, notes=notes)

    if evidence is Evidence.UNVERIFIED:
        notes.append("Back-translator could not be qualified for this language; "
                     "quality is not assessable.")
        return Score(Tier.NONE, s_lang, 0.0, (0.0, 0.0), False, evidence,
                     n_items=attempts, n_gated=attempts - sum(lang_pass),
                     reliability=reliability, refusals=refusals, notes=notes)

    tier = tier_for(s_lang, s_content)
    lo, hi = bootstrap_ci(content) if content else (0.0, 0.0)
    return Score(tier, s_lang, s_content, (lo, hi),
                 _straddles_boundary(tier, s_lang, lo, hi), evidence,
                 n_items=attempts, n_gated=n - sum(lang_pass),
                 contradictions=contradictions, reliability=reliability,
                 refusals=refusals, notes=notes)
