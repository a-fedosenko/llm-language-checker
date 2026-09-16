"""chrF++ — character n-gram F-score with word n-grams.

Implemented directly rather than pulling in sacrebleu: it is forty lines, it
keeps the dependency tree light enough to install anywhere, and this project
needs exactly one metric from it.

Two uses:
  qualification   back-translate a known reference sentence and compare to the
                  known pivot text. Deterministic, needs no judge call.
  gold-reference  score a model's output directly against a human translation,
                  where FLORES+ has one.

Follows Popović (2017): chrF++ = chrF with word n-grams added, beta=2 so recall
weighs twice precision.
"""
from __future__ import annotations

from collections import Counter

CHAR_ORDER = 6
WORD_ORDER = 2
BETA = 2.0


def _ngrams(tokens: list[str] | str, n: int) -> Counter:
    return Counter(tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1))


def _f_score(hyp: Counter, ref: Counter, beta: float) -> float | None:
    """F-score for one n-gram order. None when the order does not apply."""
    if not hyp or not ref:
        return None
    overlap = sum((hyp & ref).values())
    if overlap == 0:
        return 0.0
    precision = overlap / sum(hyp.values())
    recall = overlap / sum(ref.values())
    b2 = beta ** 2
    return (1 + b2) * precision * recall / (b2 * precision + recall)


def chrf(hypothesis: str, reference: str, *, char_order: int = CHAR_ORDER,
         word_order: int = WORD_ORDER, beta: float = BETA) -> float:
    """chrF++ in [0, 100]. Whitespace is removed for character n-grams."""
    hyp_chars = "".join(hypothesis.split())
    ref_chars = "".join(reference.split())
    if not hyp_chars or not ref_chars:
        return 0.0

    scores: list[float] = []
    for n in range(1, char_order + 1):
        s = _f_score(_ngrams(hyp_chars, n), _ngrams(ref_chars, n), beta)
        if s is not None:
            scores.append(s)
    hyp_words, ref_words = hypothesis.split(), reference.split()
    for n in range(1, word_order + 1):
        s = _f_score(_ngrams(hyp_words, n), _ngrams(ref_words, n), beta)
        if s is not None:
            scores.append(s)

    return 100.0 * sum(scores) / len(scores) if scores else 0.0
