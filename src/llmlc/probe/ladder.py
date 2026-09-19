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
"""
from __future__ import annotations

from dataclasses import dataclass, field

from llmlc.bt import (Qualification, QualificationCache, QualStatus,
                      RemoteBackTranslator, route)
from llmlc.probe import pivot as pivot_mod
from llmlc.client import OpenAICompatClient
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


def run_ladder(
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
) -> LadderResult:
    lang = scheme.get(tag)
    if lang is None:
        raise KeyError(f"Unknown tag {tag!r} in scheme {scheme.meta.name!r}")

    accept = accepted_codes(lang)
    relatives = relative_codes(scheme, lang)
    from llmlc.probe.variant import is_script_variant
    candidates = dsg.candidates(lang, incumbent=incumbent,
                                qualify_script=is_script_variant(scheme, lang) or None)
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

        trial = DesignatorTrial(cand.kind, cand.value,
                                sum(i.lang_ok for i in items), len(items),
                                kinds=cand.kinds)
        trials.append(trial)
        if best is None or trial.rate > best.rate:
            best, best_items = trial, items
        # A designator that carries every item is not improved on by trying more.
        if not sweep_all and trial.rate == 1.0:
            break

    assert best is not None
    chosen = next(c for c in candidates if c.value == best.value)

    # Every candidate failed every item: the negative does not depend on reading
    # the language, so it stands regardless of the back-translator.
    if best.rate == 0.0 and all(i.counts_against for i in best_items):
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
            items=best_items, backtranslator="(not needed)", judge_model=judge_model,
            pivot=pivot,
            qualification=Qualification(QualStatus.NO_CONTROL, 0.0, "(not needed)", tag,
                                        "", "Deterministic negative: no back-translation "
                                            "was required to reach this verdict."),
            rungs_run=1, resolves_to=resolves, calls=calls)

    # -- qualify the instrument before any score depends on it ---------------
    # A language that is itself the pivot is measured through a different one:
    # back-translating English into English grades nothing (see probe/pivot.py).
    backtranslators, pivot, controls = pivot_mod.panel_for(
        scheme, lang, pivot, backtranslators)
    bt, qual = route(backtranslators, client, judge_model, tag,
                     controls=controls, cache=cache)

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
        return finish(best_items, 2)

    # -- rung 2: judge what survived the gate --------------------------------
    by_id = {s.id: s for s in specs}
    for item in best_items:
        if item.lang_ok:
            judge_item(item, client=client, judge_model=judge_model, backtranslator=bt,
                       spec=by_id[item.spec_id], tag=tag, corpus=corpus)
            calls["backtranslation"] += 1
            calls["judge"] += 1

    result = finish(best_items, 2)
    if not result.score.borderline:
        return result

    # -- rung 3: borderline only, more items to tighten the interval ---------
    extra = specs[RUNG1_ITEMS: RUNG1_ITEMS + RUNG3_ITEMS]
    for spec in extra:
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

    return finish(best_items, 3)
