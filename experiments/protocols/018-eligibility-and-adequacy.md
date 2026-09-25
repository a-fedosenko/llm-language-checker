# 018 — Does an eligibility-plus-adequacy scale survive the data that broke the five tiers?

| | |
|---|---|
| **Date** | 2026-09-25 |
| **Status** | *(pending — hypotheses recorded before the run)* |
| **Triggered by** | [Protocol 017](017-are-the-tiers-measurable.md) showed the five-tier scale is not measurable: `Basic` never occurs, `Usable` ranks *below* `None`, and `tier_for()` orders languages worse (ρ 0.436) than one of its own inputs (ρ 0.664). 017 named the replacement but did not test it |
| **Artifacts** | `scripts/rescale.py`, re-analysis of `data/calibration/study.json`. No model calls |

## What is being proposed

Three protocols now point the same way, and the redesign follows from them directly:

| component | current role | proposed role | evidence |
|---|---|---|---|
| deterministic gate (`s_lang`) | first term of the grade, hard pre-gate with three thresholds | **eligibility filter**, one threshold: wrong script or wrong language means unusable, full stop | [016](016-which-metric-is-wrong.md): an LLM missed 15/15 script mismatches the gate caught. [017](017-are-the-tiers-measurable.md): the gate is a poor quality signal (ρ 0.370) |
| fact recall (`s_content`) | second term, binned into four coarse buckets | **the graded measurement**, published as a continuous number | [017](017-are-the-tiers-measurable.md): ρ 0.664, the best signal available. [016](016-which-metric-is-wrong.md): right about 90% of disputed items |
| tier | the headline output, five values | a lossy routing convenience **derived** from the number — monotonic, and fewer than five | [017](017-are-the-tiers-measurable.md): every discretisation tested lost signal |

Two details of the current code are in scope because the redesign exposes them:

- **`s_lang`'s three thresholds (0.95 / 0.90 / 0.80) cannot be distinguished below n = 20 items** (017, H4). At the ladder's 3 items they are one threshold wearing three hats. They collapse to one. Buying the resolution with more items is the wrong trade for a tool whose value is breadth, so the number of items does not change.
- **The gate has verdicts that are not accusations.** `low_confidence` and `too_short` void an item — `probe/gate.py` says so in as many words: *"too weak to count against the model"*. But `ItemOutcome.lang_ok` is `gate.passed`, so a voided item currently counts against `s_lang` exactly like a wrong-language one. If eligibility is to mean "the model produced the requested language", voids belong outside the denominator, not inside it as failures.

## Hypothesis

Recorded before the re-analysis was written.

1. **Monotonic within the eligible set.** Tiers formed by binning `s_content` among languages that clear the eligibility filter will be **strictly monotonic in mean chrF++** — each band above the one below it, with no inversion. This is the property the current scale lacks (`Usable` 20.9 below `None` 34.5) and the minimum bar for shipping anything.

2. **Eligibility will *not* be monotonic against chrF++, and that is expected rather than a failure.** Ineligible languages will average a mean chrF++ **at or above** the lowest eligible band, because chrF++ rewards a wrong-but-related language: protocol 014's `ace` scored chrF++ 37 for answering in Indonesian. Predicted: mean chrF++ of the ineligible set ≥ 25, overlapping the bottom eligible band rather than sitting below it.
   **This hypothesis is the one that decides how the result may be argued.** If it holds, chrF++ cannot adjudicate the eligibility filter at all, and the filter stands on 016's 15/15 script finding — a correctness requirement, not a quality dimension. If instead the ineligible set sits clearly below every eligible band, the gate *is* a quality signal, 017's H2 was mis-read, and the whole redesign needs revisiting.

3. **Two graded bands above the floor are all the data supports.** Splitting the eligible languages' `s_content` three ways will produce either an inversion or a band holding fewer than 5 of the ~98 languages; splitting two ways will do neither. Fact recall is an adequacy floor (016), and a floor has one edge.

4. **The derived tier loses ordering to the continuous score, and that loss is the price of routing.** ρ(derived tier vs mean chrF++) will land **below 0.664** (the continuous `s_content`) and **above 0.436** (the current five tiers). Predicted range 0.45–0.60. Anything at or above 0.664 would mean discretising added information, which is not possible, and would indicate a bug in the analysis.

5. **Excluding void verdicts from the eligibility denominator changes few languages but changes them correctly.** Fewer than 15 of 98 languages will move across the eligibility line, and the ones that move will be languages where LID was unsure rather than languages that produced the wrong text.

6. **The single eligibility threshold is insensitive across the range the ladder can express.** At 3–4 items per language, `s_lang` takes four or five distinct values, so thresholds of 0.5, 0.75 and 0.95 partition into at most three distinct eligible sets. Predicted: moving the threshold between 0.5 and 0.95 moves fewer than 20 of 98 languages.

**What would sink the proposal rather than adjust it:** a failure of H1 — no binning of `s_content` among eligible languages that is monotonic in chrF++. That would mean the continuous score cannot be discretised at all, and the tool would have to report a number and refuse to route on it.

## What is being tested

Whether the scale named in 017's *Impact* section, built and applied to the same 100-language calibration set, produces an ordering that is monotonic, better than the scale it replaces, and honest about what it gives up. Not whether it is better than chrF++ — 016 settled that chrF++ is the wrong arbiter for individual items, and it is used here only as the one independent per-language signal available.

## Setup

| | |
|---|---|
| Models | none. Re-analysis of an existing run |
| Data | `data/calibration/study.json` — 100 languages, 4 FLORES items each, 378 paired items, 98 languages scored (protocol 014's run: `openai-gpt-4o`, judge `openai-gpt-4o-mini`, panel `gemini-gemini-3-8-flash` / `deepseek-deepseek-v4-pro`, pivot `en`) |
| Yardstick | mean chrF++ per language, with 016's caveat attached: it is an imperfect target, and a design tuned to it is tuned to an imperfect target |
| Sample | the same 98 scored languages 017 used, so the two analyses are directly comparable |

## Method

*(to be completed)*

## Results

*(to be completed)*

## Conclusions

*(to be completed)*

## Impact

*(to be completed)*
