# 010 — Country-qualified designators

| | |
|---|---|
| **Date** | 2026-09-17 |
| **Status** | valid, underpowered — direction recorded, claim not made |
| **Triggered by** | Andrei: *"What if we try to use the fully qualified language name instead? Not `cv`, but Chuvash (Russia). I see the possibility to fall down to Russian instead, but we need to check."* |
| **Artifacts** | `experiments/designator_region_test.py`, `experiments/results/designator_region.jsonl` |

## Hypothesis

Two, in tension:

1. **Naming the country gives the model more to go on** and should raise the chance it produces the right language.
2. **Naming the country is a trap**: it may pull the model toward that country's *dominant* language — "Chuvash (Russia)" producing Russian, "Uyghur (China)" producing Chinese. That is the nearest-relative substitution failure, which the gate can now detect directly.

Andrei raised both. The second was his own stated concern.

Note on the premise: the designator already uses the language *name*, not the tag — candidate A is `"Chuvash (Cyrillic script)"`. What had never been tried is qualifying by **country**; `region_name` is a parameter of the designator builder that the pipeline never passes.

## What was tested

Six designator forms across seven languages, scored on gate outcome alone — **no judge calls**.

| Form | Example |
|---|---|
| `name` | `Chuvash` |
| `name+script` (current candidate A) | `Chuvash (Cyrillic script)` |
| `name+country` | `Chuvash (Russia)` |
| `name+country+script` | `Chuvash (Russia, Cyrillic script)` |
| `endonym` | `чӑваш` |
| `tag` | `cv` |

Languages chosen so that naming the country is a plausible trap, plus two controls:

`cv`→Russian · `ug`→Chinese · `bo`→Chinese · `ti`→Amharic · `gsw`→German · `mt` (control) · `af` (control)

## Setup

| | |
|---|---|
| Model | `openai-gpt-4o` |
| Parameters | `temperature=0`, `max_tokens=400`, reasoning off |
| Sample | 7 languages × 6 variants × 2 items = **84 calls**, 14 per variant |
| Gate | full deterministic gate including GlotLID |

## Results

| Variant | pass | refused | wrong language |
|---|---|---|---|
| `name` | 4 | 9 | 0 |
| **`name+script`** | **9** | 5 | 0 |
| `name+country` | 4 | 9 | **1** |
| `name+country+script` | 7 | 7 | 0 |
| `endonym` | 6 | 8 | 0 |
| `tag` | 4 | 10 | 0 |

**The predicted trap fired exactly once**, and on the language where it was most plausible:

> `gsw` — *"German, Swiss (Switzerland)"* → GlotLID `deu_Latn`. The model produced **Standard German**.

**The dominant signal is refusal, not error.** Across all 84 calls there was exactly one wrong-language output. The variants differ almost entirely in how often the model **agreed to try at all** — 5 refusals for `name+script` against 10 for `tag`.

**Per-language notes:**

- `ti` — the endonym `ትግርኛ` scored 2/2 where every other form managed at most 1/2, reproducing [009](009-ladder-and-designator-sweep.md).
- `gsw` — the bare tag `gsw` scored 2/2, and `name+country+script` also 2/2, while `name+script` managed 1/2. This contradicts 009's "the raw tag never wins": for a language whose ISO code is more recognisable than its awkward English name ("German, Swiss"), the tag can be the better designator.
- `cv` — refused under **every** variant except one `name+script` item. Chuvash never fell to Russian; it simply refused.
- `mt`, `af` — the controls passed under every variant except `tag` for Maltese, confirming the harness is not manufacturing failures.

**Significance (Fisher exact, n=14 per variant):**

| Comparison | p |
|---|---|
| `name+script` vs `name+country` | 0.128 |
| `name+script` vs `tag` | 0.128 |
| `name+script` vs `endonym` | 0.449 |
| `name+script` vs `name+country+script` | 0.704 |

**None reach conventional significance.** The direction is consistent across languages but this sample cannot carry a strong claim.

## Conclusions

1. **Adding the country does not help, and plausibly hurts.** `name+country` matched the worst variants on willingness and produced the only wrong-language output in the experiment. Adding country *on top of* script (7/14) was no better than script alone (9/14).
2. **Andrei's concern was correct in kind.** Naming a country can pull the model to that country's dominant language. It happened once — Swiss German → Standard German — which is exactly the case where the two languages are closest and the country is most strongly associated with the dominant one.
3. **The designator mostly governs willingness, not correctness.** This reframes what the sweep optimises: it is not steering the model toward the right language so much as getting it to attempt the task. That connects the sweep directly to the `reliability` metric added in 009.
4. **No single form wins everywhere.** `name+script` is the best default, the endonym wins for Tigrinya, and the bare tag wins for Swiss German. That is an argument for keeping the sweep rather than fixing one form.

**Limits:** one model, 84 calls, two items per cell, single snapshot. Gate-only scoring means a "pass" here is *the right language*, not *good output*. Underpowered by design — it was a screening test, not a measurement.

## Impact

- **Decision: do not add country to the default designator.** Candidate A stays `name (Script script)`. The `region_name` parameter stays in the builder but unused by default.
- The finding that designators mostly move *willingness* rather than *correctness* is recorded against the `reliability` metric — they measure closely related things and should be interpreted together.
- The `gsw` result qualifies 009's claim about raw tags: the tag is the worst default, not a form that never wins. Worth keeping candidate C in the sweep rather than dropping it as 009 might have suggested.
- A properly powered version — more languages, more items per cell, several models — is a good candidate for the calibration work at S7, where the same generations can serve both studies.
