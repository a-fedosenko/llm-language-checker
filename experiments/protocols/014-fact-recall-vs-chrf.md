# 014 — Calibration: does fact recall track chrF++?

| | |
|---|---|
| **Date** | 2026-09-23 |
| **Status** | in progress — hypothesis recorded before the run |
| **Triggered by** | S7. The whole method rests on fact recall being a usable proxy for translation quality, and that has been asserted since doc 01 and never measured |
| **Artifacts** | `src/llmlc/probe/calibrate.py`, `scripts/build_calibration_specs.py`, raw responses in `data/calibration/` and the `generation` table |

## Hypothesis

Recorded before the pilot was run.

1. **The two metrics correlate positively and strongly at the item level.** Spearman **ρ > 0.6** across items within the pilot languages. Anything below ~0.4 would mean the proxy is not measuring translation quality and the tier thresholds in `probe/score.py` rest on nothing.
2. **They correlate more strongly at the language level than at the item level.** Per-item fact recall is a handful of binary verdicts and therefore coarse — a five-fact checklist can only take six values — while chrF++ is continuous. Averaging over items should cancel much of that. This matters because **the language is the unit the tool actually reports**: tiers are per language, not per item.
3. **The proxy fails at the bottom, not the top.** Predicted shape: tight agreement where chrF++ is high, and a widening spread below roughly chrF++ 40, where a model produces text fluent enough to carry some facts but too poor to match a reference. If true, the honest consequence is that the Basic and Token tier boundaries are less trustworthy than the Strong and Usable ones.
4. **Fact recall will be the more forgiving metric.** A translation that renders every fact in different words scores well on recall and badly on chrF++. So where they disagree, recall should be *higher* — a systematic offset rather than noise. The reverse (chrF++ high, recall low) would be more worrying, because it would mean the judge is missing facts that are demonstrably present.

**What would invalidate the method, not just the study:** ρ below 0.4 at the language level, or a *negative* relationship in any band.

## What is being tested

For each language, the model under test translates FLORES source sentences into that language. The same output is then scored twice:

- **chrF++** against the FLORES human reference — the reference metric.
- **fact recall** — back-translate the output into the pivot, judge it against a fact checklist extracted from the English source sentence. This is our proxy, and exactly the machinery a normal scan uses.

Paired per item, and averaged per language.

## Known limitation, stated up front

**This calibrates on a translation task, while the tool otherwise measures free generation.** chrF++ requires a reference translation of the specific text being scored, and a free composition has none — there is no way to compute the reference metric on the task we actually run. So the transfer is an assumption: that the relationship between the two metrics observed on translations also holds on free generation.

That assumption is worth stating in any publication of this result, and it is the single biggest threat to the study's external validity. The language-level arm mitigates it slightly: per-language fact recall from *ordinary scans* can be compared against per-language chrF++ from this arm, which at least puts the proxy back on its native task on one side of the comparison.

## Setup

| | |
|---|---|
| Models | *(to be completed)* |
| Parameters | temperature 0, `reasoning_effort: none` |
| Data | FLORES-200 (CC BY-SA 4.0), fact checklists extracted from the English source sentences and not committed, being derived text |
| Sample | pilot: ~20 languages × N items, chosen to reuse [protocol 008](008-twenty-language-spread.md)'s spread so the results are comparable with an existing run |

## Pilot design note, from a 4-item smoke run

Before the pilot, the path was exercised on `af` and `ru`, two items each, purely to prove it runs. It immediately showed something that shapes how the pilot must be sampled:

| tag | item | chrF++ | recall |
|---|---|---|---|
| `af` | af-0 | 73.2 | 1.00 |
| `af` | af-1 | 64.5 | 1.00 |
| `ru` | ru-0 | 62.8 | 1.00 |
| `ru` | ru-1 | 45.6 | 1.00 |

**chrF++ spans 45.6 to 73.2 while fact recall is pinned at 1.00 on every item.** The item-level Spearman is therefore not merely weak but *undefined* — one metric is constant, so there is no ordering to compare, and `spearman()` correctly returns `None` rather than a number.

This is hypothesis 3 arriving early, and it is not a defect in either metric. Fact recall over a four-fact checklist can take five values; a competent translation recovers all four facts whether it scores 45 or 73 on chrF++. The proxy distinguishes *adequate from inadequate*, not *good from better* — which may be all the tool needs, since it reports five tiers rather than a continuous score, but it has two consequences for the pilot:

1. **The sample must be weighted toward languages the model handles badly.** A pilot drawn only from well-supported languages produces a constant and answers nothing. Protocol 008's 20-language spread is the right basis precisely because it spans the tier range.
2. **The item-level correlation may remain uncomputable even so**, in which case the language-level arm carries the study. That is the arm that matches what the tool claims anyway, so this is a reordering of emphasis rather than a loss — but it should be predicted now rather than discovered as a disappointment.

## Method

*(to be completed)*

## Results

*(to be completed)*

## Conclusions

*(to be completed)*

## Impact

*(to be completed)*
