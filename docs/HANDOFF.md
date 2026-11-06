# Handoff — continue from here

Paste the block below into a new session. Everything else it needs is in the repo.

---

We are building **llm-language-checker**: a self-hosted, heuristic tool that measures which languages an LLM can actually produce, rather than which ones a vendor claims. It exists to populate per-locale engine support data for our TMS/CAT system (Catmint), and as a portfolio project. Not commercial.

**Read these first, in order** — they carry every decision and its reasoning:

- `docs/01 - Initial discussion - stage 1.md` — prior art, methodology, output contract, dialect/macrolanguage logic
- `docs/02 - Experiment - invented language control.md` — why self-reported language support cannot be trusted
- `docs/03 - Architecture and development stages.md` — architecture, data model, staging, implementation log. **Read "Services as built" before believing the five-service diagram above it**, which is the S0 plan and was never built
- `docs/04 - Methodology.md` — the reference page, written at S9: every pipeline step with the protocol that settled it, and a limitations section of the same length
- `experiments/protocols/README.md` — twenty protocols. **016 and 018 matter most**; then 019, 017, 005, 012. **020 is written but not run**, and gates the programme re-run

**State:** S0–S11 complete. 440 tests. **The operating scheme is now `catmint`**, the 602-tag TMS locale list — dialects named explicitly, script last and only where it discriminates. The public 9,589-tag catalogue stays on disk as what back-translator controls resolve against, and is withheld from the UI picker whenever a real locale list exists beside it. Method version **3.0.0** — and **every one of the 1,564 stored rows is stale**, because 3.0.0 changed the generation prompt. Nothing in the UI reflects the current method. Re-running the four-engine programme is ~14,200 calls, and two decisions below should be settled first.

---

# Next session: the dialect problem

This is what the session is for. Everything else below is background.

**The complaint, in the owner's words:** the scan method "is not precise at all as it ignores regional differences."

That is correct as stated, and the cause is one line of the data model: the equivalence class is **`iso639_3|script`**. A scan probes one tag per class and the rest inherit, so `srp|Cyrl` holds `sr`, `sr-BA`, `sr-Cyrl-ME`, `sr-XK` and is probed **once — through bare `sr`, which carries no region**. The class collapse is what makes 602 locales cost 363 experiments; it is also what makes the scan dialect-blind. The thing that makes it affordable is the thing that makes it imprecise.

## The numbers to think with

| | |
|---|---|
| TMS list | 602 tags, 363 classes, **239 inherit** rather than being probed — **227 of those differ only by region** |
| public catalogue | 9,589 tags, 9,055 classes, 534 inherit, all 534 by region |
| marker sets authored | **7 of 534** variant tags — en-AU, en-GB, and the Serbian sets (ru-BY is a declared non-difference) |
| full ladder run | ~9–15 calls per class |
| marker probe | **4 calls** per variant tag |

## The reframe worth testing before redesigning anything

S6 already split this into **two measurements**, and they are not the same question:

- the **ladder**, per class — *can the model write this language at all*
- the **marker probe**, per variant tag — *does it mark this region*

So "measure every region" need not mean running the ladder 227 more times (~2,050 calls/engine). It can mean ladder-per-class plus a 4-call marker probe per variant (~910 calls/engine), which is less than half the cost **and measures the right thing** — re-running the ladder for `sr-ME` would mostly re-measure whether the model writes Serbian, which is already known.

On that reading the architecture is right and the gap is **authoring throughput**: 7 marker sets exist because each one needs somebody who reads the language. Serbian took an afternoon and is still `reviewed: false`.

**The counter-case, which may be decisive.** A model's *base capability* could differ by region — fluent `ar-EG`, poor `ar-MA` — and no marker set would catch that, because markers measure marking, not adequacy. If that happens, the class collapse really is wrong and the 65% is justified. **It is cheap to test on one language before deciding for all of them**: run the ladder directly on two regional tags of one macrolanguage and compare adequacy, not markers.

## What is already built that bears on it

- **Method 3.0.0 puts the region in the prompt** — `Serbian (Montenegro, Cyrillic script)`, in a system message casting the model as a speaker of that variety. Verified to change the output: `дете` against `дијете`. **But it is inert in a scan**, because the class representative has no region. It only fires where a tag is probed directly, which is what the bench does.
- **`variant_evidence` has four states** (proven / proven-failed / not-distinguishable / untested) so the remaining work stays countable.
- **The marker instrument grew three things** while authoring Serbian, all in `probe/markers.py`: **stem markers** (`пјешач-`) because the inflection list was English-only and any Slavic set silently scored near zero; **worked examples checked at load time**, which is the only guard available to an author who cannot read the language, and which caught a real error on the first draft; and **`also`**, so one set serves every spelling of a language.
- **`markers/serbian.json`** — 58 index-aligned pairs on the yat reflex, Cyrillic and Latin. Cyrillic works end to end (`proven`, rate 1.00). **Latin cannot be probed**: see the carried-forward item below.

## The two decisions this blocks

1. **Split equivalence classes by region?** +239 probes on the TMS list, ~+2,150 calls per engine, **~65% more per scan**. Do not re-run the programme before settling it, or it gets run twice.
2. **Protocol 020's H2** (`experiments/protocols/020-region-aware-prompts.md`) — whether method 3.0.0's system/user split moves the verdict on languages with no regional variant. Still open, still unrun, and still what gates the 14,200-call re-run. Its H1 and H3 were superseded by [021](../experiments/protocols/021-attestation-without-a-marker-corpus.md), which answers them with blind identification rather than chrF++ between two generations.

---


**Four engines are measured across 199 languages** (2026-09-29/30, jobs 10–13, ~8,900 calls). That is every living language for which a back-translator control exists — see *Coverage* below, because the number is a constraint, not a choice.

| engine | Proficient | Assisted | Unusable | unverified | langs w/ refusals | reader |
|---|---|---|---|---|---|---|
| **deepseek-v4-pro** | **130** | 59 | 8 | 2 | **0** | gemini-3-6-flash |
| gemini-3-8-flash | 114 | 68 | 2 | 15 | 3 | deepseek-v4-flash* |
| openai-gpt-4o | 105 | 35 | 58 | 1 | 75 | gemini-3-6-flash |
| groq-qwen3-8-27b | 66 | 71 | 62 | 0 | 75 | gemini-3-6-flash |

*a different reader, so not directly comparable with the other three. It is the weaker one, which biases against gemini — its 15 `unverified`, the highest of the four, is that handicap surfacing as "could not measure" rather than as lower tiers.*

`Unusable` and `unverified` are split here and nowhere else: the DB stores both as tier `Unusable` (because `no-control` is never a pass) and `llmlc status` reports the combined figure. Any table quoting one Unusable count is conflating *proven unusable* with *not measurable*.

On the three that share a reader: **deepseek is strictly best on 64 languages** (gpt-4o on 6), and **41 languages only deepseek can do at all**. 129 of 199 all three handle; 10 none of them can.

**The dominant effect is willingness, not ability.** deepseek refused nothing across 199 languages; gpt-4o answered `CANNOT` on 200 of 725 attempts. Protocol 011's insistence on keeping availability as a second axis is what makes that readable — a single scale would have reported it as "gpt-4o cannot write these languages," which the data does not support.

**Run it:**
```bash
cp .env.example .env               # settings; gitignored
cp .models.json.example data/models.json   # per-model endpoint + key; gitignored
                                   # (AGGREGATOR_BASE_URL still works and is what
                                   #  jobs 1-17 were measured through)
docker compose up -d               # UI at http://localhost:${API_PORT:-8000}   (8089 on Andrei's machine)
llmlc bootstrap --check            # is the instrument complete? (GlotLID + FLORES controls)
llmlc status                       # what is measured, what is stale
llmlc markers                      # variant coverage and the remaining gap
python -m pytest -q                # note: bare `pytest` misses the rootdir
python scripts/run_programme.py --base http://localhost:8089   # the cross-engine programme, over HTTP
```

The UI has seven tabs: **Support** (the default: one model, every locale, five statuses), **Bench** (the pipeline over one language, step by step), **Results** (paged, faceted, a row expands to its items and evidence), **Resolution** (what each tag actually got you), **Variants** (dialect evidence and the marker gap), **Scan** (plan for free, then start one), **Jobs** (per-class progress, cancel, history). Every block title and column heading carries an info icon defining the term; those definitions live in a single `HELP` dictionary in `index.html`.

Schema changes are Alembic's. A database made by `create_all()` has no version row, so migrating one for the first time needs `alembic stamp fb431915efe4 && alembic upgrade head`.

**Conventions that are not obvious from the code:**

1. **Every experiment gets a protocol** in `experiments/protocols/`, following `TEMPLATE.md`, with the hypothesis written down *before* the run. Invalidated results are kept with `Status: invalidated`, not deleted. This has paid for itself repeatedly: 002 withdrew a conclusion from 001, 016 overturned 014's headline, 018 withdrew a correlation from 017, and 019 found its own trigger was overstated tenfold.
2. **Reasoning must be off** for every measurement call. Vendor defaults differ and that confound already invalidated one conclusion (protocol 002). `reasoning_effort: "none"`, with per-model fallback — gpt-4o rejects the parameter outright.
3. **SQLite only, and one container.** No Postgres, no `worker`/`lid`/`bt`/`ui` service. WAL is enabled so the CLI can write on the host while the UI reads through the bind-mounted file.
4. **Results are only comparable within the same back-translator, judge and method version.** Part of the uniqueness constraint, and not a formality: the same engine measured through two qualified readers **disagreed on tier for 13% of 136 languages**, with a mean content delta of 0.000 — unbiased on average, noisy per language.
5. **`no-control` is never a pass.** Where the back-translator cannot be qualified for a language, the result is `unverified` with the reason named.
6. Before claiming a finding, **read the raw evidence**. Nearly every real bug this project found came from looking at output rather than from tests — two marker defects, a duplicate-row bug, and protocol 018's first table, which had Swahili at chrF++ 79.8 sitting in the "did not write Swahili" bucket.
7. **Tier is capability; availability is willingness** (protocol 011). Refusals are excluded from `s_lang` and reported separately. The workflow sentence carries the caveat; the tier does not move.
8. **The content score is the measurement; the tier is a lossy view of it** (protocol 018). Quote the number. Three tiers exist because a TMS must route on something, and they cost 0.04 of Spearman against the number they come from — the five they replaced cost about a third. Eligibility is a filter, not the first term of a grade: wrong script or wrong language means `Unusable`, full stop, and that check is never handed to a model (016: 15/15 against 0/15).
9. **An analysis harness calls the production function; it never re-implements it** (protocol 018). `calibrate.py` called the gate without `accept_lang`, convicting every macrolanguage of writing the wrong language. 68 of 385 verdicts were wrong and protocol 017 drew a conclusion from them. The drift arrives looking like a finding.
10. **When the instrument is missing, say so — never quietly answer worse.** Third time this has come up (005, 019, S8). A scan without GlotLID runs fine and silently loses its language check; `llmlc bootstrap` and the UI readiness banner exist so that is stated, not discovered.
11. **`runner.py` is the only definition of "run a scan".** The CLI and the HTTP trigger differ in how they report progress and who may call them, nothing else.
12. **Inheriting a tier is not inheriting a claim** (S6). A variant tag gets its own `variant_evidence` by script, markers, an authored `not-distinguishable`, or `untested`. The last two are different on purpose.
13. **The pivot language is measured through a different pivot** (protocol 013). `en` falls through to `de`, then `fr`, then `es`. The pivot rides in the back-translator id (`remote:model@de`).
14. **A deterministic negative has no instrument.** It stores `NO_INSTRUMENT` (`"(not needed)"`), so it is comparable to *every* back-translator rather than none, and `repo.upsert_result` collapses it onto one row. This is why re-running an engine through a new reader adds rows rather than replacing them, and why the 58 deterministic negatives were not duplicated.
15. **Where a defect would be invisible in the output, the guard goes in the loader** (protocol 012). Marker scoring is string matching, so a wrong marker yields a plausible number with nothing to flag it.

**The back-translator panel is fixed, and its members must stay outside the scan set** (S8, doc 03). `gemini-gemini-3-6-flash, deepseek-deepseek-v4-flash`, in that order; the guard drops the engine's whole *family*, not just its id. A model that is both under test and in the panel gets dropped from its own panel and is then measured through a different instrument from every other engine, which invalidates the cross-engine comparison by convention 4. Order is measured, not alphabetical: `route()` takes the first member that qualifies, and gemini-3-6-flash is the stronger reader at the hard end (ug 59.3 vs 40.3, am 62.8 vs 48.5).

**Run the server in Docker, never on the host.** `docker compose up -d`, not `uvicorn` in a terminal — containment. `API_PORT` and `API_BIND` in `.env`; the default bind is loopback and should stay that way, because the UI has no authentication and the port binding is the only control. **The image bakes `src/` in with `COPY` and bind-mounts only `./data`, so after any code change you must `docker compose build --no-cache api`** — otherwise the UI serves old code over current data, which is how an 11-day-old image came to render method-2.0.0 results through a five-tier vocabulary that no longer existed.

**On the scan trigger.** `POST /scans` is gated by `SCAN_TRIGGER=off|loopback|any`. Compose defaults to `any`, which is not a loosening: inside a container the peer is always the bridge gateway, so `loopback` can never match and the UI's scan button would 403 for everyone. The control there is the port binding. Only the socket peer address counts — a forged `X-Forwarded-For` is tested to fail. A browser-started scan must name `max_calls`, capped by `SCAN_TRIGGER_MAX_CALLS` (5000; a full 199-class scan costs ~2,400). One scan at a time; a second gets `409`.

---

## Coverage: why 199 and not 602

```
Catmint locale list (languages/, gitignored)   602
shipped public catalogue                     9,589
living languages                             8,607
living WITH a back-translator control          199   <- what is measured
living WITHOUT a control                     8,408
```

**199 is not a choice, it is the control ceiling.** A control is parallel text in the target language whose English meaning we already know; it is how a back-translator is certified before being trusted, because a model that cannot read a language does not refuse — it invents (protocol 005 caught gpt-4o rendering known Chuvash as *"A man is walking. He is wearing a white shirt."*). FLORES-200 supplies ~200 of them; three more are hand-seeded (`cv`, `de`, `ru`).

Beyond that set nobody can be qualified, so the honest output is `unverified`. **But the deterministic gate needs no control at all**, so negatives stay free and sound at full breadth. The shape is: *we can prove inability without a reader; we cannot prove ability.*

## Done since the last handoff

**The Catmint locale scan** (jobs 14–17, 154 locales × 4 engines) and the control-gap ranking in `data/results/control_gap.json`: the high-value slice is **27 locales, not 120**. Written up in doc 03. It also exposed a control-lookup bug — `ko` carries script `Kore`, the control text carries `Hang` — now fixed so a control answers for a script-*compatible* spelling and only that.

**S9 — README and methodology.** `docs/04 - Methodology.md` is new; the README gained a *What it found* section, the coverage ceiling, a *What a result does not mean* list, and three factual corrections (stale status block, `SCAN_TRIGGER` documented as the library default rather than what compose sets, `SCAN_TRIGGER_MAX_CALLS` as 2000 against an actual 5000).

## Next step

**1. A protocol on the `Assisted`/`Proficient` cut.** 13% of tiers flip when a qualified reader is swapped, and five `Assisted` languages scored content 0.00 while being routed as "MT-assist, mandatory human pass" — fluent text, no meaning. Protocol 018 measured cuts at 0.50/0.70/0.85 as non-monotonic, so 0.95 was the only monotonic option; the live runs are better evidence than that simulation. This decides whether three tiers are honest or two.

**2. S10 — public landing page.** Andrei's portfolio piece; should publish browsable results, not just describe the method. Doc 04 is the text it can be built from.

**3. Rebuild the image and clear the stale rows.** The running container is from an image four weeks old, so the UI is serving pre-Catmint, pre-`ko`-fix code over current data (`docker compose build --no-cache api`). `llmlc status` also reports 11 rows under an older method, and gpt-4o still carries 11 five-tier rows (`Strong`, `None`) from method 1.x.

## Needs Andrei, not the agent

- **Dialects — now the live question; see the section at the top.** Marker sets exist for **7 of 534 variant tags**: en-AU, en-GB, and Serbian ijekavian in both scripts. All `reviewed: false`, and **the Serbian ones want a speaker's eye** — they were drafted by someone who does not read the language, which is why the loader checks them against worked examples. The method is still untested where it would be most load-bearing (`ar-EG` against `ar-MA`), and whether marker probing is even the right instrument there is the open question.
- **Control texts** for the Catmint locales FLORES lacks. The gap is now ranked rather than guessed: `data/results/control_gap.json` names **27 locales attempted by three or more engines**, of which only `ko` turned out to be free from FLORES — so 26 texts, each buying three or four engines' worth of unknown. Same kind of job as the markers.
- **Whether to build the local GPU back-translator.** Not built; the GPU is unused; `hardware.detect()` now reports `profile: api` with `capable_of: gpu-int8` rather than claiming MADLAD read the text. The argument for finishing it is **reproducibility**, not cost — a vendor endpoint cannot be pinned, and a published dataset whose instrument has been retired cannot be re-graded. Detection logic survives behind `hardware.LOCAL_BACKTRANSLATOR`. Do not switch instruments mid-programme: convention 4 would strand every existing result.

## Open, carried forward

- **Serbian in Latin script cannot be marker-probed, and the reason is not a bug.** GlotLID reads ijekavian Serbian in Latin as Bosnian or Croatian — correctly, in that the three written standards overlap almost entirely in that script — so the gate returns `relative_substitution` and marker scoring never runs. The Latin marker set exists and validates against its examples; the Cyrillic one works end to end (`proven`, rate 1.00), because `srp_Cyrl` is identified cleanly. Whether `srp`/`bos`/`hrv`/`cnr` should satisfy one another *when the script is Latin* widens what counts as a pass, so it is a protocol and not a wider accept list. Same shape as the carried-forward `mag`-in-Bhojpuri item below.

- **Jobs 10–17 have no protocol.** The four-engine programme and the Catmint scan are written up in doc 03 and in `control_gap.json`, but neither has an entry in `experiments/protocols/`, and convention 1 says they should. Retroactive is the weak version of that rule; whatever runs next gets its hypothesis written first.

- **The UI shows 335 gpt-4o rows across two readers with no grouping.** The data model is right — two instruments, two rows — but a browser sees `de` twice and reads it as duplication. Add the back-translator as a facet before S10.
- **`calls_used` stays 0 while a job runs** and only updates at the end, so the programme driver's progress lines were useless. The Jobs tab uses a different source and is fine.
- **`tl` is convicted for answering in Filipino** — its standardised register, but a separate ISO code `accept_lang` does not reach. The scheme may hold other such pairs. And `mag` answered in Bhojpuri is labelled `wrong_language` where `relative_substitution` is the truth.
- **22 scripts, 27 tags, cannot be verified by any means** — Tengwar, Klingon, Indus, Mayan and eighteen others. The gate abstains rather than convicting, which is correct, but nothing tests it because there is no output to test against.
- **One test fails from a clean clone**: `test_shipped_controls_cover_flores_breadth_and_the_hand_seeded_gap` needs `data/controls/flores.json`, which `llmlc bootstrap` now builds. `tests/test_pivot.py` handles the same situation by skipping; that test should too.
- **The marker grammar axis never fires** — 0 hits in 28 generations. Rewrite its contexts to force *in hospital* / *different to*, or drop the axis rather than leave it as dead weight.
- **Back-translator panel order affects qualification cost** — a failing candidate costs 4 chrF++ calls before the next is tried.
- **Resuming a stopped job from the UI is not built.** `pending_items()` is the resume set and a stopped job keeps it intact; re-running is currently a fresh scan over the same tags.
- **`kk-Latn` deserves a second look with a different model**: asked properly, gpt-4o returns Latin script that GlotLID reads as Crimean Tatar and Turkmen. A recent official alphabet with little training text is a plausible genuine gap.

**S10 is done.** The **Support** tab is the default view: pick a model and a locale list, get one row per language with a five-value status (`supported` / `supported-via-dialect` / `unsupported` / `unverifiable` / `unchecked`), the adequacy number, and a confidence badge from the interval width. `llmlc/support.py` is the only definition of status; `api/support_table.py` owns the canonical-reader rule that collapses gpt-4o's five back-translators to one row per language, and says how many it collapsed. `scripts/build_scheme_from_tms.py` maps the 602-locale TMS list onto canonical tags (590 resolve) so the table runs down the real list — for deepseek that is 70 measured directly, 194 inherited, 46 unsupported, 132 unverifiable, 160 unchecked.

**Since S11, and not yet written up as a stage:** method 3.0.0 (region in the designator, system/user split, alphabet rule — see doc 03); a derived Latin control for Serbian via `bt/translit.py`, which closed `sr-Latn` and fixed a lookup that resolved a user's own tag against the wrong scheme; the marker-instrument additions (stem markers, load-time examples, `also`); the Serbian marker sets; bench session recovery after a page reload; and a back-translator panel chooser that shows every qualification attempt. All in the git log with reasoning.

**S11 is done.** The **Bench** tab runs the real pipeline over one language, step by step. The stage was a refactor before it was a page: `ladder_steps()` yields a `Step` after every action and returns the result, and `run_ladder()` is a *drain* over it — there is one traversal of the ladder, and `tests/test_ladder_steps.py` pins that stepping and draining reach the same score, designator, rung count, reader and call counts across five control-flow cases. Sessions live in memory (`api/bench.py`), capped at four, gated like `POST /scans`. Editing the hints marks the run `specs_modified` and keeps it out of `result` while still writing the corpus — verified live: an edited `ru` run finished Proficient, persisted nothing, and left all nine records on disk.

**Remaining stages:** S12 public landing page · S13 human-in-the-loop estimation. Both are behind the dialect question and the programme re-run. Planned together at the end of doc 03 — read that before starting either. S12 needs only what S10 and S11 already built; S13 was rescoped to a single operator (no sessions, no quotas, no auth) and its open question is whether the estimator supplies control text or a verdict.
