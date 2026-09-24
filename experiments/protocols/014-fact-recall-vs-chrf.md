# 014 — Calibration: does fact recall track chrF++?

| | |
|---|---|
| **Date** | 2026-09-23 |
| **Status** | valid, with **conclusion 2 revised** by [016](016-which-metric-is-wrong.md) — see the correction below |
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

## Setup as run

| | |
|---|---|
| Model under test | `openai-gpt-4o` |
| Back-translator | panel `gemini-gemini-3-8-flash, deepseek-deepseek-v4-pro`, qualified per language |
| Judge | `openai-gpt-4o-mini` · pivot `en` |
| Sample | **100 languages** — every other tag of the 200 with FLORES references, alphabetically. A stride rather than a hand-picked list, so the sample is reproducible and not selected on anything correlated with how well a model handles it |
| Items | 4 FLORES sentences per language; 389 built, **378 paired**, 98 languages scored |

Two languages (`kr-Arab`, `taq-Tfng`) had no qualified back-translator and contributed chrF++ only, exactly as designed — a fabricated reading would have corrupted the recall side of the correlation (protocol 005).

## Method

The model translates a FLORES source sentence into the target language. That single output is then scored twice: **chrF++** against the FLORES human reference, and **fact recall** by back-translating it into the pivot and judging against a checklist extracted from the English source. Paired per item, averaged per language, correlated by Spearman at both levels.

## Results

| | |
|---|---|
| paired items | 378 across 98 languages |
| **item-level Spearman** | **0.484** |
| **language-level Spearman** | **0.647** |
| mean offset (recall − chrF++/100) | **+0.482** |

Offsets by quality band, and the correlation *within* each band:

| band | n | mean offset | ρ within band | items scoring recall 1.0 |
|---|---|---|---|---|
| chrF++ ≥ 60 | 79 | +0.282 | **undefined** | **79 / 79** |
| chrF++ 40–60 | 135 | +0.500 | 0.176 | 129 / 135 |
| chrF++ < 40 | 164 | +0.564 | 0.414 | 109 / 164 |

**Against the hypotheses:** (1) **failed** — 0.484 at item level, below the predicted 0.6, though above the 0.4 line that would have invalidated the method. (2) **confirmed** — 0.647 at language level, clearly above the item level. (3) **confirmed** — the offset widens monotonically as quality falls. (4) **confirmed** — recall is the more forgiving metric everywhere, in every band.

### The finding that was not predicted: fact recall saturates

**317 of 378 items scored exactly 1.00.** Above chrF++ 60, *every single item* scored 1.0, which is why ρ is undefined there — a constant has no ordering. Between 40 and 60 it is 129 of 135, and ρ collapses to 0.18. Only below chrF++ 40 does recall carry real signal.

So the moderate item-level correlation is not the metrics disagreeing. It is **fact recall having almost no resolution above the bottom of the range.** A four-fact checklist can take five values, and any competent translation recovers all four. The proxy answers "did the meaning survive", and above a low bar the answer is always yes.

### The disagreements are script failures, and the gate already catches them

22 items scored chrF++ below 20 while recalling 90% or more of the facts. **19 of those 22 carry a gate verdict of `wrong_script` (16) or `wrong_language` (3).**

> `azb` — South Azerbaijani, Arabic script. The model answered in Latin-script Azerbaijani: *"JAS 39C Gripen təyyarəsi yerli vaxtla saat 9:30 radələrində (0230 UTC)…"*. chrF++ **0.38** against the Arabic-script reference — almost no character overlap — while the back-translation recovered every fact, giving recall **1.0**.
>
> `bjn-Arab` (Banjar, Arabic script) and `ks-Deva` (Kashmiri, Devanagari) fail identically: right meaning, wrong script, chrF++ 0.34 and 11.05.

**Fact recall is script-blind and language-blind; chrF++ is neither.** That is not a defect in the proxy so much as a statement of what it measures — and the tool does not use recall alone. A tier is a function of `s_lang` (the deterministic gate) *and* `s_content` (recall), and the gate is precisely what catches wrong script and wrong language for free. The two halves of the score are covering each other's blind spots, which is what the design intended, now demonstrated rather than assumed.

Restricting the correlation to items the gate passed moves ρ only from 0.484 to **0.502**, because saturation, not script failure, is what limits it.

## Correction, added 2026-09-24

**This protocol treated chrF++ as ground truth, and never justified doing so.** [Protocol 016](016-which-metric-is-wrong.md) adjudicated the disagreements with a blind third opinion and found that in the chrF++ 40–60 band, **90% of the items where recall said 1.00 are adequate translations**. chrF++ was penalising legitimate paraphrase against its single reference.

So the framing below — "the proxy is low resolution", "`s_content` is a broken gradient" — is **wrong in the direction that matters**. Fact recall was reporting those translations as adequate because they are adequate. Adequacy is close to binary above a threshold, and `s_content` is an **adequacy floor** that works, not a gradient that failed.

Conclusion 4 below is not merely unaffected but strengthened: 016 found an LLM adjudicator missed **15 of 15** real script mismatches while the deterministic gate caught all of them.

The original conclusions are kept unedited below, as the convention requires.

## Conclusions

1. **The proxy is directionally sound and low-resolution.** It ranks languages the way chrF++ does at ρ 0.647, which supports the five-tier reporting the tool actually does. It does not support finer claims, and none should be made.
2. **`s_content` does much less work than the thresholds imply.** With 84% of items at recall 1.0, the `≥ 0.70 / 0.50 / 0.30` content thresholds in `probe/score.py` are passed by nearly anything competent — so in practice **the tier is decided almost entirely by `s_lang`, the gate.** That is a real and uncomfortable statement about the current scoring, and the honest reading is that `s_content` currently behaves as a floor check rather than a quality gradient.
3. **Recall systematically overstates quality, and worst where it matters most.** The offset is +0.28 at the top and +0.56 at the bottom — the bottom being exactly where a TMS decision flips between "do not offer" and "MT-assist only".
4. **The gate is load-bearing, not a cost optimisation.** It was introduced to make negatives free; this study shows it is also what keeps a script failure from being scored as a success.

**Limits:** one model, one judge, one back-translator panel, 4 items per language, and a translation task standing in for free generation. The saturation result is the most robust finding here and the least dependent on those choices; the exact ρ is the least.

## Impact

- The method survives, with its resolution stated: **language-level ranking, five tiers, no finer.**
- **Open for the next stage:** raise the resolution of `s_content` — more facts per item, or harder facts — or else stop treating the content thresholds as a gradient and say plainly that the gate carries the tier. This should be settled before any tier threshold is quoted publicly (S8/S9).
- Protocol 011's open question is now partly answerable: with recall saturated, the reliability/quality relationship cannot be read off this data either, for the same reason.
