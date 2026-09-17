# 008 — Twenty-language spread

| | |
|---|---|
| **Date** | 2026-09-16 |
| **Status** | valid |
| **Triggered by** | S2's definition of done: *"a 20-language spread runs with most results carrying real evidence rather than `unverified`"* |
| **Artifacts** | `data/results/evidence.openai-gpt-4o.1.0.0.jsonl`, commit `83024aa` |

## Hypothesis

That control coverage was now the only thing standing between the pipeline and broad use — and that with FLORES controls in place, a 20-language run would mostly return real evidence.

Implicitly, and wrongly: that the scoring logic was correct and only coverage was missing.

## What was tested

A spread deliberately chosen to span script families, resource levels and one macrolanguage:

`de fr es pl uk el he hi th vi sw yo am km my ka is mt cy ga`

## Setup

| | |
|---|---|
| Model under test | `openai-gpt-4o` |
| Back-translator panel | `gemini-gemini-3-8-flash`, `deepseek-deepseek-v4-pro` (routed per language) |
| Judge | `openai-gpt-4o-mini` |
| Items | 2 content specs per language |
| Parameters | `temperature=0`, reasoning off |

## Results

**20/20 real evidence, 0 `unverified`.** The stated goal was met.

But **two verdicts were wrong**, and inspection of the evidence records showed why:

| Tag | Reported | Cause |
|---|---|---|
| `sw` | **None**, deterministic-negative | Output labelled `swh_Latn` at 0.95 — Coastal Swahili, a **member** of the `swa` macrolanguage. The gate called it `relative_substitution` |
| `hi` | **Token**, s_lang 0.50 | One item labelled `anp_Deva` (Angika) at **0.53** confidence. A weak call convicted the model |

Both are wrong for the same underlying reason: the relationship between a macrolanguage and its members, and how much weight a single LID call should carry.

## Conclusions

- **A macrolanguage member is the answer, not a substitution.** Asking for Swahili (`swa`) and receiving Coastal Swahili (`swh`) is the macrolanguage resolving to a member — precisely the `resolves_to` behaviour the design already called for. Treating it as substitution would have produced systematic false negatives on `ar` (28 members), `ms`, `uz`, `az`, `mn`, `zh` and every other macrolanguage.
- **A weak LID call is not evidence.** Correct GlotLID calls have been observed as low as 0.63, so a top-1 disagreement at 0.53 cannot convict a model.
- **The method lesson matters more than either bug: a broad spread found in one run what single-language testing could not.** Both bugs were invisible on `cv` and `de`, and both were systematic rather than incidental.

## Impact

- Macrolanguage members passed to the gate as `accept_lang`, and excluded from `relatives` — a macrolanguage's own members are never neighbours.
- New `low_confidence` gate verdict below 0.60, explicitly **not** counted as a negative; and the target passes if it appears anywhere in the top-5 above 0.15. GlotLID `k` raised from 3 to 5.
- After both fixes, `sw` and `hi` score **Strong**.
- Six regression tests added, written from the live cases rather than from imagination.
- Confirmed for the plan: breadth-first testing is worth more than depth on a single language, which is an argument for running a spread at each future stage rather than only at the end.
