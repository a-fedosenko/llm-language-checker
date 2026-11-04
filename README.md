# llm-language-checker

**An empirical, heuristic tool for finding out which languages an LLM can actually produce.**

Vendor language lists are marketing. "Supports 100+ languages" has no definition behind it, and for the long tail nobody publishes anything at all. This project measures it instead: you point it at a model, it generates text, checks the text, and reports a graded verdict with its evidence and its uncertainty.

> **Status: working, and used.** The pipeline, persistence and UI run end to end; the method is validated by nineteen recorded experiments (`experiments/protocols/`); four models have been measured across 199 languages. What remains thin is dialects — marker sets exist for 7 of 534 variant tags, and whether the measurement is even shaped right for regional variants is an open question (`docs/HANDOFF.md`). **The published figures are method 2.0.0**; 3.0.0 changed the generation prompt and nothing has been re-measured under it yet. **[Read the methodology](docs/04%20-%20Methodology.md)** for how a result is produced and, at equal length, what it does not mean.

## What it is not

This is **not** a linguistic authority and **not** a benchmark leaderboard. It is an empirical probe with known limits:

- It measures **generation adequacy in a target language** — not chat quality, not instruction-following in that language, not cultural appropriateness. Those dissociate.
- Sample sizes are small. Results carry confidence intervals, and a result whose interval straddles the tier boundary is reported as `borderline`, never rounded.
- For languages with no aligned reference text, quality cannot be assessed at all. Those are reported `unverified` — which is an honest answer, not a failure.
- Results are only comparable within the same back-translator, judge, and method version. All three are recorded on every result.
- The **pivot language** — the language everything is back-translated into for judging — cannot be graded against itself, so it is measured through a fallback pivot and its results carry that pivot in the instrument id.

Anything it reports is evidence, not proof.

## What it found

Four models, 199 languages each, 2026-09-29/30, ~8,900 model calls. 199 is every living language for which a back-translator can be certified — see *Coverage* below, where that number comes from.

| engine | Proficient | Assisted | Unusable | unverified | languages with refusals | read through |
|---|---|---|---|---|---|---|
| **deepseek-v4-pro** | **130** | 59 | 8 | 2 | **0** | gemini-3-6-flash |
| gemini-3-8-flash | 114 | 68 | 2 | 15 | 3 | deepseek-v4-flash\* |
| openai-gpt-4o | 105 | 35 | 58 | 1 | 75 | gemini-3-6-flash |
| groq-qwen3-8-27b | 66 | 71 | 62 | 0 | 75 | gemini-3-6-flash |

\*A different reader, so this row is not directly comparable with the other three — results are only comparable within one back-translator. It is also the weaker reader, which biases *against* gemini: its 15 `unverified`, the highest of the four, is that handicap surfacing as "could not measure" rather than as lower tiers.

On the three that share a reader: **deepseek is strictly best on 64 languages** (gpt-4o on 6), **41 languages only deepseek can write at all**, 129 of 199 all three handle, and 10 none of them can.

**The dominant effect is willingness, not ability.** deepseek refused nothing across 199 languages; gpt-4o answered `CANNOT` 200 times. Keeping availability as an axis separate from capability is what makes that readable — on a single scale it would have been reported as "gpt-4o cannot write these languages," which the evidence does not support.

Treat a single row as noisier than the aggregate. The same engine measured through two qualified readers disagreed on tier for 13% of 136 languages, with a mean content delta of 0.000 — unbiased on average, noisy per language.

A second scan put 154 locales from a real TMS locale list through the same pipeline. Every one of the four engines came back with 151 of 154 `Unusable`, and `data/results/control_gap.json` ranks the resulting gap by how much a control text would actually buy: of 120 locales where at least one engine wrote something unverifiable, only **27 were attempted by three or more engines**. A locale every engine refused is already closed and needs no control.

## Run it yourself

There is no hosted service and no public deployment. **You run it locally or in your own cloud**, with your own API keys in your own files. Nothing is sent anywhere except to the model endpoints you configure, and no key is ever stored by the application, written to a result, or entered through a web form.

```bash
git clone https://github.com/a-fedosenko/llm-language-checker
cd llm-language-checker
cp .env.example .env                        # settings
cp .models.json.example data/models.json    # your models, endpoints and keys
docker compose up -d
```

### Telling it about your models

Each model gets its own endpoint and its own key, so a single scan can reach OpenAI, a hosted gateway and a local vLLM at once:

```json
{
  "models": [
    { "model_title": "GPT-4o",        "model_id": "gpt-4o",
      "api_key": "sk-...",            "v1_endpoint": "https://api.openai.com/v1" },
    { "model_title": "Local Qwen",    "model_id": "Qwen/Qwen2.5-72B-Instruct",
      "api_key": "not-needed",        "v1_endpoint": "http://localhost:8001/v1" }
  ]
}
```

`CUSTOM_MODEL_LIST_PATH` in `.env` points at that file. Keep it under `./data` — that is the directory compose mounts into the container, so a path anywhere else resolves on the host and vanishes in Docker.

`model_id` is the identity: it goes in the request body, names `--engine`, and is stored on every result row. `model_title` is display only and safe to rename.

A scan needs three models reachable — **the engine under test, the judge, and at least one back-translator from the panel** — and the shipped defaults for the last two are this project's own ids, which will not be in your file. Add them or point `JUDGE_MODEL` and `--backtranslator` at models you have; either way the tool checks all three and names what is missing *before* it spends anything.

<details><summary>The older single-gateway route still works</summary>

Set `AGGREGATOR_BASE_URL` and `AGGREGATOR_ADMIN_API_KEY` instead, and every model id is requested from that one endpoint with that one key. This is how the measurements in *What it found* were taken. Where both are configured, the JSON file wins.

</details>

- UI: <http://localhost:8000> — **Support** (one model, every locale, five statuses), **Demo** (the method over one language, a step at a time), plus results, variants, and planning and running a scan
- API and interactive docs: <http://localhost:8000/docs>

**Before your first scan, fetch the two files the repository cannot ship.** The UI says so on arrival and offers a button; `llmlc bootstrap` does the same from a terminal, and `AUTO_BOOTSTRAP=1` does it at startup.

| | why it is not committed | without it |
|---|---|---|
| GlotLID, ~1.6 GB | too large for a repository | the gate checks script but not **language** — a model answering in Indonesian when asked for Acehnese would pass |
| FLORES-200 controls, ~25 MB download | CC BY-SA 4.0; share-alike attaches to derived text | only `cv`, `de`, `ru` can have a back-translator qualified, so nearly every language reports `unverified` |

Browsing existing results needs neither. Scanning needs both, and the tool will tell you rather than quietly measuring less than it reports.

The published port is bound to `127.0.0.1`. There is no authentication, because there is no second user; widening `API_BIND` puts an unguarded tool on your network.

**This is a single-operator tool and is not built to be exposed publicly.** There are no accounts, no per-caller quotas and no abuse handling, and the endpoints that spend your API budget are guarded by the port binding alone. If you want to put it on the internet — to collect contributions from speakers, say — that is a fork with its own SSO, rate limiting and moderation, not a setting.

The language catalogue ships in the repo, so browsing needs no network fetch. Scanning needs the two assets above.

Results go to a local SQLite file — there is no database service to run:

```bash
pip install -e ".[dev]"
llmlc scan --engine <model> --tag de,fr,cv    # measure
llmlc status                                   # what is measured, what is stale
llmlc markers                                  # variant coverage, and the remaining gap
llmlc export --merge-into your-master.json     # mergeable artifact
llmlc bootstrap --check                        # is the instrument complete?
python -m pytest
```

### Starting a scan from the browser

A scan spends your API budget, so the endpoint that starts one is gated by `SCAN_TRIGGER`:

| | |
|---|---|
| `off` | no trigger; scans stay a `llmlc scan` action |
| `loopback` | the library default — only callers on `127.0.0.1` / `::1`. Reaching it already means access to the machine holding your key |
| `any` | **what compose sets** — any client that can reach the port. Required in Docker, where the caller is always the bridge gateway, so `loopback` could never match and the UI's own scan button would 403 for everyone. Not a loosening: the control there is the port binding, published on `127.0.0.1` |

Only the socket's peer address counts; `X-Forwarded-For` is ignored, because a header any client can set is not an access control. Behind a reverse proxy, use `off`.

A browser-started scan must state a call budget, and `SCAN_TRIGGER_MAX_CALLS` (default 5000) caps it; a full 199-language scan costs about 2,400. One scan at a time — a second gets `409`, because SQLite takes one writer and two scans would spend against a budget neither of them set. **Plan first** — the plan shows how many classes will actually be probed and costs nothing.

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
- Drop your own list in `schemes/<name>.json` and set `SCHEME=<name>`, or pick it from the Support tab. Your list is gitignored; results come back keyed to your tags.
- Exporting from a TMS whose tags are not canonical? `python scripts/build_scheme_from_tms.py <export.json> --name mine` maps them. On a real 602-locale list it resolves 590 — by tag, then through the ISO 639-3 macrolanguage mapping — and **names the ones it could not**, rather than guessing. A locale it leaves unresolved is still scannable; one it resolved wrongly would be a false claim, which is why the looser rules it tried first were removed (they put Standard Malay under Malay Braille).
- Regenerate the shipped catalogue with `python scripts/build_default_scheme.py --refresh`.

### Hardware

**No GPU is required, and none is currently used.** Everything runs on CPU: language identification is GlotLID, which is CPU-only, and back-translation goes to a remote model qualified per language against human reference text.

`GET /hardware` reports two different things, and the difference matters:

| field | means |
|---|---|
| `profile` | what actually read the text. **`api`** — a remote back-translator — unless you override it |
| `capable_of` | what this machine *would* run if a local back-translator existed: `gpu-fp16`, `gpu-int8` or `cpu` by VRAM |

`profile` is recorded on every result, because results produced by different back-translators are not comparable. `capable_of` is not; it describes the box, not the measurement.

A local back-translator — MADLAD-400-3B on GPU, NLLB-200 on CPU, covering ~400 languages without a network call — was designed and never built. The detection logic for it survives, tested, behind one constant in `llmlc/hardware.py`. The reason to finish it is reproducibility rather than cost: a vendor endpoint cannot be pinned, and a published dataset whose instrument has been retired cannot be re-graded. See *Services as built* in `docs/03`.

Override with `HARDWARE_PROFILE` in `.env`.

## How it works

Briefly. **[docs/04 — Methodology](docs/04%20-%20Methodology.md)** is the full version: every step with the experiment that settled it, and a limitations section of the same length.

1. **Content-controlled generation.** The model is given a *semantic specification* in a pivot language and asked to write in the target language, choosing its own words. Not a sentence to translate (which rewards copying and punishes paraphrase) and not free writing (which lets the model fall back on memorised text).
2. **Designator selection.** An LLM has no language-code interface — whatever string you pass is just tokens in a prompt. Several candidate designators are tried and the best-performing one is kept, so a negative verdict means "under our best designator," never "under one arbitrary string."
3. **A local deterministic eligibility filter.** Refusal, copying, wrong script, wrong language (GlotLID), confusion with a nearest high-resource relative, degenerate repetition, memorised boilerplate. Free, local, and it resolves most negatives before any paid call. It decides *membership* and then stops: a model that does not write the requested language or script is unusable for it, full stop, and nothing else about it is measured. This job is never handed to a language model — asked to verify a writing system and given the category by name, one flagged 0 of 15 real mismatches that this check caught.
4. **Fact-recall scoring.** Surviving output is back-translated by a fixed, independent back-translator; a blind judge then checks which of the specified facts survived. Grading happens entirely in the pivot language, so **the judge never needs to know the target language.** This number is the measurement, and it is published continuously.
5. **A routing tier, derived from the number.** `Unusable / Assisted / Proficient` — do not offer, MT-assist behind a mandatory human pass, or light review. Three values because a five-value scale was built, measured, and found not to exist: one of its tiers was never assigned in 40 results and another ranked below the bottom. The tier is a lossy convenience for a TMS that has to route on something; the score is the result. Each carries a confidence interval, an evidence class, and the full configuration that produced it.

The back-translator is validated per language against human reference text before it is trusted, so a failure of the instrument is never reported as a failure of the model. A model that cannot read a language does not refuse — it invents: one handed known Chuvash returned *"A man is walking. He is wearing a white shirt."*

### Coverage: why 199 languages and not 9,589

```
shipped public catalogue                     9,589 tags
living languages                             8,607
living WITH a back-translator control          199   <- what can be graded
living WITHOUT a control                     8,408
```

**199 is not a choice, it is the control ceiling.** Grading needs a certified reader; certifying one needs parallel text in that language whose meaning is already known; that text exists for about two hundred languages. Beyond them nobody can be qualified and the honest output is `unverified`.

But **the deterministic gate needs no control at all**, so negatives stay sound at full catalogue breadth. The shape of the method is: *inability can be proven without a reader; ability cannot.*

### What a result does not mean

The short version of [the methodology's limitations section](docs/04%20-%20Methodology.md#8-limitations), which is the part worth reading before quoting a number:

- **Three items per language**, six for borderline ones. 28% of graded rows in the four-engine programme are flagged `borderline` — their interval spans the tier cut.
- **`Assisted` is a wide band**, spanning fact recall from 0.00 to 0.93. Five languages scored exactly 0.00 — fluent text in the right language carrying none of the requested meaning — and route identically to one scoring 0.90.
- **Swapping a qualified reader moves 13% of tiers**, at a mean content delta of 0.000. Unbiased on average, noisy per language.
- **Fact recall saturates**: 84% of items score 1.0, so above the floor it has little resolution.
- **Dialects are the least proven claim** — marker sets exist for 7 of 534 variant tags, all unreviewed, and a scan still probes one tag per `language|script` class, so regional variants inherit rather than being measured.
- **Three sentences is the whole sample.** Nothing here speaks to document-length behaviour.

## Watching it work

The **Demo** tab runs the real pipeline over one language and shows every step: the generated text, the gate's verdict and what GlotLID made of it, the back-translation, which facts survived, and the score it adds up to. Automatic mode runs it through; interactive mode waits between steps and tells you what the next one will do *before* you pay for the call.

There is no demonstration copy of the method. The page advances the same generator a scan drains, so the two cannot drift apart — which is the only way a demo is worth anything.

You can rewrite the scenario and its fact checklist in interactive mode, to see what the model does with content of your own. **An edited run is not saved**: results are comparable only within one method, and the shipped scenarios are mundane on purpose — a memorised encyclopedia opening cannot satisfy *"an old man bought fish and the price had doubled"*, and a rewrite can lose that without anyone noticing. The raw output still goes to the corpus, which is where you read it.

One language costs roughly 9–15 calls against your own key, so the endpoint that starts a session is gated exactly like the one that starts a scan.

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
| `data/results/control_gap.json` | ✅ | Which locales a new control text would actually buy something for |
| `.models.json.example` | ✅ | The shape of the model list — copy it, do not edit it in place |
| `data/models.json` | ✗ | **Your models, endpoints and keys.** Gitignored, like `.env` |
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
| `docs/04 - Methodology.md` | **The reference page** — how a result is produced, what each number means, and what it does not mean |
| `experiments/protocols/` | One protocol per experiment: hypothesis, method, results, and what it changed |

## Attribution

Results are derived from:

- **FLORES-200** © Meta AI, CC BY-SA 4.0 — <https://github.com/facebookresearch/flores>. Share-alike attaches to derived text, which is why the controls built from it are not committed.

The shipped language catalogue is derived from:

- **ISO 639-3** code tables and macrolanguage mapping © SIL International, used under the ISO 639-3 terms of use.
- **SIL langtags** © SIL International — <https://ldml.api.sil.org/langtags.json>

## License

MIT for the code. Derived data retains the terms of its sources, above.
