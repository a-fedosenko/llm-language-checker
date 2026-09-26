# 019 — The script check's alphabet is incomplete, and now that costs a verdict

| | |
|---|---|
| **Date** | 2026-09-26 |
| **Status** | *(pending — hypotheses recorded before the run)* |
| **Triggered by** | Planning the breadth run. `lid.detect_script` can emit **29** ISO 15924 codes; the shipped scheme asks for **202**. Where the scheme wants a script the function cannot produce, `gate.check` returns `wrong_script` whatever the model wrote — and since [protocol 018](018-eligibility-and-adequacy.md) that is `Unusable`, full stop, with no appeal and no interval |
| **Artifacts** | `scripts/script_audit.py`, re-analysis of `data/calibration/study.json`. No model calls |

## Why this is not the same as protocol 016's finding

016 measured the deterministic script check being **right**: 15 of 15 real mismatches caught, against 0 of 15 for a capable LLM told explicitly to look. That result is not in question here and nothing below touches it.

This is the same function being **blind** — returning a confident negative for a script it has no way to name. Incompleteness, not error. The two are easy to conflate and have opposite fixes: 016 says never replace the check with a model call, and 019 says the check has to be able to spell the alphabet it is checking against.

It has become urgent because of 018. Under the five-tier scale a script miss was one term among several and a language could still land mid-scale; under the new one, ineligibility is absolute. **A blind spot that used to cost resolution now costs the whole verdict.**

## Scope of the damage, measured before the hypotheses

| | tags |
|---|---|
| scheme tags whose script the detector can never emit | **1,274** of 9,589 |
| — of those, `Zyyy` / `Zxxx` / `Zzzz` / `Brai` (no real script claim, or not scannable) | 697 |
| — of those, a real living writing system | **577** |
| classes in the planned `--with-controls --living-only` scan | **6** of 199 |

The six: `kor|Hang`, `zho|Hans`, `zho|Hant`, `yue|Hant`, `lao|Laoo`, `sat|Olck`. Korean and both Chinese among them.

Four of the six are in the S7 calibration study — `ko-Hang`, `zh-CN`, `yue`, `sat` — with committed output, so this protocol costs nothing to run.

## The four failures are not one failure

Separating them before testing, because they need different fixes and only one of them is hard:

1. **Alias mismatch.** The scheme says `Hang`; the table maps HANGUL to `Kore`. Both name Korean writing — `Hang` is Hangul, `Kore` is the composite Hangul+Han code — and they compare unequal. Nothing is undetected; two spellings disagree.
2. **Absent hints.** `Laoo`, `Olck` and most of the other 577 are missing from a hand-written table of 29 entries. Unicode character names carry the script as a prefix (`LAO LETTER KO`, `OL CHIKI LETTER LA`), so this table should be *derived*, not maintained by hand.
3. **Genuinely undecidable by block counting.** `Hans` versus `Hant`. Every Chinese character in both is `CJK UNIFIED IDEOGRAPH`; the distinction is which characters, not which block. No amount of fixing the table reaches this.
4. **No script claim at all.** `Zyyy` (undetermined), `Zxxx` (unwritten), `Zzzz` (unknown). The check currently fails these; it should not run.

And one adjacent constant, found while reading the gate: **`MIN_CHARS = 25`**, which voids an item as `too_short`. Chinese says in 20 characters what English needs 90 for.

## Hypothesis

Recorded before any code was changed.

1. **Deriving the table from Unicode closes most of the gap.** Generating script hints from character-name prefixes instead of hand-listing 29 will make **at least 150 of the scheme's 202 requested scripts** emittable, and will resolve `Hang`, `Laoo` and `Olck` — five of the six blocked classes in the planned scan, everything except the `Hans`/`Hant` pair.

2. **`Hans` versus `Hant` is not decidable by block detection, at all.** Prediction stated so it can fail: **100%** of the study's Chinese items will detect as one and the same script code whether the output is simplified or traditional. If even a few separate, block detection is doing more than I think and the fix is smaller than I think.

3. **A character-set discriminator does decide it.** Simplified and traditional forms are largely disjoint character sets. Built from the committed FLORES Chinese references and applied to the study's `zh-CN` and `yue` output, it will classify **at least 90%** of items correctly. Below ~80% the honest move is to stop claiming the distinction rather than ship a coin flip — the scheme would keep `Hans`/`Hant` as an addressing convention the gate does not verify, recorded as a limit.

4. **`MIN_CHARS = 25` is a Latin-centric constant that voids correct output.** At least **one in five** items in dense scripts (`Hans`, `Hant`, `Jpan`, `Hang`, `Mymr`) will fall below 25 characters while recalling ≥ 0.75 of their facts — correct text thrown away for being short in a script that is short.

5. **Nothing already working changes.** The regression guard, and the one that would sink the fix rather than adjust it: re-running the gate over all 378 committed items must change **zero** verdicts for items whose expected script the detector already handled — `Latn`, `Cyrl`, `Arab`, `Deva`, `Hebr`, `Beng`, `Gujr`, `Armn`, `Geor`, `Jpan`, `Mymr`. Any movement there means the generated table disagrees with the hand-written one about a script that was never in question, and the generated table would then need auditing rather than trusting.

**What would change the plan rather than the code:** H3 failing. If simplified/traditional cannot be separated reliably, then `Hans`/`Hant` must be documented as unverified addressing rather than silently passed or silently failed — and that is a statement the README and S8 have to carry, not a constant to tune.

## What is being tested

Whether the eligibility filter — now the component that can single-handedly declare a language unusable — can actually name the scripts the catalogue asks it about, and what it should do where it cannot.

## Setup

| | |
|---|---|
| Models | none. Re-analysis plus local Unicode work |
| Data | `data/calibration/study.json` (378 committed items, 100 languages), `schemes/default.json` (9,589 tags), FLORES-200 Chinese references |
| Libraries | `unicodedata` from the standard library; GlotLID for the language half, unchanged |

## Method

*(to be completed)*

## Results

*(to be completed)*

## Conclusions

*(to be completed)*

## Impact

*(to be completed)*
