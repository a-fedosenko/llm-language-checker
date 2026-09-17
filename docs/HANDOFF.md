# Handoff — continue from here

Paste the block below into a new session. Everything else it needs is in the repo.

---

We are building **llm-language-checker**: a self-hosted, heuristic tool that measures which languages an LLM can actually produce, rather than which ones a vendor claims. It exists to populate per-locale engine support data for our TMS/CAT system, and as a portfolio project. Not commercial.

**Read these first, in order** — they carry every decision and its reasoning:

- `docs/01 - Initial discussion - stage 1.md` — prior art, methodology, output contract, dialect/macrolanguage logic
- `docs/02 - Experiment - invented language control.md` — why self-reported language support cannot be trusted
- `docs/03 - Architecture and development stages.md` — architecture, data model, staging, and the implementation log for S0–S4
- `experiments/protocols/README.md` — ten experiment protocols; 005 and 010 matter most

**State:** S0–S4 complete, 134 tests passing, last commit `53e2573`. Working tree clean.

**Run it:**
```bash
source .venv/bin/activate          # or use .venv/bin/llmlc directly
set -a && . .env && set +a         # aggregator endpoint + key, gitignored
llmlc scan --engine openai-gpt-4o --tag de,cv --dry-run
llmlc status
uvicorn llmlc.api.main:app --port 8099    # UI; 8000/8010/8025/8077/8081/8082/8088 are taken
pytest -q
```

**Conventions that are not obvious from the code:**

1. **Every experiment gets a protocol** in `experiments/protocols/`, following `TEMPLATE.md`, with the hypothesis written down *before* the run. Invalidated results are kept with `Status: invalidated`, not deleted. Raw responses are committed.
2. **Reasoning must be off** for every measurement call. Vendor defaults differ and that confound already invalidated one conclusion (protocol 002). `reasoning_effort: "none"`, with per-model fallback — gpt-4o rejects the parameter outright.
3. **SQLite only.** No Postgres — compose is a single container. A single-tenant local tool does not need a database server, and supporting both cost us two real bugs. WAL is enabled so the CLI can write on the host while the UI reads from the container through the same bind-mounted file.
4. **Results are only comparable within the same back-translator, judge and method version.** That is why they are part of the uniqueness constraint.
5. **`no-control` is never a pass.** Where the back-translator cannot be qualified for a language, the result is `unverified` with the reason named.
6. Before claiming a finding, **read the raw evidence**. Two scans produced results that looked like findings and were bugs; a third looked like bugs and was a finding.

**Next step: S5 — the full UI.** Pick engine and languages, trigger a scan, watch progress, browse results, download artifacts.

**One decision is open and blocks part of S5.** `/jobs` currently only *reports* scans; the CLI creates them. I deliberately did not build an endpoint that starts a scan, because an HTTP endpoint that spends the user's API budget needs authentication, and authentication is precisely what the self-hosted design removed the need for. Two options:

- keep scans CLI-only and leave the UI read-only, or
- add a trigger bound to localhost, on the reasoning that anyone who can reach it already has the `.env`.

Ask before building it.

**Also open, carried forward in doc 03:**
- `resolves_to` is persisted but not yet surfaced as the macrolanguage-defaults comparison the landing page wants (what each model defaults to for `ar`, `zh`, `en`, `kk`, versus what the standard says).
- Corpus rows still go to JSONL; the `generation` table exists and is unused until S7 needs offline re-grading.
- Back-translator panel order affects qualification cost — a failing candidate costs 4 chrF++ calls before the next is tried.
- `/results` loads every row and serialises it. Fine at a few thousand (59 ms), but it will need pagination before a full catalogue across several models. An API limit, not a storage one — relevant to S5.
- Should low `reliability` cap the tier? `ug` currently reads "Strong — light review" at reliability 0.33, which is true about quality and possibly misleading about availability.

**Remaining stages:** S5 full UI · S6 dialects and marker files · S7 calibration study (fact-recall vs chrF++ on ~200 FLORES languages — the strongest artifact in the project) · S8 README and methodology page · S9 public landing page, which is Andrei's portfolio piece and should publish browsable results, not just describe the method.
