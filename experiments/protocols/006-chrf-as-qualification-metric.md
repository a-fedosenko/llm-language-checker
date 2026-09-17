# 006 — chrF++ as the qualification metric

| | |
|---|---|
| **Date** | 2026-09-16 |
| **Status** | valid |
| **Triggered by** | Qualification via [005](005-backtranslator-fabrication.md) cost a judge call per control item. With 200 languages × several back-translators that is a lot of calls for a check that should be cheap |
| **Artifacts** | `src/llmlc/probe/chrf.py`, `tests/test_chrf.py` |

## Hypothesis

That a string-similarity metric could replace the judge for qualification: since a control has a *known pivot sentence*, comparing the back-translation to it directly is a translation-quality question, which chrF++ already answers — deterministically and for free.

The risk was that the fabricated and faithful cases would not separate widely enough to set a stable threshold.

## What was tested

Whether chrF++ separates a fabricating back-translator from a faithful one by a margin large enough to threshold, using the real outputs from 005.

## Setup

| | |
|---|---|
| Metric | chrF++ implemented directly — character n-grams to order 6, word n-grams to order 2, β=2 (Popović 2017) |
| Dependency | none; `sacrebleu` deliberately not added — 40 lines against a dependency for one metric |

## Results

| Case | chrF++ |
|---|---|
| identical text | 100.00 |
| paraphrase | 55.90 |
| **`deepseek` on the real control** | **81.94** |
| fabrication (unrelated sentence) | 12.73 |
| **`gpt-4o` on the real control** | **10.49** |
| reordered words | 48.61 |
| unrelated words | 8.98 |

## Conclusions

- The separation is wide and unambiguous: **10.5 versus 81.9 on identical input**. Threshold set at **30**, comfortably between them and above the reordering case.
- chrF++ is order-sensitive via word bigrams — a reordered sentence scores ~49, well below identical but far above unrelated. That is correct behaviour, and the test asserts the property rather than a fragile number.
- Qualification via reference costs **no judge call at all**.

Limit: the threshold rests on a handful of observed cases, not a calibration study. It should be revisited in S7 when fact-recall is calibrated against chrF++ across ~200 languages.

## Impact

- Qualification split into two kinds: `reference` (chrF++, no judge call, 200 languages) and `facts` (judge-graded, for languages FLORES lacks).
- The same implementation serves the planned `gold-reference` evidence class, where a model's output is scored directly against a human translation — so S7's calibration study needs no new metric code.
