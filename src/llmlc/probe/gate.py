"""The deterministic gate.

Runs locally, costs nothing, and resolves most negatives before any paid judge
call. Each check corresponds to a failure mode observed in docs/02 rather than
an imagined one:

  refusal        models answer CANNOT when asked honestly
  copy           output echoes the prompt instead of writing the language
  wrong script   "Acehnese in Arabic script" answered in English
  wrong language GlotLID: Gemini's Acehnese identified as Minangkabau
  relative       the nearest high-resource neighbour substituted for the target
  degeneration   gpt-4o's Chuvash: repetition that LID still scores 1.000
  memorised      UDHR/Bible/anthem boilerplate a model emits for languages it
                 cannot otherwise use
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from llmlc.probe.lid import LidResult, identify


class GateVerdict(str, Enum):
    PASS = "pass"
    REFUSED = "refused"
    COPY = "copy"
    WRONG_SCRIPT = "wrong_script"
    WRONG_LANGUAGE = "wrong_language"
    RELATIVE_SUBSTITUTION = "relative_substitution"
    DEGENERATE = "degenerate"
    MEMORISED = "memorised"
    TOO_SHORT = "too_short"
    LOW_CONFIDENCE = "low_confidence"


#: Verdicts that are a negative about the model, as opposed to a void item.
NEGATIVE = {
    GateVerdict.REFUSED, GateVerdict.COPY, GateVerdict.WRONG_SCRIPT,
    GateVerdict.WRONG_LANGUAGE, GateVerdict.RELATIVE_SUBSTITUTION,
    GateVerdict.DEGENERATE,
}

REFUSAL_RE = re.compile(
    r"^\s*(cannot|none)\b|^\s*(i\s*(am|'m)\s+sorry|i\s+can(not|'t)\b|"
    r"i\s+don'?t\s+(know|speak)|unable to)", re.I)

# Opening fragments of texts models reproduce from memory in languages they
# cannot otherwise write. Matched on a normalised prefix.
MEMORISED_MARKERS = (
    "all human beings are born free",
    "in the beginning god created",
    "our father who art in heaven",
    "article 1",
)

MIN_CHARS = 25

#: Below this, a top-1 LID label is too weak to convict a model on. Correct calls
#: have been observed as low as 0.63, so a weak disagreement voids the item
#: rather than counting as evidence against the model.
LID_CONFIDENT = 0.60
#: The expected language appearing anywhere in the top-k above this counts as a match.
LID_ALTERNATIVE_FLOOR = 0.15


@dataclass
class GateResult:
    verdict: GateVerdict
    lid: LidResult | None = None
    detail: str = ""
    checks: dict[str, bool] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.verdict is GateVerdict.PASS

    @property
    def is_negative(self) -> bool:
        return self.verdict in NEGATIVE


def _repetition_ratio(text: str, n: int = 3) -> float:
    """Share of repeated word n-grams. LID scores degenerate text as fluent, so
    this is measured separately."""
    words = text.split()
    if len(words) < n * 2:
        return 0.0
    grams = [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]
    return 1.0 - (len(set(grams)) / len(grams))


def _normalise(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def check(text: str | None, *, prompt: str, expect_lang: str | None,
          expect_script: str | None, relatives: set[str] | None = None,
          accept_lang: set[str] | None = None,
          lid_result: LidResult | None = None) -> GateResult:
    """Screen one generation.

    `expect_lang` is an ISO 639-3 code. `accept_lang` holds other codes that also
    satisfy the request -- chiefly the members of a macrolanguage: asking for
    Swahili (`swa`) and receiving Coastal Swahili (`swh`) is the macrolanguage
    resolving to a member, which is the answer, not a substitution.
    `relatives` are neighbours whose appearance means substitution rather than a
    generic miss.
    """
    checks: dict[str, bool] = {}

    if not text or not text.strip():
        return GateResult(GateVerdict.REFUSED, detail="empty response", checks=checks)

    stripped = text.strip()
    if REFUSAL_RE.search(stripped):
        checks["refusal"] = True
        return GateResult(GateVerdict.REFUSED, detail=stripped[:120], checks=checks)

    norm = _normalise(stripped)
    if norm and _normalise(prompt).find(norm) >= 0:
        checks["copy"] = True
        return GateResult(GateVerdict.COPY, detail="output echoes the prompt", checks=checks)

    for marker in MEMORISED_MARKERS:
        if norm.startswith(marker):
            checks["memorised"] = True
            return GateResult(GateVerdict.MEMORISED, detail=marker, checks=checks)

    if len(stripped) < MIN_CHARS:
        return GateResult(GateVerdict.TOO_SHORT, detail=f"{len(stripped)} chars", checks=checks)

    rep = _repetition_ratio(stripped)
    checks["repetition_ratio"] = rep  # type: ignore[assignment]
    if rep > 0.4:
        return GateResult(GateVerdict.DEGENERATE, detail=f"repetition ratio {rep:.2f}", checks=checks)

    lid = lid_result or identify(stripped)

    if expect_script and lid.script and lid.script != expect_script:
        checks["script"] = False
        return GateResult(GateVerdict.WRONG_SCRIPT, lid=lid,
                          detail=f"expected {expect_script}, got {lid.script}", checks=checks)
    checks["script"] = True

    accepted = {expect_lang, *(accept_lang or set())} - {None}
    if expect_lang and lid.lang and lid.lang not in accepted:
        got = lid.lang

        # The target may still be present further down the ranking; a top-1 miss
        # with the target close behind is not evidence of the wrong language.
        alt = {label.partition("_")[0]: p for label, p in lid.alternatives}
        hit = next((c for c in accepted if alt.get(c, 0.0) >= LID_ALTERNATIVE_FLOOR), None)
        if hit:
            checks["language"] = True
            return GateResult(GateVerdict.PASS, lid=lid,
                              detail=f"{expect_lang} ranked below {got} but above threshold",
                              checks=checks)

        if lid.confidence < LID_CONFIDENT:
            return GateResult(GateVerdict.LOW_CONFIDENCE, lid=lid,
                              detail=f"LID unsure: {got} at {lid.confidence:.2f}; "
                                     "too weak to count against the model",
                              checks=checks)

        if relatives and got in relatives:
            return GateResult(GateVerdict.RELATIVE_SUBSTITUTION, lid=lid,
                              detail=f"expected {expect_lang}, produced neighbour {got}",
                              checks=checks)
        return GateResult(GateVerdict.WRONG_LANGUAGE, lid=lid,
                          detail=f"expected {expect_lang}, got {got}", checks=checks)

    checks["language"] = True
    return GateResult(GateVerdict.PASS, lid=lid, checks=checks)
