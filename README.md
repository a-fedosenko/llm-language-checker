# llm-language-checker

**An empirical, heuristic tool for finding out which languages an LLM can actually produce.**

Vendor language lists are marketing. "Supports 100+ languages" has no definition behind it, and for the long tail nobody publishes anything at all. This project measures it instead: you point it at a model, it generates text, checks the text, and reports a graded verdict with its evidence and its uncertainty.

> **Status: early development.** The methodology is documented and partially validated by experiment (see `docs/`). The skeleton, language catalogue and read-only API work; the measurement pipeline is being built.

## What it is not

This is **not** a linguistic authority and **not** a benchmark leaderboard. It is an empirical probe with known limits:

- It measures **generation adequacy in a target language** — not chat quality, not instruction-following in that language, not cultural appropriateness. Those dissociate.
- Sample sizes are small. Results carry confidence intervals, and a result whose interval straddles a tier boundary is reported as `borderline`, never rounded.
- For languages with no aligned reference text, quality cannot be assessed at all. Those are reported `unverified` — which is an honest answer, not a failure.
- Results are only comparable within the same back-translator, judge, and method version. All three are recorded on every result.

Anything it reports is evidence, not proof.

## Run it yourself

There is no hosted service and no public deployment. **You run it locally or in your own cloud**, with your own API keys in your own `.env`. Nothing is sent anywhere except to the model endpoints you configure, and no key is ever stored by the application or entered through a web form.

```bash
git clone https://github.com/a-fedosenko/llm-language-checker
cd llm-language-checker
cp .env.example .env      # add your OpenAI-compatible endpoint + key
docker compose up
```

- API and interactive docs: <http://localhost:8000/docs>
- UI: arrives with the pipeline

No network fetch is needed at setup — the language catalogue ships in the repo.

Without Docker:

```bash
pip install -e ".[dev]"
uvicorn llmlc.api.main:app --reload
pytest
```

## Bring your own locale list

The core speaks canonical **BCP-47** (`kk`, `kk-Latn`, `sr-Cyrl-RS`). Any other tag convention — including orders that put the script last — reaches it through a **scheme adapter**, so no organisation's locale list is baked into the tool.

- `schemes/default.json` ships with the project: **9,589 tags** built from ISO 639-3 code tables, the official ISO 639-3 macrolanguage mapping, and SIL langtags. It carries macrolanguage/member relations, default script and region, and endonyms.
- Drop your own list in `schemes/<name>.json` and set `SCHEME=<name>`. Your list is gitignored; results come back keyed to your tags.
- Regenerate the shipped catalogue with `python scripts/build_default_scheme.py --refresh`.

### Hardware

The stack detects available hardware at startup and selects a profile automatically:

| Detected | Profile | Back-translator | Coverage |
|---|---|---|---|
| GPU ≥ 10 GB VRAM | `gpu-fp16` | MADLAD-400-3B-MT, fp16 | ~400 languages |
| GPU 4–10 GB VRAM | `gpu-int8` | MADLAD-400-3B-MT, int8 | ~400 languages |
| CPU only, or < 4 GB | `cpu` | NLLB-200-distilled-600M | ~200 languages |
| `BT_REMOTE_MODEL` set | `api` | a configured remote model | as qualified per language |

`GET /hardware` reports the resolved profile, and it is recorded on every result — results produced by different back-translators are not comparable.

Language identification runs on CPU everywhere and needs no GPU. Override detection with `HARDWARE_PROFILE` in `.env`. Reference machine: RTX 4060 Laptop (8 GB) → `gpu-int8`; fp16 is deliberately reserved for larger cards, since MADLAD-3B is ~6 GB before activations.

## How it works

Briefly — the full method, its rationale, and the experiments behind it are in `docs/`.

1. **Content-controlled generation.** The model is given a *semantic specification* in a pivot language and asked to write in the target language, choosing its own words. Not a sentence to translate (which rewards copying and punishes paraphrase) and not free writing (which lets the model fall back on memorised text).
2. **Designator selection.** An LLM has no language-code interface — whatever string you pass is just tokens in a prompt. Several candidate designators are tried and the best-performing one is kept, so a negative verdict means "under our best designator," never "under one arbitrary string."
3. **A local deterministic gate.** Refusal, copying, wrong script, wrong language (GlotLID), confusion with a nearest high-resource relative, degenerate repetition, memorised boilerplate. Free, local, and it resolves most negatives before any paid call.
4. **Fact-recall scoring.** Surviving output is back-translated by a fixed, independent back-translator; a blind judge then checks which of the specified facts survived. Grading happens entirely in the pivot language, so **the judge never needs to know the target language.**
5. **Graded verdict.** `None / Token / Basic / Usable / Strong`, with a confidence interval, an evidence class, and the full configuration that produced it.

The back-translator is validated per language against human reference text before it is trusted, so a failure of the instrument is never reported as a failure of the model.

## Output

Two artifacts. A minimal, mergeable file matching the consuming system's schema:

```json
{ "gsw-ch": { "mt.openai-gpt-4o": "Swiss German (Switzerland)" } }
```

and a separate full-evidence report carrying scores, intervals, designators tried, back-translator, judge, provenance, and timestamps. Merging is a per-key, per-engine upsert — a partial run can never wipe existing data.

## Documentation

| | |
|---|---|
| `docs/Basic idea v0.md` | Original concept |
| `docs/01 - Initial discussion - stage 1.md` | Prior art, datasets, full methodology, output contract |
| `docs/02 - Experiment - invented language control.md` | Experiment: why self-reported language support cannot be trusted |
| `docs/03 - Architecture and development stages.md` | Architecture, data model, cost model, staging, implementation log |

## Attribution

The shipped language catalogue is derived from:

- **ISO 639-3** code tables and macrolanguage mapping © SIL International, used under the ISO 639-3 terms of use.
- **SIL langtags** © SIL International — <https://ldml.api.sil.org/langtags.json>

## License

MIT for the code. Derived data retains the terms of its sources, above.
