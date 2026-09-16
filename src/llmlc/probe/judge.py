"""The judge: blind fact recall, entirely in the pivot language.

The point of grading by fact recall rather than string similarity is that the
judge never needs to know the target language -- it reads a back-translation and
checks a list. That removes the "we need expert LLMs covering 600 languages"
bootstrap problem entirely (docs/01).

Rules, all load-bearing:
  blind          the judge never sees the target-language text, the designator,
                 or which model produced it
  three-valued   missing is incompleteness; contradicted is hallucination
  not self       never the model under test (self-preference bias)
  pinned         the judge model is recorded on every result
  controlled     injected positive/negative controls detect a broken judge in-run
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum

from llmlc.client import OpenAICompatClient


class FactVerdict(str, Enum):
    PRESENT = "present"
    MISSING = "missing"
    CONTRADICTED = "contradicted"


JUDGE_PROMPT = """You are checking whether a piece of text contains specific facts.

TEXT:
{text}

FACTS:
{facts}

For each fact, answer exactly one of:
  "present"       the text states this fact
  "missing"       the text does not mention it
  "contradicted"  the text states something incompatible with it

Wording will differ from the fact — judge meaning, not phrasing.
Reply with JSON only: {{"verdicts": ["present", "missing", ...]}} with one entry \
per fact, in order. No other text."""


@dataclass
class Judgement:
    verdicts: list[FactVerdict]
    raw: str | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.verdicts)

    @property
    def recall(self) -> float:
        """Share of facts present. Contradiction counts as absent and is tracked
        separately, since hallucination is worse than omission."""
        if not self.verdicts:
            return 0.0
        return sum(v is FactVerdict.PRESENT for v in self.verdicts) / len(self.verdicts)

    @property
    def contradictions(self) -> int:
        return sum(v is FactVerdict.CONTRADICTED for v in self.verdicts)


def _parse(raw: str, n: int) -> list[FactVerdict]:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out = []
    for v in (data.get("verdicts") or [])[:n]:
        try:
            out.append(FactVerdict(str(v).strip().lower()))
        except ValueError:
            out.append(FactVerdict.MISSING)
    return out


def judge(client: OpenAICompatClient, model: str, pivot_text: str,
          facts: list[str]) -> Judgement:
    """Grade one back-translation against its fact checklist."""
    numbered = "\n".join(f"{i}. {f}" for i, f in enumerate(facts, 1))
    prompt = JUDGE_PROMPT.format(text=pivot_text.strip(), facts=numbered)
    completion = client.complete(model, prompt, max_tokens=300)
    if not completion.ok:
        return Judgement([], None, completion.error)
    verdicts = _parse(completion.text or "", len(facts))
    if len(verdicts) != len(facts):
        return Judgement(verdicts, completion.text,
                         f"expected {len(facts)} verdicts, parsed {len(verdicts)}")
    return Judgement(verdicts, completion.text)
