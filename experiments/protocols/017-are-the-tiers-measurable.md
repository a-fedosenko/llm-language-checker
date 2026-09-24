# 017 — Is the five-tier scale measurable, or does it collapse?

| | |
|---|---|
| **Date** | 2026-09-24 |
| **Status** | valid — three of the four hypotheses were wrong |
| **Triggered by** | Across all 40 results ever produced: 34 `Strong`, 4 `None`, 1 `Basic`, 1 `Token`, and **zero `Usable`**. The tier is the tool's headline output, and it appears to have two outcomes rather than five |
| **Artifacts** | re-analysis only — `data/results/evidence.*.jsonl` and `data/calibration/study.json`. No model calls |

## Why this is not obvious from the tier definitions

A tier comes from two numbers, and protocols 014 and 016 showed both are near-binary in practice:

- **`s_lang`** is a gate pass rate over the items run. At the ladder's 3 items it can only take the values 0, ⅓, ⅔ and 1 — so the thresholds `0.95 / 0.90 / 0.80` that separate Strong from Usable from Basic **cannot be told apart at all**. Only 1.0 clears any of them.
- **`s_content`** saturates: protocol 016 established it is an adequacy floor, near-binary by nature and correctly so.

Two near-binary inputs cannot produce five ordered outcomes. The question is what they *can* produce.

## Hypothesis

1. **The collapse reproduces on independent data.** Applying the current thresholds to the 98 calibration languages will put **over 70% in a single tier**, and `Usable` will be rare or absent.
2. **`s_lang` is the real discriminator.** Across languages, the gate pass rate will correlate with mean chrF++ more strongly than mean fact recall does — because gate failures are the genuine failures, and recall is a floor.
3. **The extra tiers add nothing.** A two- or three-outcome scale built on gate pass rate alone will separate chrF++ about as well as the full five-tier assignment. If true, the tiers above the floor are decoration.
4. **Resolution needs ~20 items.** To distinguish `s_lang` 0.95 from 0.90 arithmetically requires granularity finer than 0.05, so n ≥ 20 items per language — six to seven times the current cost, which is likely the wrong trade for a tool whose value is breadth.

**What would overturn this:** a clear spread of simulated tiers with `Usable` populated, or fact recall out-predicting the gate. Either would mean the scale is fine and the sample of 40 results was simply unlucky.

## Method

Re-analysis only, no model calls. The 100 calibration languages have four items each with a gate verdict, a fact-recall score and a chrF++ score, so `s_lang` and `s_content` can be recomputed and the current thresholds applied to get a simulated tier. Each candidate scale is then scored by how well it orders languages against mean chrF++.

**The yardstick is itself compromised, and this must be read with that in mind.** Protocol 016 established that chrF++ is the wrong arbiter for individual mid-range items, because it charges a correct translation for paraphrase. Across *languages*, averaged over items, it remains the only independent signal available — but a design tuned to it is tuned to an imperfect target, and that caveat attaches to everything below.

## Results

### H1 — collapse: partly confirmed

| simulated tier | n | mean chrF++ |
|---|---|---|
| Strong | 47 | **52.0** |
| None | 34 | 34.5 |
| Token | 16 | 32.0 |
| Usable | **3** | **20.9** |
| Basic | 0 | — |

The largest tier holds 47%, not the 70% predicted — this sample of 100 low-resource FLORES languages is far harsher than the languages real scans have touched, where the figure is 85% `Strong`. But `Usable` is 3 languages and `Basic` is empty.

**The ordering is not monotonic.** `Usable` averages chrF++ 20.9 — *below* `None` at 34.5 and `Token` at 32.0. A tier that ranks beneath the tiers it is supposed to outrank is not measuring anything. `None` and `Token` are 34.5 against 32.0, which is to say indistinguishable.

What the scale really separates is `Strong` (52.0) from everything else (~33). Two outcomes.

### H2 — wrong, and decisively

I predicted the gate would be the better predictor of quality. It is not, by a wide margin:

| signal | Spearman vs mean chrF++ |
|---|---|
| `s_content` (fact recall) | **0.664** |
| `s_lang` (gate pass rate) | 0.370 |

Fact recall orders languages by quality nearly twice as well as the gate does. Taken with protocol 016 — where recall was right about 90% of the disputed items — the picture is consistent: **recall is a good measurement that we have been treating as the weak half of the score.**

### H3 — wrong, and in the most useful way

The tier assignment orders languages *worse than one of its own inputs*:

| scale | Spearman vs mean chrF++ |
|---|---|
| `s_content` alone, continuous | **0.664** |
| 2 outcomes (eligible + adequate) | 0.459 |
| current 5 tiers | 0.436 |
| 3 outcomes | 0.398 |
| `s_lang` alone | 0.370 |

**Every discretisation loses to the continuous score.** `tier_for()` hard-gates on `s_lang` and then bins `s_content` into coarse buckets, and both steps throw away signal — the function destroys about a third of the ordering information present in its own inputs.

Note also that fewer tiers did not help: 3 outcomes (0.398) scored *worse* than 5, because the middle bucket collects a specific failure mode — fluent text with wrong content — whose mean chrF++ is 18.4, lower than either neighbour. The problem is not the number of buckets. It is bucketing at all, on top of a hard gate.

### H4 — arithmetic, confirmed

`s_lang` over *n* items takes values in steps of 1/*n*. Separating 0.95 from 0.90 needs steps below 0.05, so **n ≥ 20 items per language** — six to seven times the current cost. At the ladder's 3 items the three thresholds 0.95 / 0.90 / 0.80 are one threshold wearing three hats.

## Conclusions

1. **The five-tier scale is not measurable as defined.** `Basic` never occurs, `Usable` is vanishingly rare and mis-ordered, and `None` and `Token` do not separate. It reports two outcomes.
2. **The gate should filter, not grade.** Protocol 016 proved the gate is irreplaceable for catching wrong script and wrong language — an LLM missed 15 of 15. But it is a poor *quality* signal (0.370), and using it as a hard pre-gate before grading is what breaks the ordering.
3. **Fact recall deserves promotion, not repair.** It is the best quality signal available (0.664), it was right in 016's adjudication, and protocol 015 showed it is insensitive to how the checklist is cut. Three protocols now point the same way.
4. **The tier should be derived from the continuous score, not replace it.** Whatever scale ships, `s_content` belongs in the output as a number. A TMS needs a routing decision, so some discretisation is unavoidable — but discretising is a lossy presentation step, and the current one loses a third of the signal before anyone sees it.

**Limits:** simulated on a translation task, while production scans measure free generation; 4 items per language; scored against chrF++, which protocol 016 showed is an imperfect target. The non-monotonicity and the emptiness of `Basic` are robust; the exact correlation figures are not.

## Impact

Blocks S8 until the scale is decided — documenting five tiers would document something that does not exist. The options, with this data attached:

- **Report the number, derive a small tier from it.** Publish `s_content` continuously, and keep tiers only as a TMS routing convenience, derived monotonically so they never invert.
- **Keep the gate as an eligibility filter**, not as the first term of the grade: wrong script or wrong language means unusable, full stop; everything that clears it is graded by adequacy.
- **Do not buy resolution with items.** n ≥ 20 for `s_lang` to earn its thresholds is the wrong trade for a tool whose value is breadth.
