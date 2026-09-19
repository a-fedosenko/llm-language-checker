# 011 — Should low reliability cap the tier?

| | |
|---|---|
| **Date** | 2026-09-17 |
| **Status** | valid |
| **Triggered by** | `ug` reporting "Strong — light review" at reliability 0.33: true about the text that came back, silent about the two requests out of three that did not. Carried into S5 as an open question |
| **Artifacts** | re-analysis of `data/results/evidence.*.jsonl` (no new model calls); `src/llmlc/probe/score.py`; tests in `tests/test_scoring.py` |

## Hypothesis

**Low reliability predicts low quality**, so capping the tier at some reliability threshold would remove a misleading label without discarding real information. If that holds, a model that refuses most requests for a language is also worse at it when it does answer, and the cap merely anticipates what a larger sample would have shown anyway.

The competing hypothesis, stated before looking: refusal is a policy behaviour and quality is a capability, the two are independent, and a cap would restate *unwillingness* as *inability* — which is a different claim, and a false one.

## What was tested

Whether, in the results already collected, reliability co-varies with `s_content` strongly enough to justify deriving one from the other.

This is a **re-analysis of existing data, not a new run.** No model was called. It is recorded as a protocol because it settles a scoring rule, and because the answer turns on a sample size that has to be stated.

## Setup

| | |
|---|---|
| Models | `openai-gpt-4o`, `gemini-gemini-3-8-flash` (the rows already on disk) |
| Parameters | as measured — temperature 0, `reasoning_effort: none`, 3 items per rung |
| Data | `data/results/evidence.*.jsonl`, latest row per `(engine, tag, method_version)` |
| Sample | 32 results, of which **5 contain any refusal at all** |

## Method

Group the results by whether the model refused at least one item, and compare `s_content` between the groups. Refusals are already excluded from `s_lang` (S3), so any relationship would have to show up in content quality.

## Results

Every row with a refusal, across all evidence classes:

| tag | language | reliability | refusals | s_lang | s_content | tier |
|---|---|---|---|---|---|---|
| `cv` | Chuvash | 0.67 | 1 of 3 | 1.00 | 0.00 | Token |
| `ug` | Uyghur | 0.33 | 2 of 3 | 1.00 | 0.80 | Strong |
| `bo` | Tibetan | 0.67 | 1 of 3 | 1.00 | 0.80 | Strong |
| `dv` | Dhivehi | 0.67 | 1 of 3 | 0.50 | — | None (`unverified`) |
| `ee` | Éwé | 0.00 | 3 of 3 | 0.00 | — | None (`deterministic-negative`) |

Restricted to rows with real content scores (`fact-recall`): mean `s_content` was **0.53 among the three that refused something** against **0.96 among the 27 that refused nothing**.

That gap looks like support for the hypothesis. It is not. The three refusing rows are `0.00`, `0.80` and `0.80` — two of the three are at the same level as the non-refusers, and the mean is dragged down entirely by `cv`, whose zero has a separate and already-documented cause. **n = 3, split across two tiers and both extremes of the content range.**

The most direct counter-example is `ug`: the lowest reliability in the set (0.33) paired with `s_content` 0.80 and a clean `s_lang` of 1.00. The one item gpt-4o was willing to attempt, it answered well.

## Conclusions

1. **The hypothesis is not supported, and the data cannot support it either way.** Five rows with refusals, three of them scoreable, is far too small to establish or refute a correlation. Any cap threshold chosen from this sample would be fitted to three points.
2. **The competing reading survives, and it is the one with an argument behind it.** `s_lang` already excludes refusals, deliberately, for the reason recorded in S3: a model that writes perfect Uyghur twice and refuses once is capable and unwilling, and scoring that as "recognises it, cannot use it" states something false. A tier cap would reintroduce exactly the conflation that decision removed — one layer further out, where it is harder to see.
3. **The original complaint was still correct.** "Strong — light review" *was* misleading. What was wrong with it was not the tier but the **workflow sentence**, which is the part a planner acts on and which said nothing about availability.

Limits: one snapshot, two models, one refusal-prone corner of the catalogue (Uyghur, Tibetan, Chuvash, Dhivehi, Éwé). The question should be revisited at S7, where a ~200-language run will produce enough refusals to test the correlation properly. If it turns out that refusal *does* predict quality, this decision is reversible: availability is derived, not stored, so changing the rule re-renders every existing row.

## Impact

**Availability became a second axis rather than a modifier of the first.** In `probe/score.py`:

- `Availability` — `reliable` (≥ 0.90), `intermittent` (≥ 0.60), `unreliable` (> 0), `refused` (0 with attempts), derived from `reliability` and never stored.
- `Score.workflow` now carries the caveat: `ug` reads **"light review — needs a fallback engine (2 refusal(s) of 3)"**. The tier is untouched and still says `Strong`.
- `Tier.NONE` takes no caveat: "do not offer — expect retries" would be noise.

The bands are thresholds on one column, so the API filters on them in SQL (`/results?availability=unreliable`) and the totals, the facet counts and the page all count the same rows. The UI shows availability as its own column, and the page states the distinction in the standing caveat: **tier is capability, availability is willingness.**

Rows written before this change are unaffected on disk and re-render with the new sentence, because the workflow string is recomputed from the stored parts rather than read back — the prose was stored once, and every row written before today would otherwise still be saying the old thing.
