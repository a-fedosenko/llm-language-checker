# 004 — GlotLID capability check

| | |
|---|---|
| **Date** | 2026-09-16 |
| **Status** | valid |
| **Triggered by** | Wiring the deterministic gate, which rests entirely on language identification being accurate and local |
| **Artifacts** | `src/llmlc/probe/lid.py`, `tests/test_gate.py` |

## Hypothesis

That GlotLID would be accurate enough to carry the gate — and, separately, that it would **not** catch degenerate output, so a repetition detector would be needed alongside it rather than instead of it.

## What was tested

Identification accuracy on real model outputs already collected in [001](001-invented-language-control.md), including two predicted failure modes: nearest-relative substitution, and degeneration.

## Setup

| | |
|---|---|
| Model | GlotLID `model_v3.bin`, 1.6 GB, **2,102 language-script labels** |
| Library | `fasttext-wheel` 0.9.2 |
| Hardware | CPU |
| Inputs | verbatim outputs from gpt-4o and gemini captured in earlier runs |

## Results

| Input | Label | Confidence |
|---|---|---|
| Chuvash (gemini) | `chv_Cyrl` | 1.000 |
| Russian | `rus_Cyrl` | 0.998 |
| English | `eng_Latn` | 0.998 |
| Livonian (gemini) | `liv_Latn` | 1.000 |
| Aromanian (deepseek) | `rup_Latn` | 0.896 |
| Kazakh | `kaz_Cyrl` | 1.000 |
| **"Acehnese in Arabic script" (gemini)** | **`min_Arab` (Minangkabau)** | 0.800 |
| **Degenerate Chuvash (gpt-4o)** | **`chv_Cyrl`** | **1.000** |

**Library defect:** `fasttext-wheel`'s `predict()` raises under numpy 2 (`np.array(obj, copy=False)`). The underlying C++ object returns plain `(prob, label)` tuples and is stable, so the wrapper is bypassed rather than pinning numpy — torch will need numpy 2 at S3.

## Conclusions

- GlotLID is accurate enough to carry the gate, and free.
- **Both predicted failure modes confirmed on live data.** Gemini's "Acehnese in Arabic script" is identified as Minangkabau — the nearest-relative substitution the gate exists to catch, appearing unprompted. And gpt-4o's degenerate Chuvash scores `chv_Cyrl` at **1.000**, so LID cannot detect degeneration: the repetition detector is necessary, not redundant.
- Confidence is informative but not binary — see [008](008-twenty-language-spread.md), where a 0.53 call wrongly convicted a model.

## Impact

- GlotLID wired into the gate, with a script-only fallback when the model file is absent so the tool still runs (with reduced power, recorded on the result).
- The repetition detector kept as a separate check with its own threshold.
- Both live cases became regression tests rather than hypothetical ones.
