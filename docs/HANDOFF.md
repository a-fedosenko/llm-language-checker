# Handoff — continue from here

Paste the block below into a new session. Everything else it needs is in the repo.

---

We are building **llm-language-checker**: a self-hosted, heuristic tool that measures which languages an LLM can actually produce, rather than which ones a vendor claims. It exists to populate per-locale engine support data for our TMS/CAT system (Catmint), and as a portfolio project. Not commercial.

**Read these first, in order** — they carry every decision and its reasoning:

- `docs/01 - Initial discussion - stage 1.md` — prior art, methodology, output contract, dialect/macrolanguage logic
- `docs/02 - Experiment - invented language control.md` — why self-reported language support cannot be trusted
- `docs/03 - Architecture and development stages.md` — architecture, data model, staging, implementation log. **Read "Services as built" before believing the five-service diagram above it**, which is the S0 plan and was never built
- `docs/04 - Methodology.md` — the reference page, written at S9: every pipeline step with the protocol that settled it, and a limitations section of the same length
- `experiments/protocols/README.md` — twenty-one protocols. **016 and 018 matter most**; then 019, 017, 005, 012. **021 is the live one** (dialect attestation, hypotheses recorded); 020's H1/H3 are superseded by it and **020's H2 is still open and still gates the programme re-run**

**State:** S0–S11 complete, S12.5 in progress (dialect attestation: parts 0–5 of 6 done — primitives, probes, panel and controls, verdict ladder and persistence, and the bench with its page; only the programme run remains). 620 tests. The battery is **smoke-tested live**: `sr-me-cyrl` came back `full-command` and `ru-kz` `no-evidence`, which is both calibration ends behaving — see protocol 021's Results. Schema head is **d7b2c0a94e13** (the `capability` table, append-only with a current flag). **The operating scheme is now `catmint`**, the 602-tag TMS locale list — dialects named explicitly, script last and only where it discriminates. The public 9,589-tag catalogue stays on disk as what back-translator controls resolve against, and is withheld from the UI picker whenever a real locale list exists beside it. Method version **3.0.0** — and **every one of the 1,564 stored rows is stale**, because 3.0.0 changed the generation prompt. Nothing in the UI reflects the current method. Re-running the four-engine programme is ~14,200 calls, and two decisions below should be settled first.

---

# Next session: review and refactor the Bench

**The dialect method is built and works. The page that drives it does not read well, and that is the job.**

S12.5 parts 0–5 are done and committed, protocol 021 is written with its hypotheses recorded, and the battery has been smoke-tested against live models at both calibration ends. What has *not* had a single considered pass is the Bench UI: it grew by accretion across a dozen small corrections, each one sound on its own, and the result is a page its own owner called "messy and not really understandable". Treat it as a redesign, not a bug list.

## What is wrong with it, concretely

- **It serves two different probes through one form**, and the fields that belong to each are distinguished only by being hidden. Seven controls either way, in a grid that reflows.
- **The step cards carry too much and say too little.** `renderStep` has a ladder path and a dialect path with different detail keys, and the dialect one dumps a dozen `<dl>` rows that a reader has to triage.
- **The end of a run accumulated three stacked notes** — verdict, comparison, "what this left behind" — each added to answer a question the previous version raised.
- **Four distinct notes can be on screen at once** (`#d-note`, `#d-open`, `#d-stored`, `#d-plan`) before a run even starts.

**A defect pattern worth knowing before you edit `index.html`.** Two CSS blocks were added by unguarded `str.replace` calls that silently matched nothing, so the facts table and the picker lists rendered unstyled for several commits without anyone noticing. **Every edit to that file must assert its anchor matched.** Relatedly, `.grid { display: grid }` beat the UA stylesheet's `[hidden] { display: none }`, so hidden containers stayed on screen — now fixed once with `[hidden] { display: none !important }`, but the class of bug is worth remembering.

## What is built, and how it hangs together

The method is five probes over two halves. **P3 conversion and P4 self-consistency need no attestor at all** — they are the dialect equivalent of the deterministic negative, and they run first so a negative can be settled without a panel call. **P1 blind identification and P2 contrast** are the paid half. **P5 marker grounding** is not a call: `attest.identify` and `attest.separate` ground their own results and `dialect.grounding` tallies them.

| file | what it owns |
|---|---|
| `probe/attest.py` | the primitives, and **the blinding** — the expected answer is not a parameter of `identify`, so it cannot reach a prompt. `Blind` carries what an attestor may see and nothing else |
| `probe/dialect.py` | the five probes, the verdict aggregation, `attest_steps` and its drain `run_attestation` |
| `probe/panel.py` | the two manufactured controls, the family guard, `CapabilityRecord` |
| `probe/variant.py` | `DialectVerdict`, beside `VariantEvidence` rather than inside it |
| `api/bench.py` | sessions for both probes, and `adjudicate` |

**One traversal, two consumers** (convention 11): `attest_steps` is a generator, `run_attestation` drains it, and `tests/test_attest_steps.py` pins that stepping and draining reach the same result and spend the same calls across seven control-flow cases.

### The three rules the design rests on

1. **An attestor is never told the answer**, enforced by signature rather than by prompt wording. A test asserts that the same call with a *different* expectation produces a byte-identical prompt.
2. **Controls are manufactured, not collected** — which is how this escapes the problem that killed the marker corpus. Two survive, because only these have answers certain by construction: **identity** (one text as both halves of a pair; it cannot be two varieties) and **order** (one pair shown both ways; the answer must follow the text, not the slot). Two of the three controls in the original design turned out to need knowledge *about the dialect*, which is exactly what we do not have.
3. **The record routes, it never vouches.** `CapabilityRecord` exposes `put`, `get`, `known`, `rows`, `history`, `promote` and nothing that answers "is this attestor trustworthy" — a test pins the public surface. Controls run every time regardless of what is stored.

### Storage

**Append-only with a current flag.** Schema head **d7b2c0a94e13**. A re-run never replaces a verdict somebody trusts: `put_capability(promote=None)` promotes only when nothing is current yet, and promotion is an explicit gesture that deletes nothing and can be undone. There is deliberately **no unlock code** — a password on an overwrite still overwrites, and nothing is destroyed here for it to protect.

This differs from `upsert_result`, which auto-promotes fresher ladder results, and the difference is intended: a ladder result comes from an unattended scan over hundreds of languages; a dialect verdict is produced one at a time by a person who is right there.

`GET /dialect/record` serves the publishable JSON. `GET /dialect/stored` is what the page shows on selection.

## What is actually measured

**Two verdicts**, both `openai-gpt-4o`: `pt-pt` → `full-command` (high, two measurements on file), `sr-ba-latn` → `no-evidence` (low). Everything else in `capability` is attestor competence.

**`sr-me-cyrl` and `ru-kz` have attestor rows but no verdict** — those runs predate the producer record existing, and their verdicts are gone. Not retroactive. Re-run them if you want them.

## What the smoke test found

Recorded in protocol 021's Results, with n=1 per arm stated plainly.

- **`sr-me-cyrl`** → `full-command`, high. Both attestors named Montenegro unprompted citing **Пјешачила**, the ijekavian yat reflex, grounded in the text. Consistent with 012's `proven` 1.00.
- **`ru-kz`** → `no-evidence`. Zero conversion edits; all three attestors independently said `generic` and `indistinguishable`. **The instrument that fires on a known positive stays silent on a known null**, same models, same prompts. That is what H5 needs.
- **A control rejected an attestor on live data.** `groq-qwen3-8-27b` failed the order control — shown one pair twice it answered Serbia/Montenegro, then indistinguishable/indistinguishable.
- **`ru-by` produced Belarusian**, and the gate was right to convict. Protocol 010's failure reproducing, exactly as 020's H3 predicted — 020 expected it at `gsw-CH` and it arrived at `ru-BY`. A region whose name is also a language's name cannot be probed through the region-qualified designator; the Russian null runs through `ru-kz` instead.

## Defects this work found and fixed

- **`pt` and `pt-br` produced the identical prompt.** `candidates_for` passed `region_name` unconditionally, and an umbrella tag has no region subtag while still inheriting a region *name*. The neutral arm was being asked to be the dialect it is contrasted against — every contrast would have been null by construction, and the null would have looked like a finding.
- **`scope` held two different claims** — ISO macrolanguage and the TMS umbrella flag — making `kk` a macrolanguage with no members. Now `scope` and `inclusive`.
- **The conversion copy check convicted the correct answer.** In a conversion the user message *is* the text being transformed, so returning it unchanged was recorded as `copy`. The whole Russian arm came back convicted for being right.
- **The order control was a repeat test half the time.** Obtaining the two presentations by swapping arguments re-salts the coin; measured at 1,014 of 2,000 pairs showing the same order twice.
- **A third variety would have been a phantom option.** `sibling` takes only the first non-tag variety, so a third tick added a blind option no text was produced for. Hence exactly two.
- **The producer's verdict was recorded nowhere** — only attestor competence was.

## What remains

**Part 6, the programme run, has not started** — deliberately, pending bench review. Protocol 021's sample is five families (SR, ES, PT, EN, RU), ~20 calls per variety with a three-attestor panel.

**020's H2 is still open and still gates the four-engine re-run.** Its H1 and H3 are superseded by 021.

**The limit on H5, stated in 021 and worth re-reading before interpreting any null:** an attestor answering `indistinguishable` to everything passes both controls. Catching over-merging needs a pair known to be distinguishable, which is the knowledge we lack by assumption — available only for Serbian and English from protocol 012. A clean Russian null is consistent both with the method working *and* with every attestor merging everything, and only the calibration arms can tell those apart.

---
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

**S12.5 — dialect attestation, parts 0–5.** The marker corpus is retired as the instrument (the seven authored sets stay as calibration fixtures); measurement moves to evidence the models produce and we verify. Protocol 021 carries the hypotheses and the smoke test. The operating scheme became `catmint`. See the section at the top for the architecture, the rules, and the defects it found.



**The Catmint locale scan** (jobs 14–17, 154 locales × 4 engines) and the control-gap ranking in `data/results/control_gap.json`: the high-value slice is **27 locales, not 120**. Written up in doc 03. It also exposed a control-lookup bug — `ko` carries script `Kore`, the control text carries `Hang` — now fixed so a control answers for a script-*compatible* spelling and only that.

**S9 — README and methodology.** `docs/04 - Methodology.md` is new; the README gained a *What it found* section, the coverage ceiling, a *What a result does not mean* list, and three factual corrections (stale status block, `SCAN_TRIGGER` documented as the library default rather than what compose sets, `SCAN_TRIGGER_MAX_CALLS` as 2000 against an actual 5000).

## Next step

**1. Review and refactor the Bench UI.** See the top. It works and it does not read well, and it has had no considered pass — only a dozen small corrections.

**2. Then part 6**, the programme run, once the bench is worth sitting at.



**1. A protocol on the `Assisted`/`Proficient` cut.** 13% of tiers flip when a qualified reader is swapped, and five `Assisted` languages scored content 0.00 while being routed as "MT-assist, mandatory human pass" — fluent text, no meaning. Protocol 018 measured cuts at 0.50/0.70/0.85 as non-monotonic, so 0.95 was the only monotonic option; the live runs are better evidence than that simulation. This decides whether three tiers are honest or two.

**2. S10 — public landing page.** Andrei's portfolio piece; should publish browsable results, not just describe the method. Doc 04 is the text it can be built from.

**3. Rebuild the image and clear the stale rows.** The running container is from an image four weeks old, so the UI is serving pre-Catmint, pre-`ko`-fix code over current data (`docker compose build --no-cache api`). `llmlc status` also reports 11 rows under an older method, and gpt-4o still carries 11 five-tier rows (`Strong`, `None`) from method 1.x.

## Needs Andrei, not the agent

- **Dialects — now the live question; see the section at the top.** Marker sets exist for **7 of 534 variant tags**: en-AU, en-GB, and Serbian ijekavian in both scripts. All `reviewed: false`, and **the Serbian ones want a speaker's eye** — they were drafted by someone who does not read the language, which is why the loader checks them against worked examples. The method is still untested where it would be most load-bearing (`ar-EG` against `ar-MA`), and whether marker probing is even the right instrument there is the open question.
- **Control texts** for the Catmint locales FLORES lacks. The gap is now ranked rather than guessed: `data/results/control_gap.json` names **27 locales attempted by three or more engines**, of which only `ko` turned out to be free from FLORES — so 26 texts, each buying three or four engines' worth of unknown. Same kind of job as the markers.
- **Whether to build the local GPU back-translator.** Not built; the GPU is unused; `hardware.detect()` now reports `profile: api` with `capable_of: gpu-int8` rather than claiming MADLAD read the text. The argument for finishing it is **reproducibility**, not cost — a vendor endpoint cannot be pinned, and a published dataset whose instrument has been retired cannot be re-graded. Detection logic survives behind `hardware.LOCAL_BACKTRANSLATOR`. Do not switch instruments mid-programme: convention 4 would strand every existing result.

## Open, carried forward

- **Dialect verdicts are not joined to the support table.** A `capability` row with role `generation` says deepseek writes `pt-pt`; nothing surfaces that beside the language tier a reader sees on the Support tab. Joining them is a real design question — a `Result` row needs a tier, a back-translator and a judge, none of which a dialect run has — and is probably S13 rather than a patch.
- **`sr-me-cyrl` and `ru-kz` have attestor records but no verdict.** Their runs predate the producer record. Re-run to fill them.
- **The capability record has no staleness view.** `measured_at` is stored and nothing reports on it, so a year-old verdict reads exactly like a fresh one in the published JSON.

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
