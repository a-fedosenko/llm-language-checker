"""Reading a stored result as a support status.

The one place a result row becomes the five-value answer a non-specialist asked
for. Used by the API, the UI and the export adapters, because a second mapping
is a second policy -- and this is a mapping where a wrong branch would publish a
false claim rather than merely look odd.

**Five values, not four.** The fourth and fifth are the project's whole thesis:

    unsupported    the deterministic gate convicted the model locally. *Proven*,
                   needs no control, sound at full catalogue breadth.
    unverifiable   the model wrote something and no back-translator could be
                   qualified for the language, so quality is not assessable.

Collapsing the second into the first reports a failure of the instrument as a
failure of the model, which is exactly the error protocol 005 exists to prevent;
collapsing it into `unchecked` claims nobody looked, when in fact calls were
spent and the answer came back unreadable. On the 602-locale scan `unverifiable`
is the largest bucket at 115-118 rows per engine, and it is the set a control
text would drain (see `data/results/control_gap.json`).

**Status follows eligibility, not the tier.** `Proficient` and `Assisted` both
read as `supported`, and the adequacy number carries the quality. That is the
architecture rather than a simplification of it: eligibility decides membership
and then stops, adequacy is the measurement (protocol 018). The open protocol on
the `Assisted`/`Proficient` cut may yet justify a third positive value, and this
function is the only place that would change.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Status(str, Enum):
    SUPPORTED = "supported"
    SUPPORTED_VIA_DIALECT = "supported-via-dialect"
    UNSUPPORTED = "unsupported"
    UNVERIFIABLE = "unverifiable"
    UNCHECKED = "unchecked"


#: Display order, worst-known-last. Also the order the filter chips appear in.
ORDER = [Status.SUPPORTED, Status.SUPPORTED_VIA_DIALECT, Status.UNSUPPORTED,
         Status.UNVERIFIABLE, Status.UNCHECKED]

#: Named unions of statuses, for filters that answer a question the five
#: individual values do not. `usable` is the routing question -- can this model
#: be pointed at this locale at all -- and it deliberately spans a measurement
#: and an inheritance, which is why it is a *filter* and never a sixth status:
#: the rows under it still say which of the two they are, and the weaker claim
#: stays visible in the row rather than being absorbed into the label.
GROUPS: dict[str, tuple[Status, ...]] = {
    "usable": (Status.SUPPORTED, Status.SUPPORTED_VIA_DIALECT),
}

GROUP_MEANING = {
    "usable": "Everything the model can be pointed at: measured directly, or "
              "inheriting its base language's result. The rows still say which.",
}

MEANING = {
    Status.SUPPORTED:
        "The model wrote this language, and a qualified reader confirmed the "
        "meaning survived.",
    Status.SUPPORTED_VIA_DIALECT:
        "Not probed directly. This tag inherits its base language's result, "
        "which says nothing about whether the model marks this variant.",
    Status.UNSUPPORTED:
        "Proven locally: the model refused, or wrote the wrong language or "
        "script. No back-translator was needed to establish it.",
    Status.UNVERIFIABLE:
        "The model wrote something, but no back-translator could be qualified "
        "for this language, so quality cannot be assessed. Not a verdict about "
        "the model.",
    Status.UNCHECKED:
        "Never probed with this model.",
}

#: Evidence values that settle the status before anything else is consulted.
#: A future human-attested class joins this table rather than the branches below:
#: it is a different kind of evidence, and must never be averaged into a score.
_BY_EVIDENCE = {
    "unverified": Status.UNVERIFIABLE,
    "deterministic-negative": Status.UNSUPPORTED,
}

#: Interval width at or below which the adequacy number is called firm. The
#: measure saturates -- 52% of graded rows have a zero-width interval because
#: every item scored the same -- so these cuts separate "every item agreed" from
#: "three items disagreed and the mean is a shrug".
CONFIDENCE_CUTS = ((0.20, "high"), (0.40, "medium"))


def confidence_for(ci_low: float | None, ci_high: float | None) -> str | None:
    """How firm the adequacy number is, from the width of its interval.

    Deliberately independent of `borderline`, which is a different statement --
    that the interval spans the tier cut -- and is published beside this rather
    than blended into it. Two axes that mean different things stay two axes
    (the same reasoning as tier vs availability, protocol 011).
    """
    if ci_low is None or ci_high is None:
        return None
    width = abs(ci_high - ci_low)
    for cut, label in CONFIDENCE_CUTS:
        if width <= cut:
            return label
    return "low"


@dataclass(frozen=True)
class SupportRow:
    """One language, for one engine, as the table shows it."""

    tag: str
    name: str | None
    status: Status
    #: Adequacy, or None where there is no measurement to show. Never 0.0 as a
    #: stand-in: a deterministic negative stores 0.0 by construction, and
    #: rendering it as a score invites reading a convention as a result.
    score: float | None = None
    confidence: str | None = None
    borderline: bool = False
    #: Which back-translator answered, so a mixed table is legible rather than
    #: silently collapsed (convention 4).
    backtranslator: str | None = None
    inherited_from: str | None = None
    local_name: str | None = None
    script: str | None = None

    def as_dict(self) -> dict:
        return {"tag": self.tag, "name": self.name, "local_name": self.local_name,
                "script": self.script, "status": self.status.value,
                "score": self.score, "confidence": self.confidence,
                "borderline": self.borderline,
                "backtranslator": self.backtranslator,
                "inherited_from": self.inherited_from}


def status_for(row) -> Status:
    """The five-value status of one result row, or `UNCHECKED` for no row.

    Order matters and is not arbitrary. Evidence is consulted first because an
    unreadable or gate-convicted result is settled regardless of what else the
    row says; inheritance is consulted last because it only ever reclassifies
    something that would otherwise have been `supported` -- an inherited tag
    whose base language failed is unsupported, not supported-via-dialect.
    """
    if row is None:
        return Status.UNCHECKED
    by_evidence = _BY_EVIDENCE.get(getattr(row, "evidence", None))
    if by_evidence is not None:
        return by_evidence
    # Graded, but the gate still rejected most items: eligible is a floor, and
    # failing it is a proven negative however it was arrived at.
    if getattr(row, "tier", None) == "Unusable":
        return Status.UNSUPPORTED
    if getattr(row, "inherited_from", None):
        return Status.SUPPORTED_VIA_DIALECT
    return Status.SUPPORTED


def row_for(tag: str, result, lang=None, borrowed_from: str | None = None) -> SupportRow:
    """Build the display row. `result` may be None, meaning never probed.

    `borrowed_from` names a *different* tag the result was actually measured
    under -- a scheme's canonical alias, so a TMS locale `ar-eg` can show what
    was measured for `ar`. That is a weaker claim than a measurement of `ar-eg`
    itself and is labelled as one: inheriting a tier is not inheriting a claim
    (convention 12), and the whole reason `supported-via-dialect` exists is to
    keep "we measured this" apart from "we measured its base language".
    """
    status = status_for(result)
    if borrowed_from and status is Status.SUPPORTED:
        status = Status.SUPPORTED_VIA_DIALECT
    scored = status in (Status.SUPPORTED, Status.SUPPORTED_VIA_DIALECT)
    return SupportRow(
        tag=tag,
        name=getattr(lang, "name", None),
        local_name=getattr(lang, "local_name", None),
        script=getattr(lang, "script", None),
        status=status,
        score=round(result.s_content, 3) if scored and result is not None else None,
        confidence=(confidence_for(result.ci_low, result.ci_high)
                    if scored and result is not None else None),
        borderline=bool(getattr(result, "borderline", False)) if scored else False,
        backtranslator=getattr(result, "backtranslator", None) if result is not None else None,
        inherited_from=(getattr(result, "inherited_from", None) or borrowed_from
                        if result is not None else None),
    )
