# llm-language-checker

**An empirical, heuristic tool for finding out which languages an LLM can actually produce.**

Vendor language lists are marketing. "Supports 100+ languages" has no definition behind it, and for the long tail nobody publishes anything at all. This project measures it instead: you point it at a model, it generates text, checks the text, and reports a graded verdict with its evidence and its uncertainty.

> **Status: design phase.** The methodology is documented and partially validated by experiment (see `docs/`). The service itself is not yet implemented.

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
git clone <this repo>
cd llm-language-checker
cp .env.example .env      # add your OpenAI-compatible endpoint + key
docker compose up
# UI on http://localhost:8080
```

Target: minutes from clone to a working environment.

### Hardware

The stack detects available hardware at startup and selects a profile automatically:

| Detected | Back-translator | Coverage |
|---|---|---|
| GPU ≥ 6 GB VRAM | MADLAD-400-3B-MT, fp16 | ~400 languages |
| GPU 4–6 GB VRAM | MADLAD-400-3B-MT, int8 | ~400 languages |
| CPU only, or < 4 GB | NLLB-200-distilled-600M, or a remote API back-translator | ~200 languages, or as configured |

Language identification (GlotLID) runs on CPU everywhere and needs no GPU. Reference hardware for development: RTX 4060 Laptop (8 GB), 20 cores, 15 GB RAM.

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

## License

MIT.
