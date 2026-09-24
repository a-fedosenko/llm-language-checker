# 016 — When fact recall and chrF++ disagree, which one is wrong?

| | |
|---|---|
| **Date** | 2026-09-24 |
| **Status** | valid — and it revises a conclusion in [014](014-fact-recall-vs-chrf.md) |
| **Triggered by** | [Protocol 014](014-fact-recall-vs-chrf.md) was written as though chrF++ were ground truth and fact recall the thing being validated. That framing was never justified, and it is the load-bearing assumption of the whole calibration |
| **Artifacts** | `scripts/adjudicate.py`, `data/calibration/adjudication.json` |

## The assumption protocol 014 did not examine

014 concluded that fact recall is "low resolution" because it sat at 1.00 while chrF++ varied from 40 to 100. That reading assumes chrF++ is right and recall is blind.

**chrF++ measures character n-gram overlap with one human reference.** A translation that chooses different words, or a different word order, scores low *even when it is perfectly correct* — this is a documented weakness of single-reference surface metrics, not a subtlety. So the same data supports an opposite reading:

> Above chrF++ 40 most translations are genuinely adequate. Fact recall says so, correctly. chrF++ keeps varying because of surface differences that do not affect whether the meaning arrived.

Under that reading, recall is not low-resolution — **adequacy genuinely is close to binary above a threshold**, and it is chrF++ that is noisy for our purpose. The tool reports whether a model can be used for a language, which is an adequacy question, not a stylistic-proximity one.

These two readings imply opposite actions, so the disagreement has to be adjudicated rather than assumed.

## Hypothesis

A third opinion, blind to both metrics, will side with **fact recall in the middle of the range and with chrF++ at the extremes.**

1. **For items with chrF++ 40–60 and recall 1.0**, the adjudicator will call the translation adequate in **over 70%** of cases. These are paraphrase penalties, not errors.
2. **For items with chrF++ below 20 and recall 1.0**, the adjudicator will call it inadequate in **most** cases — protocol 014 showed 19 of 22 such items are `wrong_script` or `wrong_language`, where the meaning survived into the back-translation but the output was not the requested language at all.
3. **Controls will behave**: items where both metrics agree the translation is good should be judged adequate; items where both agree it is bad should be judged inadequate. If the controls misbehave, the adjudicator is not usable and nothing else in this protocol means anything.

**If hypothesis 1 holds, protocol 014's central conclusion is wrong and must be revised** — `s_content` would not be a broken gradient but a correct adequacy signal, and the fix would be to the documentation rather than to the metric.

## Design: who is allowed to adjudicate

The hard problem is that judging a translation into Acehnese requires reading Acehnese — the bootstrap this project exists to avoid. Three guards:

- **The adjudicator must be qualified for the language**, by the same FLORES control test used for back-translators (protocol 005). An unqualified reader fabricates rather than refusing, and a fabricated adjudication is worse than none.
- **It must not be the model under test.** `openai-gpt-4o` produced these translations, and a model grading its own output is the self-preference bias the judge rules already forbid.
- **It must not be the back-translator that produced the recall score for that item**, or the two measurements share a failure. The panel has two members, so the adjudicator is whichever one did not back-translate.

The adjudicator sees the English source and the translation, and is asked whether the meaning arrived and whether the text is in the requested language. It never sees the reference, either metric, or which model produced the text.

## Setup

| | |
|---|---|
| Adjudicator | the qualified panel member that did *not* back-translate the item |
| Sample | stratified from protocol 014's 378 items: disagreement cases (low chrF++, high recall) plus agreement controls at both ends |
| Blinding | source + translation only; no reference, no scores, no model identity |

## Method

119 items adjudicated across four strata, 10 skipped for want of a qualified adjudicator. Each adjudicator saw the English source and the translation, and answered two questions — is the meaning there, and is this the requested language. It never saw the reference, either metric, or which model produced the text.

Afterwards, every item's **script was checked deterministically** by Unicode block counting (`probe/lid.detect_script`). That is not a judgement call, and it turned out to be the most important number in the protocol.

## Results

| stratum | n | adjudged adequate | script actually correct |
|---|---|---|---|
| **disagree-mid** (chrF++ 40–60, recall 1.0) | 40 | **36 (90%)** | 40 / 40 |
| **disagree-low** (chrF++ < 20, recall 1.0) | 17 | 14 (82%) | **4 / 17** |
| control-good (chrF++ ≥ 60, recall 1.0) | 40 | 40 (100%) | 39 / 40 |
| control-bad (chrF++ < 40, recall ≤ 0.34) | 22 | 1 (5%) | 21 / 22 |

**The controls behaved perfectly.** 100% adequate where both metrics agreed the translation was good, 5% where both agreed it was bad. The adjudicator discriminates.

### Hypothesis 1: confirmed, and it overturns protocol 014's headline

**90% of the mid-range disagreements are adequate translations**, against a predicted 70%, and every one of the 40 is in the correct script. These are not failures of fact recall. They are chrF++ penalising a translation for choosing different words than the single reference it is scored against.

So protocol 014's central claim — that fact recall is "low resolution" and `s_content` a broken gradient — **was wrong in the direction it mattered.** Recall reported these translations as adequate because they *are* adequate. Above a threshold, adequacy genuinely is close to binary, and a metric that says so is correct rather than blunt.

### Hypothesis 2: the prediction was right, the instrument was wrong

I predicted the extreme-low band would be genuine failures, and the deterministic check agrees emphatically: **13 of 17 are in the wrong writing system.** South Azerbaijani requested in Arabic script, answered in Latin. Kashmiri requested in Devanagari, answered in Arabic. Santali requested in Ol Chiki, answered in Latin and in Devanagari.

**But the adjudicator did not notice.** It called 14 of those 17 adequate and said "yes, this is the requested language" for most of them. Across all 119 items there were **15 real script mismatches, and the adjudicator flagged `wrong-script` exactly zero times** — despite the prompt offering that category explicitly, by name, as one of three options.

## Conclusions

1. **chrF++ is the wrong yardstick for this project's question**, in the mid range. The tool asks whether a model can be used for a language; that is adequacy, and chrF++ measures surface proximity to one reference. Where they disagree between chrF++ 40 and 60, fact recall is right nine times in ten.
2. **Protocol 014's conclusion 2 is revised.** `s_content` is not a gradient that failed to materialise; it is an **adequacy floor**, and it works. The correct action is to describe it as one, not to try to make it into something it is not — which is also why [015](015-harder-fact-checklists.md)'s attempt to sharpen it changed nothing.
3. **An LLM will not verify a writing system, even when asked directly.** 0 of 15. This is the single most transferable result here: it is precisely the job the deterministic gate does for free, and the one time we handed that job to a language model it failed completely while looking entirely confident. Controls behaving is necessary, not sufficient — this adjudicator scored 100% and 5% on its controls and was still blind on a whole dimension.
4. **The project's core design choice is vindicated by its own failure case.** Deterministic gate for language and script; LLM only for meaning. That split was made in doc 01 on the argument that LID is more accurate than asking a model. It is now measured: 15/15 against 0/15.

**Limits:** one adjudicator family per item, 119 items, and adequacy judged without the reference — a rendering that is fluent and wrong in the same way as the back-translation would pass. The script finding is the robust one; the 90% is a single measurement on 40 items.

## Impact

- Protocol 014's conclusions rewritten where 016 contradicts them, with the original text kept and marked.
- **`s_content` is documented as an adequacy floor rather than a quality gradient.** Whether the three thresholds should collapse to one is now a live question for S8 — the data says they distinguish little above the floor.
- The gate is not a cost optimisation and must never be replaced by a model call, however capable the model. Recorded as a standing convention.
- chrF++ keeps its existing job — back-translator qualification, where the reference *is* the ground truth and surface similarity is exactly what is wanted — and loses its implied status as arbiter of translation quality.
