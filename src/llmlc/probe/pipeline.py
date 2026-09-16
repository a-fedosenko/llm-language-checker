"""The measurement path, end to end.

    designator -> generate -> gate -> back-translate -> judge -> tier

S1 runs it for one language with a single designator. S2 adds the designator
sweep and the adaptive ladder; the path itself does not change.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from llmlc.bt import Qualification, QualificationCache, RemoteBackTranslator, route
from llmlc.client import OpenAICompatClient
from llmlc.probe import designator as dsg
from llmlc.probe.corpus import Corpus, Record
from llmlc.probe.gate import GateResult, GateVerdict, check as gate_check
from llmlc.probe.judge import Judgement, judge as run_judge
from llmlc.probe.score import Evidence, Score, score
from llmlc.probe.specs import Spec
from llmlc.scheme import Language, Scheme


@dataclass
class ItemOutcome:
    spec_id: str
    designator: str
    generation: str | None
    gate: GateResult
    back_translation: str | None = None
    judgement: Judgement | None = None
    error: str | None = None

    @property
    def lang_ok(self) -> bool:
        return self.gate.passed

    @property
    def content(self) -> float | None:
        return self.judgement.recall if self.judgement and self.judgement.ok else None


@dataclass
class CheckResult:
    tag: str
    engine: str
    language: Language
    designator: str
    score: Score
    items: list[ItemOutcome]
    backtranslator: str
    judge_model: str
    pivot: str
    qualification: Qualification
    resolves_to: dict[str, int] = field(default_factory=dict)


def _accepted(scheme: Scheme, lang: Language) -> set[str]:
    """Codes that also satisfy a request for `lang`.

    A macrolanguage is an addressing convention, not a linguistic entity: asking
    for `sw` and getting `swh` means the macrolanguage resolved to a member,
    which is the answer. Which member it resolved to is recorded in resolves_to.
    """
    return set(lang.members) if lang.is_macro else set()


def _relatives(scheme: Scheme, lang: Language) -> set[str]:
    """High-resource neighbours whose appearance means substitution.

    Members of the same macrolanguage, plus the macrolanguage itself -- the
    family relation that docs/02 showed models actually fall back on.
    """
    out: set[str] = set()
    if lang.macro:
        out.add(lang.macro)
        for other in scheme.languages.values():
            if other.iso639_3 == lang.macro and other.members:
                out.update(other.members)
    out.discard(lang.iso639_3 or "")
    # A macrolanguage's own members are not neighbours -- they are valid answers.
    return out - _accepted(scheme, lang)


def check_language(
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
    n_sentences: int = 3,
    cache: QualificationCache | None = None,
) -> CheckResult:
    lang = scheme.get(tag)
    if lang is None:
        raise KeyError(f"Unknown tag {tag!r} in scheme {scheme.meta.name!r}")

    des = dsg.best(lang)
    relatives = _relatives(scheme, lang)
    accept = _accepted(scheme, lang)

    # Qualify the instrument before trusting it, and choose it per language: a
    # back-translator that cannot read the language turns a correct model into a
    # failing score, silently, because it fabricates rather than refusing.
    backtranslator, qual = route(backtranslators, client, judge_model, tag, cache=cache)
    items: list[ItemOutcome] = []
    resolves: dict[str, int] = {}

    for spec in specs:
        prompt = dsg.generation_prompt(des.value, spec.scenario, n_sentences)
        gen = client.complete(engine, prompt, max_tokens=400)
        corpus.write(Record("generation", engine, tag, spec.id, des.value, prompt,
                            gen.text, gen.error, gen.usage, gen.latency_s,
                            {"designator_kind": des.kind}))

        gate = gate_check(gen.text, prompt=prompt, expect_lang=lang.iso639_3,
                          expect_script=lang.script, relatives=relatives,
                          accept_lang=accept)
        if gate.lid and gate.lid.label:
            resolves[gate.lid.label] = resolves.get(gate.lid.label, 0) + 1

        if not gate.passed:
            items.append(ItemOutcome(spec.id, des.value, gen.text, gate, error=gen.error))
            continue

        bt = backtranslator.translate(gen.text or "")
        corpus.write(Record("backtranslation", backtranslator.id, tag, spec.id, des.value,
                            "", bt.text, bt.error))
        if not bt.ok:
            items.append(ItemOutcome(spec.id, des.value, gen.text, gate, error=bt.error))
            continue

        judgement = run_judge(client, judge_model, bt.text or "", spec.facts)
        corpus.write(Record("judgement", judge_model, tag, spec.id, des.value, "",
                            judgement.raw, judgement.error,
                            meta={"verdicts": [v.value for v in judgement.verdicts]}))
        items.append(ItemOutcome(spec.id, des.value, gen.text, gate, bt.text, judgement))

    contents = [i.content for i in items if i.content is not None]
    lang_pass = [i.lang_ok for i in items]
    contradictions = sum(i.judgement.contradictions for i in items
                         if i.judgement and i.judgement.ok)

    notes = []
    if any(i.gate.verdict is GateVerdict.RELATIVE_SUBSTITUTION for i in items):
        notes.append("Model produced a neighbouring language rather than the target.")

    # A deterministic negative stands on its own: it never depended on reading
    # the language, so an unqualified back-translator does not undermine it.
    if not contents and all(i.gate.is_negative for i in items):
        evidence = Evidence.DETERMINISTIC_NEGATIVE
    elif not qual.trustworthy:
        evidence = Evidence.UNVERIFIED
        notes.append(f"Back-translator {qual.backtranslator} is {qual.status.value} "
                     f"for {tag}: {qual.detail}")
    elif not contents:
        evidence = Evidence.UNVERIFIED
    else:
        evidence = Evidence.FACT_RECALL

    return CheckResult(
        tag=tag, engine=engine, language=lang, designator=des.value,
        score=score(lang_pass=lang_pass, content=[c for c in contents],
                    evidence=evidence, contradictions=contradictions, notes=notes),
        items=items, backtranslator=backtranslator.id, judge_model=judge_model,
        pivot=pivot, qualification=qual, resolves_to=resolves,
    )
