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

#: Workflow meaning for a TMS, carried alongside the tier so the number is actionable.
WORKFLOW = {
    Tier.NONE: "do not offer",
    Tier.TOKEN: "recognises it, cannot use it",
    Tier.BASIC: "MT-assist only, mandatory human pass",
    Tier.USABLE: "post-editing workflow",
    Tier.STRONG: "light review",
}


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
    notes: list[str] = field(default_factory=list)

    @property
    def workflow(self) -> str:
        return WORKFLOW[self.tier]

    def as_dict(self) -> dict:
        return {
            "tier": self.tier.value,
            "workflow": self.workflow,
            "s_lang": round(self.s_lang, 3),
            "s_content": round(self.s_content, 3),
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
          contradictions: int = 0, notes: list[str] | None = None) -> Score:
    """Combine per-item outcomes into a tier with an interval.

    `lang_pass` covers every attempted item, including those the gate rejected;
    `content` covers only items that reached the judge.
    """
    notes = list(notes or [])
    n = len(lang_pass)
    s_lang = (sum(lang_pass) / n) if n else 0.0
    s_content = (sum(content) / len(content)) if content else 0.0

    if evidence is Evidence.DETERMINISTIC_NEGATIVE:
        return Score(Tier.NONE, s_lang, 0.0, (0.0, 0.0), False, evidence,
                     n_items=n, n_gated=n - sum(lang_pass), notes=notes)

    if evidence is Evidence.UNVERIFIED:
        notes.append("Back-translator could not be qualified for this language; "
                     "quality is not assessable.")
        return Score(Tier.NONE, s_lang, 0.0, (0.0, 0.0), False, evidence,
                     n_items=n, n_gated=n - sum(lang_pass), notes=notes)

    tier = tier_for(s_lang, s_content)
    lo, hi = bootstrap_ci(content) if content else (0.0, 0.0)
    return Score(tier, s_lang, s_content, (lo, hi),
                 _straddles_boundary(tier, s_lang, lo, hi), evidence,
                 n_items=n, n_gated=n - sum(lang_pass),
                 contradictions=contradictions, notes=notes)
