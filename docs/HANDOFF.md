# Handoff — continue from here

Paste the block below into a new session. Everything else it needs is in the repo.

---

We are building **llm-language-checker**: a self-hosted, heuristic tool that measures which languages an LLM can actually produce, rather than which ones a vendor claims. It exists to populate per-locale engine support data for our TMS/CAT system (Catmint), and as a portfolio project. Not commercial.

**Read these first, in order** — they carry every decision and its reasoning:

- `docs/01 - Initial discussion - stage 1.md` — prior art, methodology, output contract, dialect/macrolanguage logic
- `docs/02 - Experiment - invented language control.md` — why self-reported language support cannot be trusted
- `docs/03 - Architecture and development stages.md` — architecture, data model, staging, implementation log. **Read "Services as built" before believing the five-service diagram above it**, which is the S0 plan and was never built
- `experiments/protocols/README.md` — nineteen protocols. **016 and 018 matter most**; then 019, 017, 005, 012

**State:** S0–S8 complete. 295 tests. Method version **2.0.0**; 932 result rows.

**Four engines are measured across 199 languages** (2026-09-29/30, jobs 10–13, ~8,900 calls). That is every living language for which a back-translator control exists — see *Coverage* below, because the number is a constraint, not a choice.

| engine | Proficient | Assisted | Unusable | langs w/ refusals | reader |
|---|---|---|---|---|---|
| **deepseek-v4-pro** | **130** | 59 | **10** | **0** | gemini-3-6-flash |
| gemini-3-8-flash | 114 | 68 | 17 | 3 | deepseek-v4-flash* |
| openai-gpt-4o | 105 | 35 | 59 | 75 | gemini-3-6-flash |
| groq-qwen3-8-27b | 66 | 71 | 62 | 75 | gemini-3-6-flash |

*a different reader, so not directly comparable with the other three. It is the weaker one, which biases against gemini — its 15 `unverified`, the highest of the four, is that handicap surfacing as "could not measure" rather than as lower tiers.*

On the three that share a reader: **deepseek is strictly best on 64 languages** (gpt-4o on 6), and **41 languages only deepseek can do at all**. 129 of 199 all three handle; 10 none of them can.

**The dominant effect is willingness, not ability.** deepseek refused nothing across 199 languages; gpt-4o answered `CANNOT` on 200 of 725 attempts. Protocol 011's insistence on keeping availability as a second axis is what makes that readable — a single scale would have reported it as "gpt-4o cannot write these languages," which the data does not support.

**Run it:**
```bash
cp .env.example .env               # aggregator endpoint + key; gitignored
docker compose up -d               # UI at http://localhost:${API_PORT:-8000}   (8089 on Andrei's machine)
llmlc bootstrap --check            # is the instrument complete? (GlotLID + FLORES controls)
llmlc status                       # what is measured, what is stale
llmlc markers                      # variant coverage and the remaining gap
python -m pytest -q                # note: bare `pytest` misses the rootdir
python scripts/run_programme.py --base http://localhost:8089   # the cross-engine programme, over HTTP
```

The UI has five tabs: **Results** (paged, faceted, a row expands to its items and evidence), **Resolution** (what each tag actually got you), **Variants** (dialect evidence and the marker gap), **Scan** (plan for free, then start one), **Jobs** (per-class progress, cancel, history). Every block title and column heading carries an info icon defining the term; those definitions live in a single `HELP` dictionary in `index.html`.

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

## Next step

**1. Scan the Catmint 602 through the gate.** `languages/languages.json` is on disk (gitignored). Every locale outside FLORES still gets a sound `Unusable` or an honest `unverified`, at gate cost only. This tells us how much of the real locale list is a problem *before* anyone commissions control texts. Start with `deepseek-v4-pro`, which came out broadest. Needs nothing from Andrei.

**2. S9 — README and methodology.** Worth writing now that there is a four-engine table to write around. Lead with the two strongest results: the invented-language control (doc 02) and 15/15 against 0/15 on script (protocol 016).

**3. A protocol on the `Assisted`/`Proficient` cut.** 13% of tiers flip when a qualified reader is swapped, and four `Assisted` languages scored content 0.00 while being routed as "MT-assist, mandatory human pass" — fluent text, no meaning. Protocol 018 measured cuts at 0.50/0.70/0.85 as non-monotonic, so 0.95 was the only monotonic option; the live runs are better evidence than that simulation. This decides whether three tiers are honest or two.

**4. S10 — public landing page.** Andrei's portfolio piece; should publish browsable results, not just describe the method.

## Needs Andrei, not the agent

- **Dialects.** Marker sets exist for **2 of 534 variant tags**, both English — which is also the pivot and the easiest possible case — and both `reviewed: false`. The method is untested where it would be load-bearing (`ar-EG` vs `ar-MA`). Drafting is model-plus-human-review, per doc 01. This is the most distinctive claim the tool makes and the least proven.
- **Control texts** for the Catmint locales FLORES lacks, if step 1 shows the gap is commercially real. Same kind of job.
- **Whether to build the local GPU back-translator.** Not built; the GPU is unused; `hardware.detect()` now reports `profile: api` with `capable_of: gpu-int8` rather than claiming MADLAD read the text. The argument for finishing it is **reproducibility**, not cost — a vendor endpoint cannot be pinned, and a published dataset whose instrument has been retired cannot be re-graded. Detection logic survives behind `hardware.LOCAL_BACKTRANSLATOR`. Do not switch instruments mid-programme: convention 4 would strand every existing result.

## Open, carried forward

- **The UI shows 335 gpt-4o rows across two readers with no grouping.** The data model is right — two instruments, two rows — but a browser sees `de` twice and reads it as duplication. Add the back-translator as a facet before S10.
- **`calls_used` stays 0 while a job runs** and only updates at the end, so the programme driver's progress lines were useless. The Jobs tab uses a different source and is fine.
- **`tl` is convicted for answering in Filipino** — its standardised register, but a separate ISO code `accept_lang` does not reach. The scheme may hold other such pairs. And `mag` answered in Bhojpuri is labelled `wrong_language` where `relative_substitution` is the truth.
- **22 scripts, 27 tags, cannot be verified by any means** — Tengwar, Klingon, Indus, Mayan and eighteen others. The gate abstains rather than convicting, which is correct, but nothing tests it because there is no output to test against.
- **One test fails from a clean clone**: `test_shipped_controls_cover_flores_breadth_and_the_hand_seeded_gap` needs `data/controls/flores.json`, which `llmlc bootstrap` now builds. `tests/test_pivot.py` handles the same situation by skipping; that test should too.
- **The marker grammar axis never fires** — 0 hits in 28 generations. Rewrite its contexts to force *in hospital* / *different to*, or drop the axis rather than leave it as dead weight.
- **Back-translator panel order affects qualification cost** — a failing candidate costs 4 chrF++ calls before the next is tried.
- **Resuming a stopped job from the UI is not built.** `pending_items()` is the resume set and a stopped job keeps it intact; re-running is currently a fresh scan over the same tags.
- **`kk-Latn` deserves a second look with a different model**: asked properly, gpt-4o returns Latin script that GlotLID reads as Crimean Tatar and Turkmen. A recent official alphabet with little training text is a plausible genuine gap.

**Remaining stages:** S9 README and methodology · S10 public landing page.
