# llm-language-checker

**An empirical, heuristic tool for finding out which languages an LLM can actually produce.**

Vendor language lists are marketing. "Supports 100+ languages" has no definition behind it, and for the long tail nobody publishes anything at all. This project measures it instead: you point it at a model, it generates text, checks the text, and reports a graded verdict with its evidence and its uncertainty.

> **Status: early development.** The methodology is documented and partially validated by experiment (see `docs/`). The measurement pipeline, persistence and UI work end to end; dialect-level testing and the calibration study are still to come.

## What it is not

This is **not** a linguistic authority and **not** a benchmark leaderboard. It is an empirical probe with known limits:

- It measures **generation adequacy in a target language** — not chat quality, not instruction-following in that language, not cultural appropriateness. Those dissociate.
- Sample sizes are small. Results carry confidence intervals, and a result whose interval straddles the tier boundary is reported as `borderline`, never rounded.
- For languages with no aligned reference text, quality cannot be assessed at all. Those are reported `unverified` — which is an honest answer, not a failure.
- Results are only comparable within the same back-translator, judge, and method version. All three are recorded on every result.
- The **pivot language** — the language everything is back-translated into for judging — cannot be graded against itself, so it is measured through a fallback pivot and its results carry that pivot in the instrument id.

Anything it reports is evidence, not proof.

## Run it yourself

There is no hosted service and no public deployment. **You run it locally or in your own cloud**, with your own API keys in your own `.env`. Nothing is sent anywhere except to the model endpoints you configure, and no key is ever stored by the application or entered through a web form.

```bash
git clone https://github.com/a-fedosenko/llm-language-checker
cd llm-language-checker
cp .env.example .env      # add your OpenAI-compatible endpoint + key
docker compose up
```

- UI: <http://localhost:8000> — browse results, plan and start a scan, watch it run
- API and interactive docs: <http://localhost:8000/docs>

The published port is bound to `127.0.0.1`. There is no authentication, because there is no second user; widening `API_BIND` puts an unguarded tool on your network.

No network fetch is needed at setup — the language catalogue ships in the repo.

Results go to a local SQLite file — there is no database service to run:

```bash
pip install -e ".[dev]"
llmlc scan --engine <model> --tag de,fr,cv    # measure
llmlc status                                   # what is measured, what is stale
llmlc markers                                  # variant coverage, and the remaining gap
llmlc export --merge-into your-master.json     # mergeable artifact
uvicorn llmlc.api.main:app                     # UI on :8000
pytest
```

### Starting a scan from the browser

A scan spends your API budget, so the endpoint that starts one is gated by `SCAN_TRIGGER`:

| | |
|---|---|
| `off` | no trigger; scans stay a `llmlc scan` action |
| `loopback` | **default** — only callers on `127.0.0.1` / `::1`. Reaching it already means access to the machine holding your key |
| `any` | any client that can reach the port. Required in Docker, where the caller is always the bridge gateway — keep `API_BIND` on loopback if you set it |

Only the socket's peer address counts; `X-Forwarded-For` is ignored, because a header any client can set is not an access control. Behind a reverse proxy, use `off`.

A browser-started scan must state a call budget, and `SCAN_TRIGGER_MAX_CALLS` (default 2000) caps it. **Plan first** — the plan shows how many classes will actually be probed and costs nothing.

## Dialects and variants

A tag like `de-AT` inherits `de`'s tier, which says nothing about whether the model marks *that variant*. So each variant tag gets a verdict of its own:

| mechanism | applies to | how |
|---|---|---|
| **script** | marked script variants (`sr-Latn`, `kk-Latn`) | the probe's own script check — free |
| **markers** | country-only variants (`en-AU`) | a closed shibboleth set, compared against the sibling variant's |
| **declared** | variants that genuinely do not differ in everyday register (`ru-BY`) | an authored decision, with its reason |
| none | everything else | `untested` — a tracked gap, not a claim |

Marker sets live in `markers/*.json` and are a **growable asset**: ship none and every dialect inherits; add a file and those tags upgrade from inherited to proven. Scoring is comparative (`boot` hits, `trunk` misses) and an item where neither appears is **void**, because that means the prompt failed rather than the model. The markers are never named in the prompt — that would measure instruction-following — and the loader rejects a file that names them in its own elicitation contexts.

This measures **variant marking**, which is a proxy for dialectal competence and not the thing itself. The shipped lists are drafted and **not human-reviewed**; they say so in the file and everywhere they are displayed.

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
3. **A local deterministic eligibility filter.** Refusal, copying, wrong script, wrong language (GlotLID), confusion with a nearest high-resource relative, degenerate repetition, memorised boilerplate. Free, local, and it resolves most negatives before any paid call. It decides *membership* and then stops: a model that does not write the requested language or script is unusable for it, full stop, and nothing else about it is measured. This job is never handed to a language model — asked to verify a writing system and given the category by name, one flagged 0 of 15 real mismatches that this check caught.
4. **Fact-recall scoring.** Surviving output is back-translated by a fixed, independent back-translator; a blind judge then checks which of the specified facts survived. Grading happens entirely in the pivot language, so **the judge never needs to know the target language.** This number is the measurement, and it is published continuously.
5. **A routing tier, derived from the number.** `Unusable / Assisted / Proficient` — do not offer, MT-assist behind a mandatory human pass, or light review. Three values because a five-value scale was built, measured, and found not to exist: one of its tiers was never assigned in 40 results and another ranked below the bottom. The tier is a lossy convenience for a TMS that has to route on something; the score is the result. Each carries a confidence interval, an evidence class, and the full configuration that produced it.

The back-translator is validated per language against human reference text before it is trusted, so a failure of the instrument is never reported as a failure of the model.

## Output

Two artifacts. A minimal, mergeable file matching the consuming system's schema:

```json
{ "gsw-ch": { "mt.openai-gpt-4o": "Swiss German (Switzerland)" } }
```

and a separate full-evidence report carrying scores, intervals, designators tried, back-translator, judge, provenance, and timestamps. Merging is a per-key, per-engine upsert — a partial run can never wipe existing data.

## What lives where

The repository carries **code, authored data, and evidence**. Everything a run produces is regenerable and stays out of git.

| Path | Tracked | What it is |
|---|---|---|
| `schemes/default.json` | ✅ | The public language catalogue, so clone-to-run needs no network |
| `data/specs/specs.json` | ✅ | Content specifications — what the model is asked to describe |
| `data/controls/controls.json` | ✅ | Hand-written back-translator controls for languages FLORES lacks |
| `experiments/` | ✅ | Protocols and the raw responses behind them, so claims are checkable |
| `data/controls/flores.json` | ✗ | FLORES-derived controls — **CC BY-SA 4.0**, regenerate with `scripts/build_controls.py` |
| `data/llmlc.db` | ✗ | Your results. `llmlc scan` writes here |
| `data/results/`, `data/corpus/` | ✗ | Export artifacts and the raw generation corpus |
| `data/cache/`, `data/models/` | ✗ | Downloaded source tables and the GlotLID model |

A first run downloads FLORES-200 (~25 MB) and, for language identification, the GlotLID model (1.6 GB).

## Documentation

| | |
|---|---|
| `docs/Basic idea v0.md` | Original concept |
| `docs/01 - Initial discussion - stage 1.md` | Prior art, datasets, full methodology, output contract |
| `docs/02 - Experiment - invented language control.md` | Experiment: why self-reported language support cannot be trusted |
| `docs/03 - Architecture and development stages.md` | Architecture, data model, cost model, staging, implementation log |
| `experiments/protocols/` | One protocol per experiment: hypothesis, method, results, and what it changed |

## Attribution

The shipped language catalogue is derived from:

- **ISO 639-3** code tables and macrolanguage mapping © SIL International, used under the ISO 639-3 terms of use.
- **SIL langtags** © SIL International — <https://ldml.api.sil.org/langtags.json>

## License

MIT for the code. Derived data retains the terms of its sources, above.
