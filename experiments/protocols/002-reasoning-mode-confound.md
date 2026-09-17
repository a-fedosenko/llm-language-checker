# 002 — Reasoning-mode confound and endpoint parameter compatibility

| | |
|---|---|
| **Date** | 2026-09-15 |
| **Status** | valid |
| **Triggered by** | Andrei, reviewing the first cross-model run: *"Why do you use thinking mode in these tests? Do we really need it? DeepSeek ate 10 times more output tokens than the others. I feel like API calls were configured too eagerly."* |
| **Artifacts** | `experiments/invented_language_test.py`, `src/llmlc/client/openai_compat.py` |

## Hypothesis

Initially none — the first cross-model run of [001](001-invented-language-control.md) left every model at its **default** deliberation setting, without considering that the defaults differ.

The hypothesis under test after the challenge: **the cross-model comparison was confounded**, because `gpt-4o` does not reason while `gemini-3-8-flash` and `deepseek-v4-pro` do so by default.

## What was tested

1. Whether reasoning can be disabled through the aggregator, and by which parameter.
2. Whether disabling it changes the conclusions of 001.
3. The token and latency cost of leaving it on.

## Setup

| | |
|---|---|
| Models | `openai-gpt-4o`, `gemini-gemini-3-8-flash`, `deepseek-deepseek-v4-pro` |
| Parameters probed | `reasoning_effort: none` / `minimal`, `extra_body.thinking.type: disabled` |
| Control prompt | *"Write two sentences in Chuvash. If you cannot, reply exactly NONE."* |

## Method

Single-prompt probe per model per parameter, inspecting `finish_reason`, `usage.completion_tokens`, `usage.completion_tokens_details.reasoning_tokens` and the content. Then a full re-run of all three models in 001 with reasoning disabled.

## Results

**Parameter support is not uniform across an "OpenAI-compatible" gateway:**

| Model | `reasoning_effort: none` | `minimal` | `extra_body.thinking` |
|---|---|---|---|
| `deepseek-v4-pro` | honoured | ignored | ignored |
| `gemini-3-8-flash` | honoured | **error** | **error** |
| `openai-gpt-4o` | **HTTP 400** `Unrecognized request argument supplied: reasoning_effort` | — | — |

**Cost of leaving it on, one prompt:**

| Model | Default | `reasoning_effort: none` |
|---|---|---|
| `deepseek-v4-pro` | 299 completion tokens, **all reasoning**, content empty, `finish_reason=length` | **2 tokens**, `finish=stop`, `"NONE"` |
| `gemini-3-8-flash` | ~300 hidden thinking tokens, content truncated to `' кӑшт пӗлетĕп. ('` | **26 tokens**, clean Chuvash |

Roughly 25 s per call became roughly 1 s.

**Effect on the conclusions of 001:**

| v1 original, invented languages | thinking on (default) | thinking off |
|---|---|---|
| `gpt-4o` | 10/10 gave a tag | 10/10 |
| `gemini-3-8-flash` | **~6/10 correctly refused** | **8/10 gave a tag** |
| `deepseek-v4-pro` | stalled / substituted | 9/10 |

## Conclusions

- **A conclusion was withdrawn.** With reasoning left on, Gemini appeared markedly more honest than GPT-4o. With it off, it fabricates 7 of 10 (hand-classified). That difference was an artifact of deliberation, not a property of the model.
- **Reasoning must be off for all measurement**, for four reasons: fidelity (the method being replicated was a plain chat call); comparability (defaults differ per model); production realism (bulk generation across hundreds of languages will never run with reasoning on); and cost.
- **"OpenAI-compatible" is not uniform.** Parameter support must be probed per model and cached, never assumed.
- A reasoning model can spend its entire budget before emitting anything. `finish_reason=length` with empty content is **truncation**, and must never be scored as a refusal — the first run silently did exactly that for two whole models.

## Impact

- `max_tokens` back to 300; `reasoning_effort: none` sent with automatic per-model fallback on HTTP 400; truncation reported as its own verdict rather than scored. All three behaviours carried into `src/llmlc/client/openai_compat.py` as the production client.
- The production pipeline needs a **capability probe per model at job start** — recorded in `docs/01` and `docs/03`.
- Process failures also recorded: an orphaned `nohup` process ran alongside its replacement and corrupted a results file (discarded, re-run), and `temperature=0` did not reproduce exactly across two gpt-4o runs.

**Andrei's challenge was correct and changed a published conclusion.** Worth noting as a method lesson: defaults that differ per vendor are a confound even when no parameter was set.
