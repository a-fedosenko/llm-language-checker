"""Scoring: eligibility, adequacy, and the small tier derived from them.

The shape of this module is a result, not a preference. Protocols 014, 016 and
017 measured a five-tier scale that did not exist: `Basic` was never assigned in
40 results, `Usable` ranked *below* `None` on 98 calibration languages, and the
function that assigned tiers ordered languages worse than one of its own inputs.
[Protocol 018](../../../experiments/protocols/018-eligibility-and-adequacy.md)
rebuilt it on what the data supports, and that is three parts:

  eligibility   the deterministic gate, as a filter. Wrong script or wrong
                language means unusable, full stop -- an LLM adjudicator missed
                15 of 15 script mismatches the gate caught (016), so this job is
                never handed to a model. One threshold, because at the handful
                of items a breadth-first tool can afford, three cannot be told
                apart (017).

  adequacy      fact recall over the items that cleared the filter. This is the
                measurement, it is published as a number, and it is the best
                ordering signal in the study (rho 0.69 against chrF++ by
                language, against 0.52 for the gate).

  tier          a lossy routing convenience *derived* from the number. Three
                values, monotonic against quality by measurement rather than by
                assertion. It never replaces the number.

Support is not binary, so a result still carries an interval over the per-item
adequacy scores, and one whose interval spans the adequacy cut is reported as
borderline rather than rounded (docs/01).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum


class Tier(str, Enum):
    """Routing outcomes, derived from the adequacy number rather than replacing it.

    None of these three names was used by the five-tier scale. That is deliberate:
    `Strong` and `None` would have survived a rename, but reusing a label whose
    meaning has changed lets an old row be read as if it were comparable. A tier
    string from method 1.x now fails to parse, which is the correct behaviour for
    a measurement that is no longer on the same scale.
    """

    UNUSABLE = "Unusable"
    ASSISTED = "Assisted"
    PROFICIENT = "Proficient"


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


ORDER = [Tier.UNUSABLE, Tier.ASSISTED, Tier.PROFICIENT]

#: Minimum share of judgeable items that must be in the requested language.
#:
#: One threshold, not three. `s_lang` moves in steps of 1/n, so telling 0.95 from
#: 0.90 needs n >= 20 items per language -- six to seven times the current cost,
#: and the wrong trade for a tool whose value is breadth (protocol 017). At the
#: ladder's three items the old three thresholds were one threshold wearing three
#: hats. 0.5 reads as "the model produced the requested language more often than
#: not", and protocol 018 measured it as the most economical cut that still
#: catches every wrong-script item: it leaves the eligible set 1% contaminated by
#: wrong script while rejecting only 74 of 378 items, where 0.95 rejects 139 to
#: capture exactly the same 23.
ELIGIBLE_MIN_LANG = 0.50

#: Minimum adequacy for the top routing band.
#:
#: High, and that is the point. Protocol 016 established that fact recall is an
#: adequacy floor rather than a quality gradient -- above a threshold, adequacy
#: is close to binary -- so the one cut a floor can carry belongs at its top
#: edge, at "essentially every fact survived". Protocol 018 measured cuts at
#: 0.50, 0.70, 0.85 and 0.95 against mean chrF++ across 98 languages; 0.95 is the
#: only one that orders the three tiers monotonically, and it is also the best
#: (rho 0.647 against 0.686 for the continuous score it is derived from).
PROFICIENT_MIN_CONTENT = 0.95

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

#: Workflow meaning for a TMS, carried alongside the tier so it is actionable.
#:
#: Three sentences because there are three decisions a TMS can actually take with
#: a locale: do not route it here, route it here behind a full human pass, or
#: route it here behind a review. The old five included two -- "recognises it,
#: cannot use it" and "post-editing workflow" -- that named a distinction the
#: measurement could not support.
WORKFLOW = {
    Tier.UNUSABLE: "do not offer",
    Tier.ASSISTED: "MT-assist only, mandatory human pass",
    Tier.PROFICIENT: "light review",
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


def is_eligible(s_lang: float) -> bool:
    """Did the model write the language it was asked for, more often than not?

    An eligibility question, not a quality one. Protocol 017 measured the gate as
    a mediocre *grader* and protocol 016 measured it as an irreplaceable *filter*
    -- 15 of 15 script mismatches caught, against 0 of 15 for a capable LLM given
    the same texts and told explicitly to look. So it decides membership and then
    stops; it does not contribute to the grade.
    """
    return s_lang >= ELIGIBLE_MIN_LANG


def tier_for(s_lang: float, s_content: float) -> Tier:
    """Derive the routing tier. Filter first, then bin the measurement.

    Deliberately trivial, and kept that way. The old version hard-gated on
    `s_lang` and then binned `s_content` four ways, and protocol 017 measured the
    result as ordering languages *worse* than `s_content` alone -- it destroyed
    about a third of the ordering information present in its own inputs. This one
    costs 0.04 of Spearman against the number it is derived from, which is the
    price of giving a TMS something to route on.
    """
    if not is_eligible(s_lang):
        return Tier.UNUSABLE
    if s_content >= PROFICIENT_MIN_CONTENT:
        return Tier.PROFICIENT
    return Tier.ASSISTED


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
    #: Items the gate declined to judge rather than convicted -- `low_confidence`
    #: and `too_short`. probe/gate.py says of the first that it is "too weak to
    #: count against the model", and this is where that promise is kept: a voided
    #: item leaves the eligibility denominator instead of sitting in it as a
    #: failure. Counted so a reader can see how much of the sample was mute.
    voided: int = 0
    #: Share of attempts where the model was willing to try at all. Distinct from
    #: capability: a model that writes perfect Uyghur twice and refuses once is
    #: capable but unreliable, and calling that "recognises it, cannot use it"
    #: would be false. Refusals are excluded from s_lang and reported here.
    reliability: float = 1.0
    refusals: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def eligible(self) -> bool:
        """Whether the model cleared the language-and-script filter at all.

        Published beside the tier because it is a different kind of statement:
        every other number here grades how well the model did, and this one says
        whether it was answering the question.
        """
        return is_eligible(self.s_lang)

    @property
    def availability(self) -> Availability:
        return availability_for(self.reliability, attempts=self.n_items)

    @property
    def workflow(self) -> str:
        """The tier's workflow, qualified by availability.

        The tier alone was misleading in one direction we actually hit: `ug`
        reported "light review" at reliability 0.33, true about the
        quality of what came back and quiet about how rarely it came back at
        all. The caveat rides on the sentence a planner reads; the tier itself
        stays a statement about capability.
        """
        base = WORKFLOW[self.tier]
        caveat = AVAILABILITY_CAVEAT[self.availability]
        if not caveat or self.tier is Tier.UNUSABLE:
            return base
        return f"{base} -- {caveat} ({self.refusals} refusal(s) of {self.n_items})"

    def as_dict(self) -> dict:
        return {
            "tier": self.tier.value,
            "workflow": self.workflow,
            "eligible": self.eligible,
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
            "voided": self.voided,
            "contradictions": self.contradictions,
            "notes": self.notes,
        }


def _straddles_boundary(s_lang: float, lo: float, hi: float) -> bool:
    """True when the interval spans the adequacy cut, so the tier cannot be stated flatly.

    There is one cut left to straddle. Eligibility is not one of them: it is a
    filter over gate verdicts, not over the adequacy scores the interval is drawn
    from, so an interval says nothing about which side of it a language sits.
    """
    return tier_for(s_lang, lo) is not tier_for(s_lang, hi)


def score(*, lang_pass: list[bool], content: list[float], evidence: Evidence,
          voided: int = 0, contradictions: int = 0, refusals: int = 0,
          notes: list[str] | None = None) -> Score:
    """Combine per-item outcomes into an eligibility, an adequacy and a tier.

    `lang_pass` covers items where the model produced text, including those the
    gate then rejected. `refusals` are counted separately: declining to answer is
    a willingness signal, not a capability one, and merging the two would let a
    model that writes a language perfectly be labelled unable to use it.

    `voided` says how many of the `False` entries in `lang_pass` were the gate
    declining to judge -- `low_confidence` or `too_short` -- rather than
    convicting. Those leave the eligibility denominator entirely. The gate module
    already held this position in a comment ("too weak to count against the
    model") while the arithmetic did the opposite; protocol 018 moved the
    arithmetic to match, and found it changes 1 language in 98.
    """
    notes = list(notes or [])
    n = len(lang_pass)
    attempts = n + refusals
    reliability = (n / attempts) if attempts else 0.0
    passes = sum(lang_pass)
    # Eligibility is measured over the items the gate was willing to rule on.
    judgeable = n - voided
    s_lang = (passes / judgeable) if judgeable else 0.0
    if refusals and n:
        notes.append(f"Refused {refusals} of {attempts} attempts; "
                     f"capability scored on the {n} it attempted.")
    if voided:
        notes.append(f"{voided} of {n} item(s) the gate declined to rule on; "
                     f"eligibility measured over the remaining {judgeable}.")
    s_content = (sum(content) / len(content)) if content else 0.0

    if evidence is Evidence.DETERMINISTIC_NEGATIVE:
        return Score(Tier.UNUSABLE, s_lang, 0.0, (0.0, 0.0), False, evidence,
                     n_items=attempts, n_gated=attempts - passes, voided=voided,
                     reliability=reliability, refusals=refusals, notes=notes)

    if evidence is Evidence.UNVERIFIED:
        notes.append("Back-translator could not be qualified for this language; "
                     "quality is not assessable.")
        return Score(Tier.UNUSABLE, s_lang, 0.0, (0.0, 0.0), False, evidence,
                     n_items=attempts, n_gated=attempts - passes, voided=voided,
                     reliability=reliability, refusals=refusals, notes=notes)

    tier = tier_for(s_lang, s_content)
    lo, hi = bootstrap_ci(content) if content else (0.0, 0.0)
    return Score(tier, s_lang, s_content, (lo, hi),
                 _straddles_boundary(s_lang, lo, hi), evidence,
                 n_items=attempts, n_gated=n - passes, voided=voided,
                 contradictions=contradictions, reliability=reliability,
                 refusals=refusals, notes=notes)
