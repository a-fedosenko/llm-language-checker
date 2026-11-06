"""The adaptive ladder.

Never run a fixed number of items. Most languages are resolved by the gate alone,
which costs one model call each and no judge call; only the survivors are paid
for, and only the ambiguous ones are paid for twice.

    rung 1  designator selection, gate-scored, no judge call
            all candidates fail every item -> None, stop
    rung 2  judge what survived; a clear result stops here
    rung 3  borderline only: more items to tighten the interval

The designator sweep lives in rung 1 because an LLM has no language-code
interface -- a `None` verdict must mean "none under our best designator", never
"none under one arbitrary string" (docs/02, protocol 001).

**There is one traversal of the ladder, and it is a generator.** `ladder_steps`
yields a `Step` after every action and returns the result; `run_ladder` drains
it and is what every existing caller still uses. A step-at-a-time consumer --
the bench -- advances the same generator instead of walking the same
sequence a second time.

That shape is not a preference. Convention 11 says `runner.py` is the only
definition of "run a scan", and convention 9 records what breaking it cost: an
analysis harness re-implemented a production call, got it subtly wrong, and 68
bad verdicts reached a protocol's conclusions. A second walk of the ladder would
drift the same way, and the drift arrives looking like a finding.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generator, Iterator

from llmlc.bt import (Qualification, QualificationCache, QualStatus,
                      RemoteBackTranslator, route)
from llmlc.bt.qualify import MIN_CHRF, MIN_RECALL
from llmlc.probe import pivot as pivot_mod
from llmlc.client import OpenAICompatClient
from llmlc.db.models import NO_INSTRUMENT
from llmlc.probe import designator as dsg
from llmlc.probe.corpus import Corpus
from llmlc.probe.gate import GateVerdict
from llmlc.probe.score import Evidence, Score, score
from llmlc.probe.specs import Spec
from llmlc.probe.steps import ItemOutcome, generate_and_gate, judge_item
from llmlc.scheme import Language, Scheme

RUNG1_ITEMS = 3
RUNG3_ITEMS = 6

#: Gate verdicts that neither pass nor count against the model: the item is void,
#: not evidence. Memorised boilerplate, text too short to judge, and LID calls too
#: weak to convict on.
VOID = {GateVerdict.MEMORISED, GateVerdict.TOO_SHORT, GateVerdict.LOW_CONFIDENCE}


#: What each kind of step is for, in the terms the tool reports in. Served to
#: the bench with the step itself rather than restated in the page: text
#: describing what the code does belongs beside the code, or it goes stale the
#: first time a threshold moves.
STEP_HELP: dict[str, tuple[str, str]] = {
    "generated": (
        "Generate, then gate",
        "The model is given a scenario in the pivot language and asked to write "
        "it in the target language, choosing its own words. The reply goes "
        "straight into the local gate -- script, then language identification, "
        "then the degenerate and memorised checks. No paid call yet, which is "
        "why most negatives cost nothing.",
    ),
    "designator-trial": (
        "Score this designator",
        "An LLM has no language-code interface, so the name we ask by is a "
        "prompt parameter to optimise rather than a fact to look up. Each "
        "candidate is scored on how many of its items cleared the gate.",
    ),
    "designator-chosen": (
        "Keep the best designator",
        "Everything after this runs under one name, so a negative verdict means "
        "'none under our best designator' rather than 'none under one arbitrary "
        "string'.",
    ),
    "deterministic-negative": (
        "Stop: proven locally",
        "Every candidate failed every item. The verdict does not depend on "
        "reading the language back, so it needs no back-translator and holds "
        "against every one of them.",
    ),
    "qualification": (
        "Qualify the reader",
        "Before any score depends on the back-translator, it is given text in "
        "this language whose English meaning is already known and scored with "
        "chrF++ against the reference. A model that cannot read a language does "
        "not refuse -- it invents (protocol 005).",
    ),
    "unverified": (
        "Stop: cannot be verified",
        "No back-translator could be qualified for this language, so quality is "
        "not assessable. `no-control` is never a pass, and this is not a verdict "
        "about the model.",
    ),
    "judged": (
        "Back-translate, then judge",
        "The surviving text is read back into the pivot language, and a blind "
        "judge marks which of the specified facts survived the round trip. The "
        "judge never sees the target language.",
    ),
    "scored": (
        "Score it",
        "Eligibility first -- did the model write the language at all -- then "
        "adequacy over the items that cleared it, with a bootstrap interval. "
        "The tier is derived from the number and never replaces it.",
    ),
    "extra-item": (
        "Another item: the interval straddles the cut",
        "The result came back borderline, so more items are run to tighten the "
        "interval rather than rounding a number that cannot be stated flatly.",
    ),
}


def gate_tone(verdict: GateVerdict) -> str:
    """How a gate verdict should read at a glance.

    Three states, because the gate has three kinds of outcome and only two of
    them are about the model. `VOID` verdicts -- memorised text, too short, a
    language-ID call too weak to commit -- are neither a pass nor evidence
    against it, and colouring them like a failure would say the opposite of what
    the arithmetic does with them (protocol 018).
    """
    if verdict is GateVerdict.PASS:
        return "ok"
    if verdict in VOID:
        return "warn"
    return "bad"


@dataclass
class Step:
    """One action the ladder took, as it happened.

    Carries enough for a page to render it without reaching back into the
    pipeline, and `next_kind` so an interactive consumer can say what is about
    to happen *before* spending the call that does it.
    """

    kind: str
    rung: int
    summary: str
    detail: dict = field(default_factory=dict)
    calls: dict = field(default_factory=dict)
    next_kind: str | None = None
    terminal: bool = False
    #: "ok" | "warn" | "bad" | "" -- how this step reads at a glance. Decided
    #: here rather than in the page: whether a gate verdict is a failure or an
    #: abstention is a fact about the method, and a page re-deriving it would be
    #: a second opinion on the one question the gate exists to answer.
    tone: str = ""

    @property
    def title(self) -> str:
        return STEP_HELP.get(self.kind, (self.kind, ""))[0]

    @property
    def explains(self) -> str:
        return STEP_HELP.get(self.kind, ("", ""))[1]

    def as_dict(self) -> dict:
        nxt = STEP_HELP.get(self.next_kind or "")
        return {
            "kind": self.kind, "rung": self.rung, "title": self.title,
            "summary": self.summary, "explains": self.explains,
            "detail": self.detail, "calls": dict(self.calls),
            "terminal": self.terminal, "tone": self.tone,
            "next": ({"kind": self.next_kind, "title": nxt[0], "explains": nxt[1]}
                     if nxt else None),
        }


def item_detail(item: ItemOutcome) -> dict:
    """An item as the bench shows it. Deliberately the whole text: reading the
    raw output is how nearly every real defect in this project was found."""
    return {
        "spec_id": item.spec_id,
        "designator": item.designator,
        "prompt": item.prompt,
        "generation": item.generation,
        "gate": item.gate.verdict.value,
        "gate_detail": item.gate.detail,
        "lid": ({"label": item.gate.lid.label,
                 "confidence": round(item.gate.lid.confidence, 3),
                 "backend": item.gate.lid.backend}
                if item.gate.lid else None),
        "back_translation": item.back_translation,
        "verdicts": ([v.value for v in item.judgement.verdicts]
                     if item.judgement and item.judgement.ok else None),
        "recall": (round(item.judgement.recall, 3)
                   if item.judgement and item.judgement.ok else None),
        "error": item.error,
    }


@dataclass
class DesignatorTrial:
    kind: str                      # primary candidate kind
    value: str
    gate_pass: int
    attempts: int
    kinds: tuple[str, ...] = ()    # every candidate kind that produced this string

    def __post_init__(self) -> None:
        if not self.kinds:
            self.kinds = (self.kind,)

    @property
    def rate(self) -> float:
        return self.gate_pass / self.attempts if self.attempts else 0.0

    def is_(self, kind: str) -> bool:
        return kind in self.kinds


@dataclass
class LadderResult:
    tag: str
    engine: str
    language: Language
    designator: str
    designator_kinds: tuple[str, ...]
    trials: list[DesignatorTrial]
    score: Score
    items: list[ItemOutcome]
    backtranslator: str
    judge_model: str
    pivot: str
    qualification: Qualification
    rungs_run: int
    resolves_to: dict[str, int] = field(default_factory=dict)
    calls: dict[str, int] = field(default_factory=dict)
    inherited_from: str | None = None
    #: How this tag's *variant* claim was established, if at all. Filled by the
    #: scan rather than the ladder: the ladder measures a class, and a variant is
    #: a property of a tag within one (S6).
    variant: object | None = None

    @property
    def beat_incumbent(self) -> bool | None:
        """Whether the chosen designator outperformed the incumbent one.

        `None` means no comparison was possible -- either no incumbent was
        supplied, or the incumbent string was identical to another candidate and
        so was never a separate competitor. `False` means a comparison was made
        and selection did not beat the incumbent, which is a different fact.
        """
        incumbent = [t for t in self.trials if t.is_("E")]
        if len(incumbent) != 1 or len(incumbent[0].kinds) > 1:
            return None
        inc = incumbent[0]
        win = next((t for t in self.trials if t.value == self.designator), None)
        if win is None:
            return None
        return win.rate > inc.rate


def _refused(items: list[ItemOutcome]) -> int:
    return sum(1 for i in items if i.gate.verdict is GateVerdict.REFUSED)


def accepted_codes(lang: Language) -> set[str]:
    """Codes that also satisfy a request for this language -- a macrolanguage's
    members. Asking for `sw` and getting `swh` is resolution, not substitution."""
    return set(lang.members) if lang.is_macro else set()


def relative_codes(scheme: Scheme, lang: Language) -> set[str]:
    out: set[str] = set()
    if lang.macro:
        out.add(lang.macro)
        for other in scheme.languages.values():
            if other.iso639_3 == lang.macro and other.members:
                out.update(other.members)
    out.discard(lang.iso639_3 or "")
    return out - accepted_codes(lang)


def candidates_for(scheme: Scheme, lang: Language, incumbent: str | None = None):
    """The designators this language will actually be asked by.

    One definition, because two callers need it and they must not disagree: the
    ladder spends money on these, and the bench's pre-flight tells a reader
    what is about to be asked. A pre-flight built from a second copy of this
    logic would describe a run that is not the one about to happen -- the same
    failure as an analysis harness re-implementing a production call
    (convention 9).
    """
    from llmlc.probe.variant import is_script_variant

    # The region is named only when the *tag* carries one. `region_name` alone
    # is not that test: a locale list's unqualified tag has no region subtag and
    # still inherits a region name from the reference catalogue's likely-subtag
    # resolution -- `pt` carries "Brazil", `en` "United States", `sr` "Serbia".
    # Passing it unconditionally asked for `pt` with the identical designator as
    # `pt-br` ("Portuguese (Brazil)"), and for `en` as `en-us`, so the
    # unqualified tag -- the neutral arm a dialect is contrasted against -- was
    # silently asked to be a dialect, and the contrast was a null comparison by
    # construction.
    #
    # This is protocol 020's trigger in mirror image: there two tags shared one
    # prompt because the region was never passed, here because it was passed
    # where the tag had none. A designator must say exactly what the tag says.
    return dsg.candidates(lang, incumbent=incumbent,
                          region_name=lang.region_name if lang.region else None,
                          qualify_script=is_script_variant(scheme, lang) or None)


def run_ladder(**kw) -> LadderResult:
    """Run the ladder to completion. The one-shot path, and what every caller
    outside the bench uses.

    A drain over `ladder_steps`, not a second implementation of it: the result
    of running every step must be identical to the result of stepping through
    them, and the only way to guarantee that is for there to be one sequence.
    """
    gen = ladder_steps(**kw)
    while True:
        try:
            next(gen)
        except StopIteration as done:
            return done.value


def ladder_steps(
    *,
    scheme: Scheme,
    tag: str,
    engine: str,
    client: OpenAICompatClient,
    backtranslators: list[RemoteBackTranslator],
    judge_model: str,
    specs: list[Spec],
    corpus: Corpus,
    pivot: str = "en",
    incumbent: str | None = None,
    sweep_all: bool = False,
    cache: QualificationCache | None = None,
) -> Generator[Step, None, LadderResult]:
    """The ladder, yielding a `Step` after every action and returning the result.

    Every `yield` sits *after* the work it reports, so a consumer that stops
    early has already paid for what it has seen and nothing more.
    """
    lang = scheme.get(tag)
    if lang is None:
        raise KeyError(f"Unknown tag {tag!r} in scheme {scheme.meta.name!r}")

    accept = accepted_codes(lang)
    relatives = relative_codes(scheme, lang)
    candidates = candidates_for(scheme, lang, incumbent)
    calls = {"generation": 0, "backtranslation": 0, "judge": 0}
    resolves: dict[str, int] = {}

    def record_lid(item: ItemOutcome) -> None:
        if item.gate.lid and item.gate.lid.label:
            resolves[item.gate.lid.label] = resolves.get(item.gate.lid.label, 0) + 1

    # -- rung 1: designator selection, gate only -----------------------------
    trials: list[DesignatorTrial] = []
    best_items: list[ItemOutcome] = []
    best: DesignatorTrial | None = None

    for cand in candidates:
        items: list[ItemOutcome] = []
        for spec in specs[:RUNG1_ITEMS]:
            item = generate_and_gate(client=client, engine=engine, lang=lang,
                                     designator=cand.value, spec=spec, corpus=corpus,
                                     relatives=relatives, accept=accept)
            calls["generation"] += 1
            record_lid(item)
            items.append(item)
            yield Step("generated", 1,
                       f"{cand.value!r}: {item.gate.verdict.value}",
                       item_detail(item), calls, next_kind="generated",
                       tone=gate_tone(item.gate.verdict))

        trial = DesignatorTrial(cand.kind, cand.value,
                                sum(i.lang_ok for i in items), len(items),
                                kinds=cand.kinds)
        trials.append(trial)
        if best is None or trial.rate > best.rate:
            best, best_items = trial, items
        # A designator that carries every item is not improved on by trying more.
        done = not sweep_all and trial.rate == 1.0
        yield Step("designator-trial", 1,
                   f"{cand.value!r} cleared the gate on "
                   f"{trial.gate_pass} of {trial.attempts}",
                   {"designator": cand.value, "kinds": list(cand.kinds),
                    "gate_pass": trial.gate_pass, "attempts": trial.attempts,
                    "rate": round(trial.rate, 3),
                    "stopping_early": done,
                    "candidates_left": 0 if done else
                                       len(candidates) - len(trials)},
                   calls,
                   next_kind="designator-chosen" if done or len(trials) == len(candidates)
                             else "generated",
                   tone="ok" if trial.rate == 1.0 else "warn" if trial.rate else "bad")
        if done:
            break

    assert best is not None
    chosen = next(c for c in candidates if c.value == best.value)

    deterministic = best.rate == 0.0 and all(i.counts_against for i in best_items)
    yield Step("designator-chosen", 1,
               f"best designator {best.value!r} at {best.rate:.2f}",
               {"designator": best.value, "kinds": list(chosen.kinds),
                "rate": round(best.rate, 3),
                "trials": [{"designator": x.value, "kinds": list(x.kinds),
                            "gate_pass": x.gate_pass, "attempts": x.attempts,
                            "rate": round(x.rate, 3)} for x in trials]},
               calls,
               next_kind="deterministic-negative" if deterministic else "qualification",
               tone="ok" if best.rate == 1.0 else "warn" if best.rate else "bad")

    # Every candidate failed every item: the negative does not depend on reading
    # the language, so it stands regardless of the back-translator.
    if deterministic:
        yield Step("deterministic-negative", 1,
                   f"every candidate failed every item; "
                   f"{_refused(best_items)} refusal(s)",
                   {"refusals": _refused(best_items),
                    "verdicts": [i.gate.verdict.value for i in best_items]},
                   calls, terminal=True, tone="bad")
        return LadderResult(
            tag=tag, engine=engine, language=lang, designator=best.value,
            designator_kinds=chosen.kinds, trials=trials,
            score=score(
                # Items the model *attempted* and got wrong still count as
                # attempts. Passing an empty list here made a model that answered
                # every item in the wrong script indistinguishable from one that
                # refused every item -- reliability 0.0 for a model that was
                # entirely willing.
                lang_pass=[False] * (len(best_items) - _refused(best_items)),
                content=[], evidence=Evidence.DETERMINISTIC_NEGATIVE,
                refusals=_refused(best_items)),
            items=best_items, backtranslator=NO_INSTRUMENT, judge_model=judge_model,
            pivot=pivot,
            qualification=Qualification(QualStatus.NO_CONTROL, 0.0, NO_INSTRUMENT, tag,
                                        "", "Deterministic negative: no back-translation "
                                            "was required to reach this verdict."),
            rungs_run=1, resolves_to=resolves, calls=calls)

    # -- qualify the instrument before any score depends on it ---------------
    # A language that is itself the pivot is measured through a different one:
    # back-translating English into English grades nothing (see probe/pivot.py).
    backtranslators, pivot, controls = pivot_mod.panel_for(
        scheme, lang, pivot, backtranslators)
    tried: list = []
    bt, qual = route(backtranslators, client, judge_model, tag,
                     controls=controls, cache=cache, scheme=scheme,
                     attempts=tried)
    yield Step("qualification", 2,
               f"{bt.id}: {qual.status.value}"
               + (f" at {qual.score:.1f}" if qual.kind == "reference" else ""),
               {"backtranslator": bt.id, "status": qual.status.value,
                "score": round(qual.score, 2), "kind": qual.kind,
                "detail": qual.detail, "pivot": pivot,
                "trustworthy": qual.trustworthy,
                # The panel in the order it was tried, so "why this reader" is
                # answerable from the page rather than from the source.
                "panel": [b.id for b in backtranslators],
                "attempts": [{"backtranslator": q.backtranslator,
                              "status": q.status.value,
                              "score": round(q.score, 2), "kind": q.kind,
                              "detail": q.detail} for q in tried],
                "threshold": (MIN_CHRF if qual.kind == "reference"
                              else MIN_RECALL if qual.kind == "facts" else None)},
               calls,
               next_kind="judged" if qual.trustworthy else "unverified",
               tone="ok" if qual.trustworthy else "bad")

    def finish(items: list[ItemOutcome], rungs: int) -> LadderResult:
        contents = [i.content for i in items if i.content is not None]
        notes = []
        if any(i.gate.verdict is GateVerdict.RELATIVE_SUBSTITUTION for i in items):
            notes.append("Model produced a neighbouring language rather than the target.")
        if not qual.trustworthy:
            evidence = Evidence.UNVERIFIED
            notes.append(f"Back-translator {qual.backtranslator} is {qual.status.value} "
                         f"for {tag}: {qual.detail}")
        elif not contents:
            evidence = Evidence.UNVERIFIED
        else:
            evidence = Evidence.FACT_RECALL
        refused = [i for i in items if i.gate.verdict is GateVerdict.REFUSED]
        graded = [i for i in items
                  if i.gate.verdict not in VOID and i.gate.verdict is not GateVerdict.REFUSED]
        return LadderResult(
            tag=tag, engine=engine, language=lang, designator=best.value,
            designator_kinds=chosen.kinds, trials=trials,
            score=score(lang_pass=[i.lang_ok for i in graded], content=contents,
                        evidence=evidence, refusals=len(refused),
                        contradictions=sum(i.judgement.contradictions for i in items
                                           if i.judgement and i.judgement.ok),
                        notes=notes),
            items=items, backtranslator=bt.id, judge_model=judge_model, pivot=pivot,
            qualification=qual, rungs_run=rungs, resolves_to=resolves, calls=calls)

    if not qual.trustworthy:
        yield Step("unverified", 2,
                   f"no qualified reader for {tag}: {qual.detail or qual.status.value}",
                   {"backtranslator": qual.backtranslator,
                    "status": qual.status.value, "detail": qual.detail},
                   # Not red: no reader could be qualified, which is a statement
                   # about the instrument and not a verdict about the model.
                   calls, terminal=True, tone="warn")
        return finish(best_items, 2)

    # -- rung 2: judge what survived the gate --------------------------------
    by_id = {s.id: s for s in specs}
    gradeable = [i for i in best_items if i.lang_ok]
    for n, item in enumerate(gradeable, 1):
        judge_item(item, client=client, judge_model=judge_model, backtranslator=bt,
                   spec=by_id[item.spec_id], tag=tag, corpus=corpus)
        calls["backtranslation"] += 1
        calls["judge"] += 1
        yield Step("judged", 2,
                   f"{item.spec_id}: recall "
                   + (f"{item.judgement.recall:.2f}"
                      if item.judgement and item.judgement.ok else "unavailable"),
                   item_detail(item), calls,
                   next_kind="judged" if n < len(gradeable) else "scored",
                   tone=_recall_tone(item))

    result = finish(best_items, 2)
    yield Step("scored", 2, _score_summary(result.score),
               _score_detail(result.score), calls,
               terminal=not result.score.borderline,
               next_kind="extra-item" if result.score.borderline else None,
               tone=_tier_tone(result.score))
    if not result.score.borderline:
        return result

    # -- rung 3: borderline only, more items to tighten the interval ---------
    extra = specs[RUNG1_ITEMS: RUNG1_ITEMS + RUNG3_ITEMS]
    for n, spec in enumerate(extra, 1):
        item = generate_and_gate(client=client, engine=engine, lang=lang,
                                 designator=best.value, spec=spec, corpus=corpus,
                                 relatives=relatives, accept=accept)
        calls["generation"] += 1
        record_lid(item)
        if item.lang_ok:
            judge_item(item, client=client, judge_model=judge_model, backtranslator=bt,
                       spec=spec, tag=tag, corpus=corpus)
            calls["backtranslation"] += 1
            calls["judge"] += 1
        best_items.append(item)
        yield Step("extra-item", 3,
                   f"{spec.id}: {item.gate.verdict.value}"
                   + (f", recall {item.judgement.recall:.2f}"
                      if item.judgement and item.judgement.ok else ""),
                   item_detail(item), calls,
                   next_kind="extra-item" if n < len(extra) else "scored",
                   tone=gate_tone(item.gate.verdict) if not item.lang_ok
                        else _recall_tone(item))

    final = finish(best_items, 3)
    yield Step("scored", 3, _score_summary(final.score), _score_detail(final.score),
               calls, terminal=True, tone=_tier_tone(final.score))
    return final


def _recall_tone(item: ItemOutcome) -> str:
    """An item that was judged, by how much of the meaning came back.

    The cut is the adequacy cut, so a green item is one that would carry a
    `Proficient` verdict on its own -- the colour and the tier agree rather than
    being two separate opinions about the same number.
    """
    from llmlc.probe.score import PROFICIENT_MIN_CONTENT

    if item.judgement is None or not item.judgement.ok:
        return "warn"
    if item.judgement.recall >= PROFICIENT_MIN_CONTENT:
        return "ok"
    return "warn" if item.judgement.recall else "bad"


def _tier_tone(s: Score) -> str:
    from llmlc.probe.score import Tier

    return {Tier.PROFICIENT: "ok", Tier.ASSISTED: "warn", Tier.UNUSABLE: "bad"}[s.tier]


def _score_summary(s: Score) -> str:
    return (f"{s.tier.value} — eligibility {s.s_lang:.2f}, adequacy {s.s_content:.2f} "
            f"[{s.ci[0]:.2f}, {s.ci[1]:.2f}]"
            + (" (borderline)" if s.borderline else ""))


def _score_detail(s: Score) -> dict:
    d = s.as_dict()
    # The workflow sentence is what a planner actually reads, and it carries the
    # availability caveat the tier deliberately does not.
    d["workflow"] = s.workflow
    return d
