# 02 — Experiment: invented-language control

Date: 2026-09-15
Models: `openai-gpt-4o`, `gemini-gemini-3-8-flash`, `deepseek-deepseek-v4-pro` via the Logrus aggregator
Settings: `temperature=0`, `max_tokens=300`, **reasoning disabled**, 68 calls per model
Script: `experiments/invented_language_test.py`
Raw responses: `experiments/results/nothink/<model>.jsonl`

## Purpose

`languages_mt_support.json` holds an `mt.chatgpt` designator for 422 of our 602 tags. Roughly 100 came from OpenAI's documentation; the remaining ~322 were produced by asking the model *"what is the language tag you would understand for X?"* and keeping the answer if it looked reasonable.

Doc 01 predicted that this method would return a plausible tag for a language that does not exist. This experiment tests that, and separates two different confabulations: inventing an **interface identifier**, and producing **text** in a language the model cannot write.

## Design

24 language descriptions in three strata × three prompt variants (`v3_write` skipped for well-known):

| Stratum | n | Content |
|---|---|---|
| **invented** | 10 | Plausible-sounding, zero collisions against all 850 distinct names in `languages.json` |
| **real_obscure** | 10 | Real languages from our own scheme: Acehnese-Arab, Afar-DJ, Aghem, Tigre, Tsakonian, Livonian, Aromanian, Chuvash, Zarma, Wolaytta |
| **well_known** | 4 | de-CH, pt-BR, ar-EG, zh-TW-Hant |

| Variant | Prompt |
|---|---|
| `v1_original` | Replicates the original phrasing verbatim |
| `v2_escape` | Same, plus *"if this language does not exist, or you cannot work with it, reply with exactly NONE"* |
| `v3_write` | *"Write two sentences in X"*, with the same escape hatch |

## Results

| variant | stratum | confab | hedged | refused | unclear | n |
|---|---|---|---|---|---|---|
| v1_original | invented | 9 | 1 | 0 | 0 | 10 |
| v1_original | real_obscure | 10 | 0 | 0 | 0 | 10 |
| v1_original | well_known | 4 | 0 | 0 | 0 | 4 |
| v2_escape | invented | 0 | 0 | **10** | 0 | 10 |
| v2_escape | real_obscure | 7 | 0 | 3 | 0 | 10 |
| v2_escape | well_known | 4 | 0 | 0 | 0 | 4 |
| v3_write | invented | 0 | 0 | **10** | 0 | 10 |
| v3_write | real_obscure | 1 | 0 | 8 | 1 | 10 |

Verdict labels are heuristic; all raw responses were reviewed by eye before the conclusions below.

### Finding 1 — the original phrasing invented a tag for 10/10 nonexistent languages

Prediction confirmed. But the output is not noise: the model **silently substituted a real neighbouring language**.

| Invented | GPT-4o's answer |
|---|---|
| Nurdagh (Türkiye), Arabic script | "the language tag for **Turkish** written in the Arabic script…" |
| Lombric (France) | "the language tag for **French**… is `fr`" |
| Zhalgari (Kazakhstan), Cyrillic | "**Kazakh** written in the Cyrillic script is typically `kk-Cyrl-KZ`" |
| Tesseno (Italy) | "a locality in Italy… would typically be **Italian**" |
| Tavrian (Moldova) | "a dialect of the **Gagauz** language spoken in Moldova" |
| Kelmari (Nepal), Devanagari | "Kelmali (also known as Kelmari)… would…" — invents an alternate name |

Only *Andaluvian (Spain)* produced a genuine "there is no widely recognized language called…".

This is the **nearest-relative substitution** failure mode that doc 01 identified as the dominant long-tail risk — appearing one layer earlier than expected, at tag selection rather than at generation. Confident, plausible, wrong-language answers are far more dangerous than gibberish, because they survive manual review.

### Finding 2 — an escape hatch fixes confabulation completely, and introduces over-refusal

`v2_escape` refused **10/10** invented languages. The confabulation is entirely an artifact of phrasing, and the fix costs nothing.

But the same phrasing then refused **3 of 10 real languages** from our own scheme — Acehnese (Arabic script), Tsakonian, Aromanian. So v2 trades over-claiming for over-refusing. **Neither phrasing is a capability measure.**

### Finding 3 — a tag claim does not predict writing ability

| Language | v2 tag | v3 write |
|---|---|---|
| Aghem (Cameroon) | `agq` | **refused** |
| Tigre (Eritrea) | prose answer | **refused** |
| Livonian (Latvia) | `liv` | **refused** |
| Zarma (Niger) | `zrm` | **refused** |
| Wolaytta (Ethiopia) | `wal` | **refused** |
| Afar (Djibouti) | `aa-DJ` | wrote: *Maacaa kee nagaa? Nagaay adar?* |
| Chuvash (Russia) | `cv` | wrote: *Куҫар ҫӗрӗҫе юратнӑ. Тӑван ҫӗрӗмӗн кӗтесем.* |
| Acehnese-Arab / Tsakonian / Aromanian | NONE | refused |

**Of the 7 languages that produced a confident tag, only 2 would write.** Tag-presence predicts writing ability at roughly 29% — measured against the model's own behaviour, not against ground truth, which can only be worse.

Caveat, deliberately not overstated: a `v3` refusal may be conservatism rather than inability, since it is a single bare ask with no designator variation. That is precisely why Probe 3 uses content-controlled generation across several designators. It does not weaken the narrow conclusion: **the existing column records what the model says about its interface, not what it can do.**

## Harness finding: reasoning must be disabled

The first pass left each model at its default deliberation setting. That was wrong, and it invalidated the first cross-model comparison.

`openai-gpt-4o` does not reason. `gemini-gemini-3-8-flash` and `deepseek-deepseek-v4-pro` both reason by default. Comparing their answers therefore conflated model knowledge with whether the model was allowed to deliberate — and the effect was large enough to reverse a conclusion (see below).

Four reasons reasoning must be off for this work:

1. **Fidelity.** The method being replicated was a plain chat call. If deliberation changes the answer, the experiment measures something that never happened.
2. **Comparability.** Leaving each model at its own default makes cross-model results meaningless.
3. **Production realism.** The pipeline will issue bulk "write 3 sentences in X" calls across 600 languages. That will never be run with reasoning on, so measuring with it on measures a configuration we will not ship.
4. **Cost and latency.** On a single Chuvash prompt, DeepSeek spent 299 completion tokens — **all of them reasoning** — and returned empty content with `finish_reason: length`. With `reasoning_effort: "none"` it answered in **2 tokens**. Gemini went from ~300 hidden thinking tokens and truncated output to a clean 26-token answer. Roughly 25 s per call became roughly 1 s.

**Implementation note, and a real constraint for the product:** `reasoning_effort: "none"` is honoured on the gemini and deepseek routes; `"minimal"` and `extra_body.thinking` are rejected; and `openai-gpt-4o` rejects the parameter outright with `Unrecognized request argument supplied: reasoning_effort`. **"OpenAI-compatible" is not uniform.** The harness now probes support per model and falls back automatically, and the production pipeline needs the same capability probe at job start.

## Cross-model results, reasoning disabled

### v1 original phrasing, invented languages — hand-classified from raw text

| Model | Correct refusal | Substituted or fabricated |
|---|---|---|
| `openai-gpt-4o` | 1 (Andaluvian) | **9** |
| `gemini-gemini-3-8-flash` | 3 (Tavrian, Merovian, Lombric) | **7** |
| `deepseek-deepseek-v4-pro` | 0 | **10** |

The core finding holds across all three models and is not a GPT-4o quirk.

**Correction to the first pass.** With reasoning left on, Gemini refused roughly 6 of 10 and appeared markedly more honest than GPT-4o. With reasoning off it fabricates 7 of 10. That difference was an artifact of deliberation, not a property of the model, and the earlier claim is withdrawn.

**Better models fabricate more dangerously.** GPT-4o substitutes vaguely ("Lombric… the language tag for French is `fr`"). Gemini invents *precise* identifiers and plausible provenance: `xkm-Deva-NP` for Kelmari, `crh-Arab` for Nurdagh, Selvanic as "a Romance language formerly spoken on the Croatian island of Silba", Tesseno as "an endangered, highly localized Gallo-Italic dialect". DeepSeek invents alternate names — "Tavrian, also spelled Taurian", "Selvanic, also known as Selvan or Selvanski", "Kashtari, also known as Kalam Kohistani". A fabricated ISO code with a fabricated language family attached will survive expert manual review far more often than a vague substitution.

Gemini produced one genuine flash of grounding: it noted that *le lombric* is French for "earthworm" and refused on that basis.

### Self-report fails in both directions, within a single model

DeepSeek answered `NONE` when asked for an Aromanian tag, then wrote plausible Aromanian when asked to write it — *"Nica nu am vidzutã un lucru ca aiestu."* Tag-refusal is not evidence of inability, just as a tag claim is not evidence of ability.

### Confident tags are frequently invalid

| Model | Language | Tag given | Problem |
|---|---|---|---|
| DeepSeek | Livonian | `lv-liv` | malformed; `lv` is Latvian |
| DeepSeek | Zarma | `zarma` | not a code in any standard |
| GPT-4o | Tigre | `tir` | that is Tigrinya; Tigre is `tig` — and it then refused to write it |
| Gemini | Aghem | `agh` | the ISO 639-3 code is `agq` |

### Writing succeeded where the output is still unusable

Two cases that no tag-based method could ever detect, and that Probe 2 catches for free:

- **GPT-4o, Chuvash:** `Куҫар ҫӗршывӗҫ ҫӗршывӗҫсем ҫӗршывӗ` — degenerate repetition, caught by the n-gram loop detector.
- **Gemini, Acehnese in Arabic script:** the reply opens in **English** commentary rather than in Acehnese — caught by LID plus the script-block check.

### Writing breadth differs sharply

Of the 10 real obscure languages, under v3: GPT-4o wrote 2 (one degenerate), DeepSeek wrote 6, Gemini wrote 10. Whether Gemini's 10 are *correct* is exactly what this experiment cannot determine and what the LID gate plus fact-recall scoring exist to measure. Confident output in all 10 is either genuine breadth or confident fabrication, and the tag column cannot tell them apart.

## Consequences for the method

1. **The ~322 self-reported entries need re-derivation.** Confirmed, no longer suspected.
2. **Probe 0 must use the escape-hatch phrasing** — and must still never be treated as ground truth, since it both over-refuses (3/10) and over-claims (5 of 7).
3. **The honesty probe (Probe 1) should run both phrasings.** `v1` measures over-claim, `v2` measures over-refusal. These are two distinct per-model coefficients, not one.
4. **Probe 2's nearest-relative check is empirically justified**, and is the single most important gate: the failure mode it catches is the one that actually occurs.
5. **Designator selection (candidates A–E) is validated as necessary.** A single-designator method demonstrably produces plausible wrong answers with no error signal.

## Limitations

- Three models, one snapshot each, single sample per cell. Fine for a yes/no on the prediction; not a measurement.
- **`temperature=0` is not determinism.** GPT-4o was run twice under equivalent settings and the `v3_write` cell moved by one item. Any per-language claim needs repeats.
- The first pass was run with each model's default reasoning setting and is superseded. Its data is kept only as evidence of the confound.
- A run was briefly corrupted by two processes appending to the same output file; that file was discarded and the run repeated.
- The 10 invented names were checked against our own 850 names, not against all ~7000 living languages. Residual collision risk is small but non-zero.
- Verdict classification is regex-heuristic; conclusions rest on eye review of the raw JSONL, which is kept alongside.
