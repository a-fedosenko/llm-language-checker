"""Who attests, and whether their answer is worth counting.

An attestor's verdict is never trusted on faith. The marker instrument was
retired because authoring a corpus does not scale; replacing it with "ask a
model and believe it" would trade an unscalable instrument for an unreliable
one, which is worse — a model handed a question about a dialect it does not
know will answer anyway, fluently, and nothing in the output says so.

So every attestor is checked, per dialect family, by **controls we manufacture
rather than collect**. That is the whole reason this escapes the problem that
killed the marker sets: a control here is constructed from the texts already in
hand, needs no speaker of the language, and its correct answer is certain by
construction rather than by authority.

Two controls, and between them they catch the failure that matters:

  identity   the same text shown as both halves of a pair. The correct answer
             is `indistinguishable`, necessarily, because the two texts *are*
             the same text. An attestor that names two different varieties here
             is manufacturing differences, which is precisely the false
             evidence the redesign exists to avoid.
  order      one real pair shown twice, in both orders. A reliable attestor's
             answers swap with the presentation; one answering by position
             gives the same answer both times. Position bias would otherwise
             read as dialect knowledge, and reads as it most strongly on the
             families where we most want a positive.

**What these cannot catch, stated plainly:** an attestor that answers
`indistinguishable` to everything passes both. Detecting over-merging needs a
pair known to be distinguishable, and knowing that independently is exactly
what we do not have for an arbitrary dialect. It is available for Serbian and
English, where protocol 012 measured `proven` at 1.00 — which is why those two
families are in protocol 021's sample as calibration rather than as subjects.
For the rest, over-merging is indistinguishable from a true negative, and a
negative result there must be reported as "no evidence of a difference" rather
than "no difference".

**The record routes, it does not vouch.** A stored capability decides who is
asked first; controls decide whether the answer is believed, and they run every
time regardless of what the record says. Without that rule an attestor wrongly
recorded as competent keeps being asked and keeps being believed, and the error
becomes self-confirming — the record would become the thing it replaced: a
stored claim that quietly goes stale while everything downstream trusts it.
A stale record costs wasted routing, never a wrong verdict. A cache, not an
authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from llmlc.client import OpenAICompatClient
from llmlc.probe import attest
from llmlc.probe.attest import Blind
from llmlc.probe.corpus import Corpus, Record


class Role(str, Enum):
    """The three competences, kept apart because they dissociate.

    A model can spot ijekavian reliably and still mistranslate what the sentence
    says; another can understand it perfectly and produce only generic Serbian.
    One score over all three would hide which, and "supports the dialect" would
    mean nothing in particular.
    """

    GENERATION = "generation"           # can it *write* the variety distinctly
    DISCRIMINATION = "discrimination"   # can it *tell* the variety from its siblings
    COMPREHENSION = "comprehension"     # can it *recover meaning* from the variety


class ControlKind(str, Enum):
    IDENTITY = "identity"
    ORDER = "order"


@dataclass
class ControlResult:
    kind: ControlKind
    passed: bool
    detail: str = ""
    raw: str | None = None

    def as_dict(self) -> dict:
        return {"kind": self.kind.value, "passed": self.passed, "detail": self.detail}


@dataclass
class Competence:
    """Whether one attestor's answers about one family may be counted at all.

    Per *dialect family*, not per model. A strong engine can be a weak attestor
    for one variety, and the record has to be able to say so rather than letting
    its silence pass for evidence.
    """

    attestor: str
    family: str
    controls: list[ControlResult] = field(default_factory=list)
    error: str | None = None

    @property
    def qualified(self) -> bool:
        """Every control passed. Not a majority: each control tests a different
        way of being wrong, and failing either is disqualifying on its own."""
        return (self.error is None and bool(self.controls)
                and all(c.passed for c in self.controls))

    @property
    def failed(self) -> list[str]:
        return [c.kind.value for c in self.controls if not c.passed]

    def as_dict(self) -> dict:
        return {"attestor": self.attestor, "family": self.family,
                "qualified": self.qualified, "failed": self.failed,
                "controls": [c.as_dict() for c in self.controls],
                "error": self.error}


def identity_control(client: OpenAICompatClient, attestor: str, *, text: str,
                     blind: Blind, tag: str, corpus: Corpus) -> ControlResult:
    """Show one text as both halves of a pair. It cannot be two varieties.

    The strongest control available without a speaker, because its answer is not
    a judgement at all — it is an identity. Any answer that splits the pair is
    the attestor inventing a difference between a text and itself.

    `separate` salts the presentation order by the texts, so with two identical
    texts the order is moot and nothing about the construction is visible to the
    attestor: it sees an ordinary pair.
    """
    sep = attest.separate(client, attestor, first=text, second=text, blind=blind)
    corpus.write(Record("control", attestor, tag, "identity", None,
                        "[identity control: the same text as both halves]",
                        sep.raw, sep.error,
                        meta={"a": sep.a, "b": sep.b, "split": sep.split}))
    if sep.error:
        return ControlResult(ControlKind.IDENTITY, False,
                             f"no usable answer: {sep.error}", sep.raw)
    if sep.split:
        return ControlResult(
            ControlKind.IDENTITY, False,
            f"named {sep.a!r} and {sep.b!r} for two copies of one text", sep.raw)
    return ControlResult(ControlKind.IDENTITY, True,
                         f"did not split a text from itself ({sep.a!r})", sep.raw)


def order_control(client: OpenAICompatClient, attestor: str, *, first: str, second: str,
                  blind: Blind, tag: str, corpus: Corpus) -> ControlResult:
    """Ask the same pair twice and check the answer follows the texts.

    The two orders are **forced**, not obtained by swapping the arguments.
    Swapping flips which text is `first` and re-salts the presentation coin, so
    when the two coins agree the attestor sees the same order twice — 1,014 of
    2,000 pairs by measurement. The control would then have been a repeat test
    about half the time, passing a position-answering attestor for exactly the
    half of cases it exists to catch.

    A position-answering attestor says "A is the first option, B is the second"
    both times. That failure is invisible in any single answer and would be read
    as dialect knowledge precisely where we most want a positive.
    """
    a = attest.separate(client, attestor, first=first, second=second, blind=blind,
                        present=False)
    b = attest.separate(client, attestor, first=first, second=second, blind=blind,
                        present=True)
    for i, s in enumerate((a, b)):
        corpus.write(Record("control", attestor, tag, f"order-{i + 1}", None,
                            "[order control: one pair, both presentations]",
                            s.raw, s.error,
                            meta={"a": s.a, "b": s.b, "swapped": s.swapped}))

    if a.error or b.error:
        return ControlResult(ControlKind.ORDER, False,
                             f"no usable answer: {a.error or b.error}")
    # Unscramble both into the caller's own order, then compare. If the answer
    # follows the text, the two readings agree; if it follows the slot, they do
    # not. Both merging and both declining also agree, and are not evidence of
    # position bias -- this control tests consistency, not confidence.
    def settled(s):
        return (s.b, s.a) if s.swapped else (s.a, s.b)

    if settled(a) == settled(b):
        return ControlResult(ControlKind.ORDER, True,
                             "the answer followed the text, not the slot")
    return ControlResult(
        ControlKind.ORDER, False,
        f"answered {a.a!r}/{a.b!r} then {b.a!r}/{b.b!r}: the answer followed the "
        "position rather than the text")


def qualify_attestor(client: OpenAICompatClient, attestor: str, *, family: str,
                     blind: Blind, neutral: str, first: str, second: str,
                     tag: str, corpus: Corpus) -> Competence:
    """Run both controls for one attestor on one family.

    Costs three calls. Paid once per (attestor, family) in a run, and not
    cached across runs: a competence record routes, it does not vouch, so the
    controls run every time.
    """
    out = Competence(attestor, family)
    out.controls.append(identity_control(client, attestor, text=neutral, blind=blind,
                                         tag=tag, corpus=corpus))
    out.controls.append(order_control(client, attestor, first=first, second=second,
                                      blind=blind, tag=tag, corpus=corpus))
    return out


# -- the panel ----------------------------------------------------------------

def eligible(attestors: list[str], *, producer: str) -> list[str]:
    """Attestors a producer's own output may be shown to.

    Drops the producer's whole **family**, not just its id -- the S8 panel rule,
    and for the same reason protocol 005 established it: a model grading its own
    output measures self-consistency and reports it as agreement. Two ids from
    one vendor are near enough to the same reader that the guard has to cut at
    the family.
    """
    from llmlc.runner import model_family

    fam = model_family(producer)
    return [a for a in attestors if model_family(a) != fam and a != producer]


def order_by_record(attestors: list[str], *, known: dict[str, bool] | None = None,
                    ) -> list[str]:
    """Ask the likely-qualified first, without ever skipping the controls.

    `known` is what a stored capability record says about this family, keyed by
    attestor: True qualified before, False did not, absent never tried. It
    reorders and nothing else -- every attestor returned still faces the
    controls, and one recorded as failing is still *tried*, because a record is
    a cache of a past measurement and models change under a fixed id.

    Early in a scan the record is empty and this is the identity function, which
    is why the first engine scanned is the expensive one and every later scan is
    cheaper.
    """
    known = known or {}
    return sorted(attestors, key=lambda a: (0 if known.get(a) is True
                                            else 1 if a not in known else 2,
                                            attestors.index(a)))


@dataclass
class Panel:
    """The attestors that answered for one family, and what each was worth."""

    competences: list[Competence] = field(default_factory=list)

    @property
    def qualified(self) -> list[str]:
        return [c.attestor for c in self.competences if c.qualified]

    @property
    def disqualified(self) -> list[str]:
        return [c.attestor for c in self.competences if not c.qualified]

    @property
    def empty(self) -> bool:
        """No competent attestor. A *result* -- `indeterminate` -- and never to
        be folded into a negative: "nobody could check" is not "the model
        cannot do it", and reporting it as the second is the error protocol 005
        exists to prevent."""
        return not self.qualified

    @property
    def single(self) -> bool:
        """One qualified member. Usable, but a verdict from it is stamped
        lower-confidence rather than silently promoted to a panel result."""
        return len(self.qualified) == 1

    def as_dict(self) -> dict:
        return {"qualified": self.qualified, "disqualified": self.disqualified,
                "empty": self.empty, "single": self.single,
                "competences": [c.as_dict() for c in self.competences]}


@dataclass
class Vote:
    """One qualified attestor's answer to one question, for aggregation."""

    attestor: str
    correct: bool
    abstained: bool = False


@dataclass
class Consensus:
    """What a panel of qualified attestors concluded, disagreement intact."""

    votes: list[Vote] = field(default_factory=list)

    @property
    def counted(self) -> list[Vote]:
        """Abstentions are not votes. An attestor saying "generic" or
        "indistinguishable" has answered honestly about the text, and counting
        that as a wrong answer would convict the model for the attestor's
        candour."""
        return [v for v in self.votes if not v.abstained]

    @property
    def agreed(self) -> bool | None:
        """True when every counted vote says correct, False when every one says
        wrong, None when they disagree.

        **Disagreement is stored as disagreement**, never averaged. A mean over
        three judges who split two-to-one reports 0.67 and hides that one of
        them read the text completely differently — which is the finding, not
        the noise.
        """
        counted = self.counted
        if not counted:
            return None
        if all(v.correct for v in counted):
            return True
        if not any(v.correct for v in counted):
            return False
        return None

    @property
    def split(self) -> bool:
        return self.agreed is None and len(self.counted) > 1

    def as_dict(self) -> dict:
        return {"agreed": self.agreed, "split": self.split,
                "votes": [{"attestor": v.attestor, "correct": v.correct,
                           "abstained": v.abstained} for v in self.votes]}


# -- the capability record ----------------------------------------------------

@dataclass(frozen=True)
class CapabilityKey:
    """What a capability claim is about.

    The `snapshot` is the model id and nothing more, by the owner's decision:
    vendor endpoints change silently under a fixed id, and pinning a date we
    cannot verify would be a precision we do not have. `measured_at` on the
    record is what carries the age, and the honest reading of a record is "this
    was true of whatever answered to that id on that date".
    """

    model: str
    tag: str
    role: Role
    script: str | None = None

    def as_dict(self) -> dict:
        return {"model": self.model, "tag": self.tag, "role": self.role.value,
                "script": self.script}


@dataclass
class Capability:
    """One measured claim: this model, this variety, this role.

    A byproduct of scanning somebody else. Measuring deepseek's generation puts
    every attestor on the panel through controls for the same family, so the
    first engine scanned is the expensive one and each later scan is cheaper --
    which is what makes a five-family battery affordable at all.
    """

    key: CapabilityKey
    qualified: bool
    confidence: str = "medium"       # high | medium | low
    probes: list[str] = field(default_factory=list)
    detail: str = ""
    measured_at: float | None = None

    def as_dict(self) -> dict:
        return {**self.key.as_dict(), "qualified": self.qualified,
                "confidence": self.confidence, "probes": list(self.probes),
                "detail": self.detail, "measured_at": self.measured_at}


class CapabilityRecord:
    """Stored capability claims, used for routing only.

    Named in full rather than `Record`, which is `corpus.Record` in this module
    and would silently shadow it -- the corpus write inside `identity_control`
    is a positional call, so the shadow was a TypeError at the first control
    rather than anything legible.

    The invariant this class exists to make structural: **it can reorder who is
    asked, and it can never decide whether an answer is believed.** `known()`
    returns a routing hint; there is deliberately no method that returns "this
    attestor is trustworthy, skip its controls", because the moment one existed
    someone would call it and a wrongly-recorded attestor would become
    permanently self-confirming.

    This is the in-memory shape. Persistence is a separate concern and lands
    with the verdict ladder; nothing here knows about a database, so the probes
    can be tested and the bench driven with no store at all.
    """

    def __init__(self, rows: list[Capability] | None = None) -> None:
        self._rows: dict[CapabilityKey, Capability] = {}
        for r in rows or []:
            self.put(r)

    def put(self, cap: Capability) -> Capability:
        self._rows[cap.key] = cap
        return cap

    def get(self, key: CapabilityKey) -> Capability | None:
        return self._rows.get(key)

    def known(self, attestors: list[str], *, tag: str, role: Role,
              script: str | None = None) -> dict[str, bool]:
        """Routing hints for `order_by_record`: attestor -> qualified-before.

        Absent means never measured, which is different from measured-and-failed
        and is ordered differently: an unknown attestor is worth trying before
        one that failed, and both are still tried.
        """
        out: dict[str, bool] = {}
        for a in attestors:
            row = self.get(CapabilityKey(a, tag, role, script))
            if row is not None:
                out[a] = row.qualified
        return out

    def rows(self) -> list[Capability]:
        return list(self._rows.values())


def capabilities_from(panel: Panel, *, tag: str, role: Role,
                      script: str | None = None, probes: list[str] | None = None,
                      ) -> list[Capability]:
    """Turn a run's control outcomes into records, negatives included.

    A disqualified attestor is as much a measurement as a qualified one, and
    recording only the successes would make the record look like a list of
    models that work while silently dropping the evidence that the others do
    not.
    """
    out = []
    for c in panel.competences:
        out.append(Capability(
            key=CapabilityKey(c.attestor, tag, role, script),
            qualified=c.qualified,
            confidence="high" if c.qualified else "medium",
            probes=list(probes or []),
            detail=("passed every control" if c.qualified
                    else f"failed: {', '.join(c.failed) or c.error or 'no controls run'}"),
        ))
    return out
