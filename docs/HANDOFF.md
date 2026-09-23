# Handoff — continue from here

Paste the block below into a new session. Everything else it needs is in the repo.

---

We are building **llm-language-checker**: a self-hosted, heuristic tool that measures which languages an LLM can actually produce, rather than which ones a vendor claims. It exists to populate per-locale engine support data for our TMS/CAT system, and as a portfolio project. Not commercial.

**Read these first, in order** — they carry every decision and its reasoning:

- `docs/01 - Initial discussion - stage 1.md` — prior art, methodology, output contract, dialect/macrolanguage logic
- `docs/02 - Experiment - invented language control.md` — why self-reported language support cannot be trusted
- `docs/03 - Architecture and development stages.md` — architecture, data model, staging, and the implementation log for S0–S6
- `experiments/protocols/README.md` — thirteen experiment protocols; 005, 011, 012 and 013 matter most

**State:** S0–S6 complete and the S7 calibration path built but not yet run; 256 tests passing.

**Run it:**
```bash
source .venv/bin/activate          # or use .venv/bin/llmlc directly
set -a && . .env && set +a         # aggregator endpoint + key, gitignored
llmlc scan --engine openai-gpt-4o --tag de,cv --dry-run
llmlc status                       # what is measured, what is stale
llmlc markers                      # variant coverage and the remaining gap
llmlc calibrate --engine <model> --dry-run   # the S7 study; needs specs built first
uvicorn llmlc.api.main:app --port 8099    # UI; 8000/8010/8025/8077/8081/8082/8088 are taken
pytest -q
```

The UI has five tabs: **Results** (paged, faceted, a row expands to its items and evidence), **Resolution** (what each tag actually got you), **Variants** (dialect evidence and the marker gap), **Scan** (plan for free, then start one), **Jobs** (per-class progress, cancel, history). Every block title and column heading carries an info icon defining the term; those definitions live in a single `HELP` dictionary in `index.html` rather than in the markup, because the same terms appear in several tables.

Schema changes are Alembic's. A database made by `create_all()` has no version row, so migrating one for the first time needs `alembic stamp fb431915efe4 && alembic upgrade head`.

**Conventions that are not obvious from the code:**

1. **Every experiment gets a protocol** in `experiments/protocols/`, following `TEMPLATE.md`, with the hypothesis written down *before* the run. Invalidated results are kept with `Status: invalidated`, not deleted. Raw responses are committed.
2. **Reasoning must be off** for every measurement call. Vendor defaults differ and that confound already invalidated one conclusion (protocol 002). `reasoning_effort: "none"`, with per-model fallback — gpt-4o rejects the parameter outright.
3. **SQLite only.** No Postgres — compose is a single container. A single-tenant local tool does not need a database server, and supporting both cost us two real bugs. WAL is enabled so the CLI can write on the host while the UI reads from the container through the same bind-mounted file.
4. **Results are only comparable within the same back-translator, judge and method version.** That is why they are part of the uniqueness constraint.
5. **`no-control` is never a pass.** Where the back-translator cannot be qualified for a language, the result is `unverified` with the reason named.
6. Before claiming a finding, **read the raw evidence**. Three of the last four real bugs were found by looking at actual output rather than by tests: two marker defects in S6, and a duplicate-row bug that surfaced only as two identical rows in the UI.
7. **Tier is capability; availability is willingness** (protocol 011). Refusals are excluded from `s_lang` and reported separately. Do not let one become the other — the workflow sentence carries the caveat, the tier does not move.
8. **`runner.py` is the only definition of "run a scan".** The CLI and the HTTP trigger differ in how they report progress and who may call them, nothing else. Add scan behaviour there, not in `cli.py`.
9. **Inheriting a tier is not inheriting a claim** (S6). A variant tag gets its own `variant_evidence` by script, markers, an authored `not-distinguishable`, or `untested`. The last two are different on purpose: one is a finished decision, the other is countable remaining work.
10. **The pivot language is measured through a different pivot** (protocol 013). Back-translating English into English grades nothing, so `en` falls through to `de`, then `fr`, then `es`. The pivot rides in the back-translator id (`remote:model@de`), which keeps qualifications cached per pivot and stops two incomparable measurements of one language from overwriting each other.
11. **A deterministic negative has no instrument.** It stores `NO_INSTRUMENT` (`"(not needed)"`) because the local gate settled it and nothing read the language — so it is comparable to *every* back-translator's result rather than none of them, and `repo.upsert_result` collapses it onto the same row. A sentinel sitting in an identity column is why `kk-Latn` appeared twice.
12. **Where a defect would be invisible in the output, the guard goes in the loader.** Marker scoring is string matching, so a wrong marker yields a plausible number with nothing to flag it. Three such defects are now rejected at load time rather than trusted to review (protocol 012).

**On the scan trigger.** `POST /scans` is bound to loopback (`SCAN_TRIGGER=off|loopback|any`, default `loopback`), because reaching it already implies access to the machine holding the `.env`. Only the socket peer address counts — a forged `X-Forwarded-For` is tested to fail. Docker needs `any`, where the control is the port binding, and compose publishes on `127.0.0.1`. A browser-started scan must name a `max_calls`; the CLI need not. One scan at a time; a second gets `409`. Cancellation is checked between classes, and orphaned `running` jobs are reaped at API startup.

---

## Next step: run the S7 calibration pilot

**The path is built and proven; the study has not been run.** [Protocol 014](../experiments/protocols/014-fact-recall-vs-chrf.md) holds the hypothesis, written before any measurement, and a design note from a four-item smoke run. The only thing standing between here and a result is deciding how much to spend.

```bash
python scripts/build_calibration_specs.py --tags <20 tags> --items 4   # ~1 call per item
llmlc calibrate --engine openai-gpt-4o --tag <same tags> --dry-run     # free, prints the estimate
llmlc calibrate --engine openai-gpt-4o --tag <same tags> --items 4     # 3 calls per item
```

Use protocol 008's twenty-language spread for the tag list, so the results sit alongside an existing run.

**Read the design note in protocol 014 before choosing the sample.** The smoke run found chrF++ spanning 45.6 to 73.2 while fact recall was 1.00 on every item — the item-level correlation came back *undefined*, not weak, because a constant metric has no ordering. Fact recall over a four-fact checklist separates adequate from inadequate, not good from better. **A pilot drawn from well-supported languages will measure nothing.** Weight it toward languages the model handles badly, and expect the language-level arm to carry the study.

**How it works, and the limitation to keep stating.** The model translates a FLORES source sentence; the same output is scored by chrF++ against the human reference and by fact recall against a checklist extracted from the source. It has to be a translation task because chrF++ needs a reference for the specific text being scored, and free compositions have none — which is why `Evidence.GOLD_REFERENCE`, declared in S2 on the assumption this would fall out of the ordinary probe, went unassigned until now. So the study calibrates on translation and the proxy is applied to free generation, and that transfer is an assumption, not a finding.

**After the pilot:** complete protocol 014's Method/Results/Conclusions, decide whether the tier thresholds in `probe/score.py` need moving, and only then price the full ~200-language run.

**Open, carried forward in doc 03:**

- **One test fails from a clean clone**: `test_shipped_controls_cover_flores_breadth_and_the_hand_seeded_gap` needs `data/controls/flores.json`, untracked as licence-encumbered. Pre-existing since `3032687` and unrelated to recent work; everything passes where the data has been built. `tests/test_pivot.py` handles the same situation by skipping when no reference control is present, and that test should probably do the same.
- Marker coverage is 2 of 534 variant tags. The method is proven on English — which is also the pivot, and the easiest possible case — and untested where it would be load-bearing (`ar-EG` vs `ar-MA`). Drafting is a model-plus-human-review job, per doc 01.
- The marker **grammar axis never fires** — 0 hits in 28 generations. Its contexts need rewriting to force *in hospital* / *different to*, or the axis should be dropped rather than left as dead weight.
- Both shipped marker lists are `reviewed: false`. They are drafted claims about a language, not reviewed ones, and the code says so everywhere it shows them.
- Back-translator panel order affects qualification cost — a failing candidate costs 4 chrF++ calls before the next is tried.
- The UI reads the database when it has rows and the evidence files only when it does not, so old file-only results disappear after a user's first scan. Correct precedence, surprising presentation.
- Resuming a stopped job from the UI is not built. `pending_items()` is the resume set and a stopped job keeps it intact; re-running is currently a fresh scan over the same tags.
- Whether refusal predicts quality is unanswerable at n=3 (protocol 011). S7's ~200-language run is where to test it, and availability is derived rather than stored precisely so the rule can change.
- `kk-Latn` deserves a second look with a different model: asked properly, gpt-4o returns Latin script that GlotLID reads as Crimean Tatar and Turkmen. A recent official alphabet with little training text is a plausible genuine gap rather than a gpt-4o quirk.

**Remaining stages:** S7 calibration study · S8 README and methodology page · S9 public landing page, which is Andrei's portfolio piece and should publish browsable results, not just describe the method.
