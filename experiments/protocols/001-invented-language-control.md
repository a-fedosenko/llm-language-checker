# 001 — Invented-language control

| | |
|---|---|
| **Date** | 2026-09-15 |
| **Status** | valid (first pass invalidated — see [002](002-reasoning-mode-confound.md)) |
| **Triggered by** | Learning that ~322 of the 422 `mt.chatgpt` designators in the internal scheme were produced by asking the model *"what is the language tag you would understand for X?"* and keeping the answer if it looked reasonable |
| **Artifacts** | `experiments/invented_language_test.py`, `experiments/results/nothink/*.jsonl`, `docs/02` |

## Hypothesis

The original method would return a plausible-looking tag for a language that does not exist, because *"what tag would you understand for X?"* is exactly the kind of question a model answers fluently regardless of whether it can do anything with X.

Stated before the run, in `docs/01`, as a falsifiable prediction.

## What was tested

Three separate things, deliberately not conflated:

1. Does the original phrasing produce a tag for a nonexistent language?
2. Does adding an explicit escape hatch fix it — i.e. is the failure one of phrasing or of the model?
3. Does a tag claim predict the ability to actually write the language?

## Setup

| | |
|---|---|
| Models | `openai-gpt-4o`, `gemini-gemini-3-8-flash`, `deepseek-deepseek-v4-pro`, via the Logrus aggregator |
| Parameters | `temperature=0`, `max_tokens=300`, **`reasoning_effort=none`** with per-model fallback |
| Sample | 24 descriptions × 3 prompt variants = 68 calls per model |
| Strata | 10 invented (checked for zero collision against all 850 names in the internal scheme), 10 real-but-obscure drawn from that scheme, 4 well-known |

Prompt variants: `v1_original` replicating the original phrasing verbatim; `v2_escape` adding *"if this language does not exist, reply exactly NONE"*; `v3_write` asking for two sentences with the same escape hatch.

## Method

Each cell run once at temperature 0. Responses classified by regex into confabulated / hedged / refused / unclear, then **hand-checked against the raw text** — the regex proved unreliable on prose-style models, so all conclusions below rest on reading the JSONL, not on the automated counts.

## Results

**Tag fabrication on invented languages, hand-classified:**

| Model | Correct refusal | Substituted or fabricated |
|---|---|---|
| `openai-gpt-4o` | 1 (Andaluvian) | **9** |
| `gemini-gemini-3-8-flash` | 3 (Tavrian, Merovian, Lombric) | **7** |
| `deepseek-deepseek-v4-pro` | 0 | **10** |

**The output is not noise — it is substitution of a real neighbour:**

| Invented | GPT-4o's answer |
|---|---|
| Nurdagh (Türkiye), Arabic script | "the language tag for **Turkish** written in the Arabic script…" |
| Lombric (France) | "the language tag for **French**… is `fr`" |
| Zhalgari (Kazakhstan), Cyrillic | "**Kazakh** written in Cyrillic… `kk-Cyrl-KZ`" |
| Tesseno (Italy) | "a locality in Italy… would typically be **Italian**" |

Gemini fabricated more *precisely*: `xkm-Deva-NP` for Kelmari, `crh-Arab` for Nurdagh, Selvanic as "a Romance language formerly spoken on the Croatian island of Silba", Tesseno as "an endangered, highly localized Gallo-Italic dialect". It did catch that *lombric* is French for earthworm.

**Escape hatch:** `v2` refused **10/10** invented languages — a complete fix for fabrication. But it also refused **3 of 10 real** languages from our own scheme (Acehnese-Arabic, Tsakonian, Aromanian).

**Tag claim vs writing ability (gpt-4o):** of 7 real languages that produced a confident tag, **only 2 would write** (Afar, Chuvash). Aghem, Tigre, Livonian, Zarma and Wolaytta gave tags and then refused.

**Self-report fails in both directions within one model:** DeepSeek answered `NONE` for an Aromanian tag, then wrote plausible Aromanian on request.

**Confident tags are often invalid:** `lv-liv` for Livonian (malformed — `lv` is Latvian), bare `zarma` (not a code), `tir` for Tigre (that is Tigrinya; Tigre is `tig`), `agh` for Aghem (the code is `agq`).

## Conclusions

- The prediction is **confirmed across three models**; it is not a GPT-4o quirk.
- The dangerous property is not fabrication but **plausibility**: a fabricated ISO code with a fabricated language family attached survives expert manual review. Stronger models fabricate more convincingly.
- **Neither phrasing measures capability.** `v1` over-claims, `v2` over-refuses.
- Self-report is not evidence in either direction.

Limits: one snapshot per model, single sample per cell, heuristic pre-classification. Enough for a yes/no on the prediction; not a measurement. `temperature=0` did not reproduce exactly across two gpt-4o runs.

## Impact

- The ~322 self-reported entries in the internal scheme need re-derivation. Confirmed, no longer suspected.
- **Probe 0 (self-report) can never be ground truth**, and Probe 1 must run *both* phrasings to measure over-claim and over-refusal as separate per-model coefficients.
- **Designator selection became part of the method**: a `None` verdict must mean "none under our best designator", never "none under one arbitrary string". Candidates A–E defined in `docs/01`, with the incumbent carried as candidate E so selection can be measured against it.
- Probe 2's nearest-relative check moved from theorised to empirically justified — substitution is the failure that actually occurs.
