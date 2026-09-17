# 005 — Back-translator fabrication

| | |
|---|---|
| **Date** | 2026-09-16 |
| **Status** | valid — the most consequential result so far |
| **Triggered by** | The first live end-to-end run of the S1 pipeline returning a verdict that looked wrong |
| **Artifacts** | `src/llmlc/bt/qualify.py`, `data/controls/controls.json`, commit `e2ef977` |

## Hypothesis

Before the run, `docs/01` argued that **"reading is a much lower bar than writing, so far more systems clear it"** — and therefore that back-translator qualification was a refinement that could wait for S3.

Both halves of that turned out to be wrong.

## What was tested

Not planned as an experiment. The first real pipeline run scored Gemini on Chuvash as **Token (0.13)** while its output looked correct to inspection, so the back-translator became the suspect and was tested directly against text of known meaning.

## Setup

| | |
|---|---|
| Model under test | `gemini-gemini-3-8-flash` |
| Back-translators compared | `openai-gpt-4o`, `deepseek-deepseek-v4-pro`, `gemini-gemini-3-8-flash`, `anthropic-claude-sonnet-4` |
| Parameters | `temperature=0`, reasoning off |
| Control | Chuvash of known meaning: *"Эпĕ чăвашла пĕлетĕп. Паян çанталăк питĕ аван."* = "I know Chuvash. The weather is very good today." |

## Results

Gemini's Chuvash was correct — *"Пӗр хӗрарӑм ирхи автобуса ӗлкӗреймерӗ. Вӑл ҫумӑр айӗнче ӗҫе ҫуран кайрӗ."* = "A woman missed the morning bus. She walked to work in the rain." GPT-4o back-translated it as **"The sun rises in the east. Its light spreads across the sky."**

**Control test:**

| Back-translator | Output for the known control |
|---|---|
| `openai-gpt-4o` | *"A man is walking. He is wearing a white shirt."* ❌ fabricated |
| `deepseek-v4-pro` | *"I know Chuvash. The weather is very nice today."* ✅ |
| `gemini-3-8-flash` | *"I know Chuvash. Today the weather is very nice."* ✅ |
| `anthropic-claude-sonnet-4` | HTTP 404 — listed by the aggregator but not actually available |

**Same model, same output, different instrument:**

| Back-translator | Verdict for Gemini on Chuvash |
|---|---|
| `openai-gpt-4o` (unqualified) | **Token**, s_content 0.13 |
| `deepseek-v4-pro` (qualified) | **Strong**, s_content 0.93 |

## Conclusions

- **The hypothesis in `docs/01` was wrong, and wrong in the dangerous direction.** A model that cannot read a language **does not refuse — it invents**. GPT-4o declines to *write* Chuvash but silently fabricates a *reading* of it.
- Therefore **reading failures are more dangerous than writing failures**, not less. Writing failures are visible — refusal, degeneration, wrong language — and the gate catches them for free. Reading failures are invisible without a control, and they corrupt the score of a model that did nothing wrong.
- Without qualification the pipeline produces **confidently wrong results**, off by two tiers, with no signal that anything went wrong.
- Model availability cannot be taken from a gateway's own listing.

## Impact

- **Back-translator qualification pulled forward from S3 into S1** and made mandatory before any fact-recall score is reported. Where a control exists and fails, or no control exists at all, the result is `unverified` with the reason named. `no-control` is deliberately **not** a pass.
- `docs/01` corrected in place with a dated correction block rather than a silent edit.
- Control texts seeded by hand (`cv`, `de`, `ru`), which immediately made control coverage the binding constraint — and moved FLORES ingestion onto the critical path, becoming [007](007-flores-sourcing-and-mapping.md) and the whole of S2.
- Later generalised to **per-language routing**: no single back-translator reads everything, so the choice is made per language from cached qualification results.
