"""The two primitive steps, extracted so the ladder can call them per rung.

`generate_and_gate` costs one model call and no judge call -- it is what makes
most negatives free, and what the designator sweep is scored on.
`judge_item` is the paid half, run only on what survives.
"""
from __future__ import annotations

from dataclasses import dataclass

from llmlc.bt import RemoteBackTranslator
from llmlc.client import OpenAICompatClient
from llmlc.probe import designator as dsg
from llmlc.probe.corpus import Corpus, Record
from llmlc.probe.gate import GateResult, check as gate_check
from llmlc.probe.judge import Judgement
from llmlc.probe.judge import judge as run_judge
from llmlc.probe.specs import Spec
from llmlc.scheme import Language


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
    def counts_against(self) -> bool:
        """Void items -- memorised text, too short, weak LID -- are neither a pass
        nor evidence against the model, so they are excluded from s_lang."""
        return self.gate.is_negative

    @property
    def content(self) -> float | None:
        return self.judgement.recall if self.judgement and self.judgement.ok else None


def generate_and_gate(*, client: OpenAICompatClient, engine: str, lang: Language,
                      designator: str, spec: Spec, corpus: Corpus,
                      relatives: set[str], accept: set[str],
                      n_sentences: int = 3) -> ItemOutcome:
    prompt = dsg.generation_prompt(designator, spec.scenario, n_sentences)
    gen = client.complete(engine, prompt, max_tokens=400)
    corpus.write(Record("generation", engine, lang.tag, spec.id, designator, prompt,
                        gen.text, gen.error, gen.usage, gen.latency_s))
    gate = gate_check(gen.text, prompt=prompt, expect_lang=lang.iso639_3,
                      expect_script=lang.script, relatives=relatives, accept_lang=accept)
    return ItemOutcome(spec.id, designator, gen.text, gate, error=gen.error)


def judge_item(item: ItemOutcome, *, client: OpenAICompatClient, judge_model: str,
               backtranslator: RemoteBackTranslator, spec: Spec, tag: str,
               corpus: Corpus) -> ItemOutcome:
    """Back-translate and grade. Only ever called on items that passed the gate."""
    bt = backtranslator.translate(item.generation or "")
    corpus.write(Record("backtranslation", backtranslator.id, tag, spec.id,
                        item.designator, "", bt.text, bt.error))
    if not bt.ok:
        item.error = bt.error
        return item

    judgement = run_judge(client, judge_model, bt.text or "", spec.facts)
    corpus.write(Record("judgement", judge_model, tag, spec.id, item.designator, "",
                        judgement.raw, judgement.error,
                        meta={"verdicts": [v.value for v in judgement.verdicts]}))
    item.back_translation = bt.text
    item.judgement = judgement
    return item
