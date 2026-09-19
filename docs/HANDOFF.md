# Handoff — continue from here

Paste the block below into a new session. Everything else it needs is in the repo.

---

We are building **llm-language-checker**: a self-hosted, heuristic tool that measures which languages an LLM can actually produce, rather than which ones a vendor claims. It exists to populate per-locale engine support data for our TMS/CAT system, and as a portfolio project. Not commercial.

**Read these first, in order** — they carry every decision and its reasoning:

- `docs/01 - Initial discussion - stage 1.md` — prior art, methodology, output contract, dialect/macrolanguage logic
- `docs/02 - Experiment - invented language control.md` — why self-reported language support cannot be trusted
- `docs/03 - Architecture and development stages.md` — architecture, data model, staging, and the implementation log for S0–S5
- `experiments/protocols/README.md` — eleven experiment protocols; 005, 010 and 011 matter most

**State:** S0–S5 complete, 182 tests passing.

**Run it:**
```bash
source .venv/bin/activate          # or use .venv/bin/llmlc directly
set -a && . .env && set +a         # aggregator endpoint + key, gitignored
llmlc scan --engine openai-gpt-4o --tag de,cv --dry-run
llmlc status
uvicorn llmlc.api.main:app --port 8099    # UI; 8000/8010/8025/8077/8081/8082/8088 are taken
pytest -q
```

The UI has four tabs: **Results** (paged, faceted, one row expands to its items and evidence), **Resolution** (what each tag actually got you), **Scan** (plan for free, then start one), **Jobs** (per-class progress, cancel, history).

**Conventions that are not obvious from the code:**

1. **Every experiment gets a protocol** in `experiments/protocols/`, following `TEMPLATE.md`, with the hypothesis written down *before* the run. Invalidated results are kept with `Status: invalidated`, not deleted. Raw responses are committed.
2. **Reasoning must be off** for every measurement call. Vendor defaults differ and that confound already invalidated one conclusion (protocol 002). `reasoning_effort: "none"`, with per-model fallback — gpt-4o rejects the parameter outright.
3. **SQLite only.** No Postgres — compose is a single container. A single-tenant local tool does not need a database server, and supporting both cost us two real bugs. WAL is enabled so the CLI can write on the host while the UI reads from the container through the same bind-mounted file.
4. **Results are only comparable within the same back-translator, judge and method version.** That is why they are part of the uniqueness constraint.
5. **`no-control` is never a pass.** Where the back-translator cannot be qualified for a language, the result is `unverified` with the reason named.
6. Before claiming a finding, **read the raw evidence**. Two scans produced results that looked like findings and were bugs; a third looked like bugs and was a finding.
7. **Tier is capability; availability is willingness** (protocol 011). Refusals are excluded from `s_lang` and reported separately. Do not let one become the other — the workflow sentence carries the caveat, the tier does not move.
8. **`runner.py` is the only definition of "run a scan".** The CLI and the HTTP trigger differ in how they report progress and who may call them, nothing else. Add scan behaviour there, not in `cli.py`.

**On the scan trigger.** `POST /scans` is bound to loopback (`SCAN_TRIGGER=off|loopback|any`, default `loopback`), because reaching it already implies access to the machine holding the `.env`. Only the socket peer address counts — a forged `X-Forwarded-For` is tested to fail. Docker needs `any`, where the control is the port binding, and compose publishes on `127.0.0.1`. A browser-started scan must name a `max_calls`; the CLI need not. One scan at a time; a second gets `409`. Cancellation is checked between classes, and orphaned `running` jobs are reaped at API startup.

**Next step: S6 — dialects and marker files.** `en-AU` proven from a marker list; `ru-BY` correctly `not-distinguishable`; `kk-Latn` scored by script. This is where `variant_evidence: untested` — currently carried by every inherited tag — starts becoming a real claim.

**Open, carried forward in doc 03:**
- Corpus rows still go to JSONL; the `generation` table exists and is unused until S7 needs offline re-grading.
- Back-translator panel order affects qualification cost — a failing candidate costs 4 chrF++ calls before the next is tried.
- The UI reads the database when it has rows and the evidence files only when it does not, so old file-only results disappear after a user's first scan. Correct precedence, surprising presentation.
- Resuming a stopped job from the UI is not built. `pending_items()` is the resume set and a stopped job keeps it intact; re-running is currently a fresh scan over the same tags.
- Whether refusal predicts quality is unanswerable at n=3 (protocol 011). S7's ~200-language run is where to test it, and availability is derived rather than stored precisely so the rule can change.

**Remaining stages:** S6 dialects and marker files · S7 calibration study (fact-recall vs chrF++ on ~200 FLORES languages — the strongest artifact in the project) · S8 README and methodology page · S9 public landing page, which is Andrei's portfolio piece and should publish browsable results, not just describe the method.
