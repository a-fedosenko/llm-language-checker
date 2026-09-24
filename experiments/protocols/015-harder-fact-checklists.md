# 015 — Does fact recall saturate because the facts are easy, or intrinsically?

| | |
|---|---|
| **Date** | 2026-09-24 |
| **Status** | valid, but uninformative — the intervention was too weak to answer the question. See [016](016-which-metric-is-wrong.md) |
| **Triggered by** | [Protocol 014](014-fact-recall-vs-chrf.md): 317 of 378 items scored recall exactly 1.00, and above chrF++ 60 every item did. If that is a property of the checklists it is fixable; if it is a property of the metric it must be documented instead |
| **Artifacts** | `data/calibration/specs.hard.json`, `data/calibration/study.hard.json`, `src/llmlc/probe/calibrate.py` |

## Hypothesis

The question is whether `s_content` can be made to discriminate at all, because protocol 014 showed the current thresholds (`0.70 / 0.50 / 0.30`) are cleared by nearly anything competent — so the tier is decided almost entirely by the gate.

Two readings, and they imply different projects:

- **Fixable.** Recall saturates because a checklist of four plain facts ("a dog barks", "it happened at 9:30") survives any translation that is merely adequate. Facts chosen for the details mediocre translation actually loses — exact numbers, negation, modality, who did what to whom — would separate good from adequate.
- **Intrinsic.** Fact recall asks whether *meaning survived*, and above a low bar meaning either survives or it does not. The metric is close to binary by construction, and no choice of facts rescues a gradient that the measurement cannot express.

**Predicted: mostly fixable, partly intrinsic.** Specifically:

1. **Saturation falls materially.** Items scoring exactly 1.00 drop from 84% to **below 60%**.
2. **Item-level correlation with chrF++ improves**, from 0.484 to **above 0.60** — the threshold protocol 014 predicted and missed.
3. **The improvement is concentrated in the bands where the old checklist was blind.** Above chrF++ 60 the old checklist had *no* variance at all (79/79 at 1.00); if hard facts are working, that band should now show a spread.
4. **Language-level correlation moves little.** It was already 0.647, and averaging over items hides checklist granularity. A large change here would suggest something other than resolution changed.

**The failure mode to watch is saturation at the other end.** Facts can be made so demanding that every translation misses some, collapsing recall toward zero and destroying the gradient just as thoroughly. If mean recall falls below ~0.3 the checklists are too hard, and that is a failed intervention, not a finding about models.

## Design: the same texts, judged twice

The comparison is **paired at the item level**. Protocol 014 stored every translation and every back-translation, so this re-judges those exact texts against new checklists. No sentence is translated again.

That makes the checklist the only variable: identical model outputs, identical back-translations, identical chrF++ scores, identical judge. Any change in recall is attributable to the facts and to nothing else — which is a far stronger design than running a fresh sample would have been, and it costs two calls per item instead of four.

It is also the first real use of the corpus as doc 01 intended it: *when the method changes, re-grade offline instead of re-running every model.*

## Setup

| | |
|---|---|
| Source texts | the 378 paired items of protocol 014, unchanged |
| Extractor | `openai-gpt-4o-mini`, new prompt targeting discriminating detail |
| Judge | `openai-gpt-4o-mini`, unchanged, same prompt |
| Cost | ~378 extraction + ~378 judge calls; no translation, no back-translation |

## Note recorded before the results, after inspecting the checklists

The hard checklists were inspected as soon as they were built, and **the intervention is weaker than intended.** Mean facts per item moved from 3.9 to 4.0. 101 of 102 checklists differ from their plain counterpart, but mostly by splitting one claim into two:

> **plain** — "The crash occurred at around 9:30 am local time."
> **hard** — "The crash occurred at around 9:30 am local time." *plus* "The crash occurred at 0230 UTC."

A FLORES sentence is a short news sentence; it does not contain more checkable facts than it contains. Hardness cannot be conjured by asking for more of them.

This is recorded **before** running the re-grade, because it changes what a null result would mean. If recall does not move, the honest conclusion is *"this intervention was too weak to tell"* — **not** "saturation is intrinsic". Distinguishing those two needs a different experiment, which is why [protocol 016](016-which-metric-is-wrong.md) was opened rather than reading this one's null as an answer.

## Method

Extract hard checklists over the same 378 sentences, re-judge the stored back-translations against them, and compare paired at the item level.

## Results

196 items had checklists on both sides and a recall score on both.

| | mean recall | saturated at 1.00 | floored at 0 | rho vs chrF++ |
|---|---|---|---|---|
| plain checklist | 0.925 | 164 / 196 (83.7%) | 3 | 0.495 |
| **hard checklist** | 0.909 | **161 / 196 (82.1%)** | 8 | **0.505** |

By band, the picture does not move either:

| band | n | saturated before -> after | rho before -> after |
|---|---|---|---|
| chrF++ >= 60 | 43 | 43 -> 43 | undefined -> undefined |
| chrF++ 40-60 | 76 | 72 -> 71 | 0.207 -> 0.201 |
| chrF++ < 40 | 77 | 49 -> 47 | 0.420 -> 0.415 |

**Nothing changed.** Saturation fell by 1.6 points, rho rose by 0.01, and above chrF++ 60 every item still scores a perfect recall. All four predictions failed: saturation did not drop below 60%, rho did not exceed 0.60, the top band gained no variance, and the language-level figure moved down (0.647 -> 0.575) rather than staying put — that last being the 196-item subset rather than a real decline.

## Conclusions

**This experiment does not answer its question, and the note recorded before the run says why.** The checklists were inspected as soon as they were built and found barely harder — 4.0 facts per item against 3.9, differing mostly by splitting one claim in two. A null result from an intervention that did not really intervene tells us nothing about whether saturation is intrinsic.

What it does establish, weakly: **recall is insensitive to how a FLORES sentence's facts are carved up.** Asking for the same content in five pieces rather than four changes nothing, which is at least consistent with the metric measuring something real rather than an artefact of checklist construction.

The question itself is answered by [protocol 016](016-which-metric-is-wrong.md), which attacks it from the other side: rather than trying to make recall discriminate more, it asks whether recall was right all along and chrF++ was the wrong yardstick.

## Impact

- `scripts/build_calibration_specs.py --profile hard`, plus `calibrate.regrade()` and `compare()` — the offline re-grading path, which is how the corpus earns its keep. This run cost ~378 judge calls and no translation calls at all; re-running the study outright would have cost four times that.
- A rule worth keeping: **inspect the manipulation before paying for the measurement.** Had the checklists been examined after the run rather than before, this null would have read as a finding.
