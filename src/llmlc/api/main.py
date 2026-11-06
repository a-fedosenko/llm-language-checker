"""The HTTP surface.

Read endpoints are open: nothing here is secret, and the whole tool runs on one
person's machine. The single write endpoint -- `POST /scans`, which spends the
user's API budget -- is gated by `settings.scan_trigger`, because "self-hosted,
therefore no authentication" stops being a sufficient answer the moment an
endpoint can cost money. See `_check_trigger_allowed`.
"""
from __future__ import annotations

import ipaddress
import json
from contextlib import asynccontextmanager
import pathlib
import urllib.error
import urllib.request
from functools import lru_cache

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from llmlc import __version__, bootstrap, hardware, runner
from llmlc.api import results as results_store
from llmlc.client import (NotConfigured, build_client, check_models, custom_models,
                          is_configured)
from llmlc.api import bench as bench_sessions, support_table
from llmlc.support import (GROUP_MEANING as support_group_meaning,
                           GROUPS as support_groups,
                           MEANING as support_meaning, ORDER as support_order)
from llmlc.config import settings
from llmlc.scheme import Language, Scheme, load_scheme

STATIC = pathlib.Path(__file__).resolve().parent / "static"

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """A scan lives in this process, so any job still marked `running` at startup
    was orphaned by a restart. Reconcile before serving, or the first thing the
    UI does is wait on a job nobody is working."""
    try:
        for job_id in runner.reap_orphans():
            print(f"[llmlc] job {job_id} was left running by a previous process; marked failed")
    except Exception as e:  # noqa: BLE001 -- never let this stop the server booting
        print(f"[llmlc] could not reconcile jobs at startup: {e}")

    try:
        if bootstrap.auto():
            print("[llmlc] first-run assets fetched (AUTO_BOOTSTRAP)")
        else:
            missing = bootstrap.status()["missing"]
            if missing:
                # Printed, not fatal. The UI serves committed results perfectly
                # well without these; it is *scanning* that would measure less
                # than it reports, and the readiness banner says so there.
                print(f"[llmlc] first-run assets missing: {', '.join(missing)} — "
                      f"run `llmlc bootstrap` or use the button in the UI")
    except Exception as e:  # noqa: BLE001
        print(f"[llmlc] readiness check failed: {e}")
    yield


app = FastAPI(
    lifespan=lifespan,
    title="llm-language-checker",
    version=__version__,
    description="Empirical, heuristic checks of which languages a model can actually produce. "
                "Run locally; results are evidence, not proof.",
)


#: Locale lists kept on disk but not offered in the UI. `default` is the public
#: 9,589-tag catalogue: still the reference controls resolve against, no longer
#: a list anyone should scan. Hidden, not removed -- it is what
#: `scripts/build_scheme_from_tms.py` resolves a TMS list against.
HIDDEN_SCHEMES = {"default"}


@lru_cache(maxsize=4)
def get_scheme(name: str) -> Scheme:
    return load_scheme(name)


@app.get("/health")
def health() -> dict:
    try:
        s = get_scheme(settings.scheme)
        loaded, tags = True, len(s.languages)
    except FileNotFoundError:
        loaded, tags = False, 0
    return {"status": "ok", "version": __version__, "scheme_loaded": loaded, "tags": tags}


@app.get("/readiness")
def readiness() -> dict:
    """What a scan needs, and whether it is here.

    Separate from `/health`, which answers "is the service up". This answers "is
    the instrument complete" -- and they are different questions, because the
    service runs perfectly well while measuring with half a gate. Stating that is
    the same rule as `no-control is never a pass`: when the instrument is
    missing, say so rather than quietly answer worse.
    """
    st = bootstrap.status()
    st["disk_free_mb"] = bootstrap.disk_free_mb()
    return st


@app.post("/bootstrap")
def bootstrap_fetch(request: Request, body: BootstrapRequest | None = None) -> dict:
    """Fetch the missing first-run assets.

    Gated exactly like `POST /scans`: it is the other endpoint that reaches the
    network and writes to the user's disk, and 1.6 GB is not something a passing
    caller should be able to start. Same setting, same reasoning.
    """
    _check_trigger_allowed(request)
    keys = (body.assets if body else None) or None
    try:
        return bootstrap.ensure(keys)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OSError as e:
        raise HTTPException(status_code=502, detail=f"fetch failed: {e}") from e


@app.get("/hardware")
def hardware_info() -> dict:
    return hardware.detect(settings.hardware_profile).as_dict()


@app.get("/scheme")
def scheme_meta() -> dict:
    return get_scheme(settings.scheme).meta.model_dump()


@app.get("/languages")
def languages(
    q: str | None = Query(None, description="Substring match on tag, name or endonym"),
    scope: str | None = Query(None, pattern="^(individual|macrolanguage)$"),
    type_: str | None = Query(None, alias="type", description="ISO 639-3 type: L, E, H, A, C"),
    limit: int = Query(100, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    scheme: str | None = Query(None, description="Locale list to search; the active one by default"),
) -> dict:
    items = list(get_scheme(scheme or settings.scheme).languages.values())
    if scope:
        items = [x for x in items if x.scope == scope]
    if type_:
        items = [x for x in items if x.type == type_]
    if q:
        ql = q.lower()
        items = [x for x in items
                 if ql in x.tag.lower()
                 or (x.name and ql in x.name.lower())
                 or (x.local_name and ql in x.local_name.lower())]
    return {"total": len(items), "offset": offset, "limit": limit,
            "items": items[offset: offset + limit]}


@app.get("/languages/{tag}")
def language(tag: str) -> dict:
    s = get_scheme(settings.scheme)
    lang = s.get(tag)
    if lang is None:
        raise HTTPException(404, f"Unknown tag {tag!r} in scheme {s.meta.name!r}")
    macro = s.macro_for(tag)
    return {
        "language": lang,
        "class_members": s.classes().get(lang.cls, []),
        "variants": s.variants_of(tag),
        "inherits_from": macro.tag if macro else None,
    }


# -- results -----------------------------------------------------------------

@app.get("/results")
def results(
    engine: str | None = Query(None),
    tier: str | None = Query(None),
    evidence: str | None = Query(None),
    availability: str | None = Query(None,
                                     pattern="^(reliable|intermittent|unreliable|refused)$"),
    variant: str | None = Query(
        None, pattern="^(proven|proven-failed|not-distinguishable|untested)$",
        description="variant evidence state"),
    q: str | None = Query(None, description="substring match on tag or language name"),
    limit: int = Query(200, ge=1, le=5000),
    offset: int = Query(0, ge=0),
) -> dict:
    """One page of results, with a summary over every row that matched.

    Paged because a full catalogue across several models is six figures of rows
    and the old unpaged version serialised all of them on every load.
    """
    return results_store.page(results_store.Query(
        engine=engine, tier=tier, evidence=evidence, availability=availability,
        variant=variant, q=q, limit=limit, offset=offset))


@app.get("/results/{engine}/{tag}")
def result_detail(engine: str, tag: str) -> dict:
    row = results_store.detail(engine, tag)
    if row is None:
        raise HTTPException(404, f"No result for {tag!r} on {engine!r}")
    return row


@app.get("/resolution")
def resolution(engine: str | None = Query(None),
               macro_only: bool = Query(False,
                                        description="only macrolanguages, where the "
                                                    "standard defines members")) -> dict:
    """What each model actually produces when asked for a language, against what
    the catalogue says that language resolves to."""
    return results_store.resolution(engine, only_macro=macro_only)


@app.get("/variants")
def variant_coverage(engine: str | None = Query(None)) -> dict:
    """Dialect evidence per tag, and the size of the remaining gap.

    `untested` is deliberately countable: it means no marker set has been
    authored for that variant yet, so inheriting the base language's tier is a
    placeholder rather than a claim.
    """
    return results_store.variants(engine)


@app.get("/engines")
def engines() -> dict:
    """Models available to scan, and models already measured.

    `available` is the custom model list where one is configured, and the
    gateway's own list otherwise -- the UI needs a picker, and typing a model
    name from memory is how you spend a budget on a typo.

    How binding it is depends on which source answered, and the difference is
    real. A gateway's list is advisory: it is the gateway's opinion, and a name
    missing from it is still worth trying. A custom list is the configuration
    itself -- a model absent from it has no endpoint and no key, so a scan
    naming one is refused before it spends anything.
    """
    measured = sorted(results_store.page(
        results_store.Query(limit=1)).get("summary", {}).get("engines", {}))
    try:
        closed = bool(custom_models())
    except NotConfigured:
        closed = False
    return {"available": _model_list(), "measured": measured,
            "judge": settings.judge_model,
            "backtranslator_panel": runner.DEFAULT_PANEL.split(","),
            # Whether `available` is the whole of what can be scanned, so the UI
            # can offer a picker rather than a free-text field.
            "available_is_exhaustive": closed}


def _model_list() -> list[str]:
    """What the engine picker offers. The custom list first, the gateway second.

    The custom list is read every call rather than cached: it is a local file
    the user edits, and a picker that needs a container restart to notice a new
    model is the kind of staleness this project has already been bitten by. The
    network path stays cached -- see `_aggregator_model_list`.
    """
    try:
        entries = custom_models()
    except NotConfigured:
        # A broken list is reported where a scan is attempted, with the parse
        # error. Here it only means the picker has nothing to offer.
        return []
    if entries:
        return sorted(e.model_id for e in entries)
    return _aggregator_model_list()


@lru_cache(maxsize=1)
def _aggregator_model_list() -> list[str]:
    """Model ids from the aggregator, cached for the process.

    Failure is silent and returns nothing: an unreachable gateway must degrade
    the picker to a free-text field, not break the page.
    """
    url = settings.aggregator_model_list_url
    if not url:
        return []
    req = urllib.request.Request(url)
    if settings.aggregator_admin_api_key:
        req.add_header("Authorization", f"Bearer {settings.aggregator_admin_api_key}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = json.load(r)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return []
    rows = body.get("data", body) if isinstance(body, dict) else body
    if not isinstance(rows, list):
        return []
    out = [x.get("id") for x in rows if isinstance(x, dict) and x.get("id")]
    return sorted(str(x) for x in out)


@app.get("/support")
def support(engine: str, scheme: str | None = Query(None)) -> dict:
    """One model, every locale in a scheme, one row each.

    The plain answer, for a reader who wants to know what a model does with
    their locale list and not how it was established. Five statuses, an adequacy
    number where one was measured, and nothing else -- the evidence, the
    designator, the interval and the gate verdict all live on the Results tab,
    which is where someone asking *why* should be sent.

    Returned whole rather than paged: a locale list is a few hundred rows, and
    search and filter over a complete table in the browser beats a round trip
    per keystroke. The shipped 9,589-tag catalogue is the exception and is
    capped, because nobody browses nine thousand rows and the response is 2 MB.
    """
    data = support_table.build(engine, scheme)
    rows = data["rows"]
    if len(rows) > SUPPORT_MAX_ROWS:
        # Drop `unchecked` rows first, never a flat alphabetical slice. The page
        # searches and filters client-side, so a slice silently shrinks what the
        # filters can reach -- the counts said 29 unverifiable and the table
        # could only ever show the 5 that fell inside the first 2,000 rows.
        # An unchecked row carries nothing but its tag; a measured one is the
        # whole point, so measured rows are never the ones cut.
        measured = [r for r in rows if r["status"] != "unchecked"]
        unchecked = [r for r in rows if r["status"] == "unchecked"]
        keep = max(0, SUPPORT_MAX_ROWS - len(measured))
        data["rows"] = sorted(measured + unchecked[:keep],
                              key=lambda r: (r["name"] or r["tag"]).lower())
        data["truncated"] = len(rows)
        data["unchecked_omitted"] = len(unchecked) - keep
    return data


@app.get("/schemes")
def schemes() -> dict:
    """Locale lists on disk, so the support table can offer a picker.

    A user's own list is the point of the page -- the shipped 9,589-tag
    catalogue is a catalogue, not anyone's locale list -- and requiring an
    environment variable and a restart to look at it would be the wrong
    ergonomics for a question asked once a week.

    **`default` is withheld once a real locale list exists.** It remains on disk
    and remains what controls are resolved against, but offering it beside a TMS
    list invites a scan down 9,589 tags spelled in a different convention from
    the one being measured, whose base tags are themselves varieties.

    It is withheld *conditionally*, because `schemes/default.json` is the only
    scheme a fresh clone has -- every other one is gitignored, being built from a
    locale list that is not ours to publish. Hiding it unconditionally would
    hand a new user an empty picker. So: hidden when there is something better
    to offer, shown when it is all there is.
    """
    from llmlc.scheme.loader import SCHEMES_DIR

    found = []
    for f in sorted(SCHEMES_DIR.glob("*.json")):
        try:
            s = load_scheme(f.stem)
        except Exception:  # noqa: BLE001 -- a broken scheme file is not a 500 here
            continue
        found.append({"name": s.meta.name, "file": f.stem, "count": len(s.languages),
                      "description": s.meta.description})

    hideable = {f["file"] for f in found} - HIDDEN_SCHEMES
    out = [f for f in found
           if f["file"] not in HIDDEN_SCHEMES or f["file"] == settings.scheme
           or not hideable]
    return {"schemes": out, "active": settings.scheme}


@app.get("/support/statuses")
def support_statuses() -> dict:
    """What each status means, served from the one definition rather than
    restated in the page. A label whose meaning lives in two places drifts."""
    return {"order": [s.value for s in support_order],
            "meaning": {s.value: support_meaning[s] for s in support_order},
            # Unions over the five, so the page does not restate which statuses
            # a named filter covers. A group that means one thing in the code
            # and another in the markup is the drift this endpoint exists to
            # prevent.
            "groups": {name: [s.value for s in members]
                       for name, members in support_groups.items()},
            "group_meaning": dict(support_group_meaning)}


@app.get("/", include_in_schema=False)
def index():
    page = STATIC / "index.html"
    if not page.exists():
        return {"message": "UI not installed", "docs": "/docs"}
    return FileResponse(page)


# -- jobs and the scan trigger -----------------------------------------------

#: Rows above which `/support` stops sending the whole table. The shipped
#: catalogue is 9,589 tags; a user's own locale list is a few hundred.
SUPPORT_MAX_ROWS = 2000

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _job_dict(j, *, detail: bool = False) -> dict:
    done = sum(1 for i in j.items if i.status == "done")
    out = {"id": j.id, "engine": j.engine, "status": j.status,
           "method_version": j.method_version, "calls_used": j.calls_used,
           "max_calls": j.max_calls,
           "requested": len(j.requested_tags or []),
           "classes": len(j.items), "classes_done": done,
           "unknown": j.unknown_tags or [],
           "hardware_profile": j.hardware_profile,
           "cancelling": runner.is_cancelled(j.id),
           "error": j.error,
           "created_at": j.created_at.isoformat() if j.created_at else None,
           "finished_at": j.finished_at.isoformat() if j.finished_at else None}
    if detail:
        out["judge"] = j.judge
        out["pivot"] = j.pivot
        out["backtranslator_panel"] = j.backtranslator_panel or []
        out["requested_tags"] = j.requested_tags or []
        out["items"] = [{"cls": i.cls, "representative": i.representative,
                         "members": i.members or [], "status": i.status,
                         "error": i.error}
                        for i in sorted(j.items, key=lambda i: i.id)]
    return out


@app.get("/jobs")
def jobs(limit: int = Query(25, ge=1, le=200)) -> dict:
    """Recent scans, newest first, with per-class progress."""
    from sqlalchemy import select

    from llmlc.db import create_all, session
    from llmlc.db.models import Job
    create_all()
    with session() as s:
        rows = list(s.scalars(select(Job).order_by(Job.id.desc()).limit(limit)))
        return {"items": [_job_dict(j) for j in rows],
                "running": runner.running_job_id(),
                "trigger": _trigger_state()}


@app.get("/jobs/{job_id}")
def job_detail(job_id: int) -> dict:
    from llmlc.db import create_all, session
    from llmlc.db.models import Job
    create_all()
    with session() as s:
        job = s.get(Job, job_id)
        if job is None:
            raise HTTPException(404, f"No job {job_id}")
        return _job_dict(job, detail=True)


class ScanTrigger(BaseModel):
    """What the browser may ask for.

    `max_calls` is required here and optional on the CLI. Someone typing a command
    has already decided to spend; someone clicking a button in a browser should
    have to name the ceiling first.
    """

    engine: str = Field(min_length=1)
    tags: list[str] = Field(min_length=1)
    max_calls: int = Field(gt=0)
    backtranslator: str = runner.DEFAULT_PANEL
    judge: str | None = None
    pivot: str = "en"
    sweep_all: bool = False
    scheme: str | None = None


class BenchStart(BaseModel):
    engine: str
    tag: str
    mode: str = "interactive"          # interactive | auto -- recorded, not enforced
    judge: str | None = None
    backtranslator: str | None = None
    pivot: str = "en"
    scheme: str | None = None
    sweep_all: bool = False
    specs: list[dict] | None = Field(
        None, description="Rewritten content specifications. Any edit makes the run "
                          "incomparable to the stored results, and it is not saved.")


class BootstrapRequest(BaseModel):
    assets: list[str] | None = Field(None, description="asset keys; omit for all missing")


def _trigger_state() -> dict:
    return {"mode": settings.scan_trigger,
            "max_calls": settings.scan_trigger_max_calls,
            "configured": is_configured()}


def _check_trigger_allowed(request: Request) -> None:
    """Whether this caller may spend the user's API budget.

    The reasoning, written down because it is the one place this project trades
    away a property it otherwise holds: the self-hosted design removed the need
    for authentication by removing the multi-user case, and a write endpoint that
    costs money quietly puts it back. Rather than add accounts to a single-user
    tool, the trigger is bound to the loopback interface, where reaching it
    already implies access to the machine holding the `.env`.

    The peer address is the socket's, never `X-Forwarded-For`: a header any
    client can set is not an access control. Behind a real reverse proxy every
    request looks like loopback, which is why `off` exists and is one setting
    away.
    """
    mode = settings.scan_trigger
    if mode == "off":
        raise HTTPException(403, "Scan triggering is disabled (SCAN_TRIGGER=off). "
                                 "Start scans with `llmlc scan`.")
    if mode == "any":
        return
    host = request.client.host if request.client else None
    if host in LOOPBACK:
        return
    try:
        if host and ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise HTTPException(
        403, f"Scan triggering is limited to loopback and this request came from "
             f"{host or 'an unknown address'}. In Docker the peer address is the "
             f"bridge gateway: publish the port on 127.0.0.1 and set SCAN_TRIGGER=any, "
             f"or start scans with `llmlc scan`.")


@app.get("/scans/plan")
def plan_scan(engine: str, tags: str,
              scheme: str | None = Query(None)) -> dict:
    """The dry run, over HTTP. Costs nothing and spends nothing.

    Class collapse is the whole economics of a wide scan -- `de`, `de-AT` and
    `de-CH` are one experiment -- so the number that matters before you commit a
    budget is classes, not tags.
    """
    from llmlc.probe.scan import plan as plan_scan_groups
    s = get_scheme(scheme or settings.scheme)
    wanted = [x.strip() for x in tags.replace("\n", ",").replace(" ", ",").split(",") if x.strip()]
    groups, unknown = plan_scan_groups(s, wanted)
    known = sum(len(m) for m in groups.values())
    return {
        "engine": engine,
        "tags": known, "classes": len(groups), "inherited": known - len(groups),
        "unknown": unknown,
        "estimate_calls": len(groups) * 9,
        "groups": [{"cls": cls, "probe": members[0], "inherit": members[1:]}
                   for cls, members in groups.items()],
    }


@app.post("/scans", status_code=202)
def start_scan(body: ScanTrigger, request: Request) -> dict:
    """Start a scan. Returns immediately with the job to watch."""
    _check_trigger_allowed(request)
    ceiling = settings.scan_trigger_max_calls
    if body.max_calls > ceiling:
        raise HTTPException(400, f"max_calls {body.max_calls} exceeds the trigger ceiling "
                                 f"of {ceiling} (SCAN_TRIGGER_MAX_CALLS).")
    if (running := runner.running_job_id()) is not None:
        raise HTTPException(409, f"Job {running} is still running. One scan at a time: "
                                 f"SQLite takes one writer, and two scans would spend "
                                 f"against a budget neither of them set.")

    req = runner.ScanRequest(
        engine=body.engine, tags=body.tags, scheme=body.scheme,
        backtranslator=body.backtranslator, judge=body.judge, pivot=body.pivot,
        max_calls=body.max_calls, sweep_all=body.sweep_all)
    try:
        job_id = runner.create(req)
    except runner.ScanRefused as e:
        raise HTTPException(400, str(e)) from e
    runner.run_in_background(req, job_id)
    return {"job_id": job_id, "status": "running", "watch": f"/jobs/{job_id}"}


@app.post("/jobs/{job_id}/cancel")
def cancel_scan(job_id: int, request: Request) -> dict:
    """Ask a running scan to stop after the class it is on.

    Between classes rather than mid-class: a half-probed class is a partial
    measurement, and the calls already spent on it would be wasted either way.
    """
    _check_trigger_allowed(request)
    from llmlc.db import create_all, session
    from llmlc.db.models import Job
    create_all()
    with session() as s:
        job = s.get(Job, job_id)
        if job is None:
            raise HTTPException(404, f"No job {job_id}")
        if job.status != "running":
            return {"job_id": job_id, "status": job.status, "cancelled": False,
                    "detail": "Job is not running."}
    runner.cancel(job_id)
    return {"job_id": job_id, "status": "cancelling", "cancelled": True,
            "detail": "Will stop after the class in flight."}


@app.get("/stale")
def stale_results(engine: str | None = Query(None)) -> dict:
    """Results measured under an older method version -- the re-run set."""
    from llmlc.db import create_all, session
    from llmlc.db.repo import stale
    from llmlc.export.artifacts import METHOD_VERSION
    create_all()
    with session() as s:
        rows = stale(s, METHOD_VERSION, engine=engine)
        return {"current_method_version": METHOD_VERSION, "count": len(rows),
                "tags": sorted({r.tag for r in rows})}


# -- artifacts ---------------------------------------------------------------

ARTIFACTS = pathlib.Path("data/results")

#: Only the two artifacts the tool writes. A directory served by pattern is one
#: rename away from serving whatever else lands in it.
ARTIFACT_PREFIXES = ("support.", "evidence.")


@app.get("/artifacts")
def artifacts() -> dict:
    """The files a scan wrote, for download."""
    if not ARTIFACTS.is_dir():
        return {"items": []}
    out = []
    for f in sorted(ARTIFACTS.iterdir()):
        if not f.is_file() or not f.name.startswith(ARTIFACT_PREFIXES):
            continue
        st = f.stat()
        out.append({"name": f.name, "bytes": st.st_size,
                    "kind": "support" if f.name.startswith("support.") else "evidence",
                    "modified": st.st_mtime})
    return {"items": out, "dir": str(ARTIFACTS)}


@app.get("/artifacts/{name}")
def artifact(name: str):
    if "/" in name or "\\" in name or not name.startswith(ARTIFACT_PREFIXES):
        raise HTTPException(404, f"No artifact {name!r}")
    path = (ARTIFACTS / name).resolve()
    if not path.is_file() or ARTIFACTS.resolve() not in path.parents:
        raise HTTPException(404, f"No artifact {name!r}")
    return FileResponse(path, filename=name, media_type="application/octet-stream")


@app.get("/export.csv")
def export_csv(
    engine: str | None = Query(None),
    tier: str | None = Query(None),
    evidence: str | None = Query(None),
    availability: str | None = Query(None,
                                     pattern="^(reliable|intermittent|unreliable|refused)$"),
    q: str | None = Query(None),
):
    """The filtered view as a spreadsheet.

    Deliberately not the mergeable artifact: this is for reading, `llmlc export`
    is for merging, and conflating the two is how a scored prompt string ends up
    in someone's production config (docs/01).
    """
    import csv
    import io

    from fastapi.responses import StreamingResponse

    rows = results_store.page(results_store.Query(
        engine=engine, tier=tier, evidence=evidence, availability=availability,
        q=q, limit=1_000_000))["items"]
    cols = ["tag", "language", "engine", "tier", "workflow", "evidence", "availability",
            "s_lang", "s_content", "ci_low", "ci_high", "borderline", "reliability",
            "refusals", "designator", "inherited_from", "backtranslator", "judge",
            "method_version", "tested_at"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        ci = r.get("ci") or [None, None]
        w.writerow([
            r.get("tag"), (r.get("language") or {}).get("name"), r.get("engine"),
            r.get("tier"), r.get("workflow"), r.get("evidence"), r.get("availability"),
            r.get("s_lang"), r.get("s_content"), ci[0], ci[1], r.get("borderline"),
            r.get("reliability"), r.get("refusals"),
            (r.get("designator") or {}).get("winner"), r.get("inherited_from"),
            r.get("backtranslator"), r.get("judge"), r.get("method_version"),
            r.get("tested_at")])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition":
                                      'attachment; filename="llmlc-results.csv"'})


# -- the bench ----------------------------------------------------------

@app.post("/bench", status_code=201)
def bench_start(body: BenchStart, request: Request) -> dict:
    """Open a session over one language. Spends nothing until the first step.

    Gated exactly like `POST /scans`: it reaches a model with the user's own key
    and costs roughly 9 to 15 calls for one language. Cheaper than a scan is not
    the same as free.
    """
    _check_trigger_allowed(request)
    try:
        client = build_client()
    except NotConfigured as e:
        raise HTTPException(400, str(e)) from e

    asked = [m.strip() for m in (body.backtranslator or runner.DEFAULT_PANEL).split(",")
             if m.strip()]
    panel = [m for m in asked
             if runner.model_family(m) != runner.model_family(body.engine)]
    dropped = [m for m in asked if m not in panel]
    if not panel:
        raise HTTPException(400, "No back-translator left after excluding the model "
                                 "under test: a model grading itself measures "
                                 "self-consistency, not intelligibility.")
    judge = body.judge or settings.judge_model
    if (missing := check_models([body.engine, judge, *panel])):
        raise HTTPException(400, f"Not in the custom model list: {', '.join(missing)}.")

    scheme = load_scheme(body.scheme or settings.scheme)
    if scheme.get(body.tag) is None:
        raise HTTPException(404, f"No tag {body.tag!r} in scheme {scheme.meta.name!r}.")

    specs, modified = bench_sessions.specs_for(body.specs)
    if not specs:
        raise HTTPException(400, "No content specifications to run.")

    from llmlc.bt import RemoteBackTranslator
    from llmlc.db.qualcache import DbQualificationCache

    try:
        session = bench_sessions.start(
            engine=body.engine, tag=body.tag, scheme=scheme, client=client,
            backtranslators=[RemoteBackTranslator(client, m, body.pivot) for m in panel],
            judge_model=judge, pivot=body.pivot, mode=body.mode,
            specs=specs, specs_modified=modified,
            cache=DbQualificationCache(), sweep_all=body.sweep_all)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    # Said at start, because by the time the qualification step runs the dropped
    # member is simply absent and nothing explains why the panel is shorter than
    # the one that was asked for.
    session.plan["panel"] = panel
    session.plan["panel_dropped"] = dropped
    session.plan["judge"] = judge
    return session.public()


@app.get("/bench/help")
def bench_help() -> dict:
    """What each kind of step does, from the table beside the code.

    The page needs this before the first step exists, to say what the first call
    will do before spending it. Served rather than duplicated in the markup for
    the usual reason: a description that lives in two places stops matching the
    one that moves.
    """
    from llmlc.probe.ladder import STEP_HELP

    return {kind: {"title": title, "explains": explains}
            for kind, (title, explains) in STEP_HELP.items()}


@app.post("/bench/{session_id}/step")
def bench_step(session_id: str) -> dict:
    """Advance one step. The call that actually spends money.

    One step per request rather than a stream, because the point of interactive
    mode is that a person decides whether the next call happens.
    """
    session = bench_sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "No such bench session. They live in memory and do "
                                 "not survive a restart.")
    step = bench_sessions.advance(session, on_result=_save_bench_result)
    return {"step": step, "session": session.public()}


@app.get("/bench/{session_id}")
def bench_state(session_id: str) -> dict:
    session = bench_sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "No such bench session.")
    return session.public()


@app.delete("/bench/{session_id}")
def bench_close(session_id: str) -> dict:
    """Abandon a session. Every yield sits after the work it reports, so closing
    one mid-run cannot leave a call half-paid-for."""
    return {"closed": bench_sessions.close(session_id)}


@app.get("/specs")
def specs() -> list[dict]:
    """The shipped content specifications.

    Served rather than restated in the page because the bench lets them be
    edited, and the page has to be able to tell an edit from the original — a
    second copy in the markup would make every run look edited the first time
    a scenario was reworded here.
    """
    from llmlc.probe.specs import load_specs

    return [{"id": s.id, "scenario": s.scenario, "facts": list(s.facts)}
            for s in load_specs()]


@app.get("/bench")
def bench_list() -> dict:
    return {"sessions": bench_sessions.listing(),
            "max_sessions": bench_sessions.MAX_SESSIONS}


def _save_bench_result(result) -> None:
    """Store a finished bench run as a result row.

    Only reached for a run whose specifications were not edited -- `bench.py`
    enforces that -- so what lands here is the same measurement a scan would
    have produced, taken through whichever instrument the operator chose. It is
    keyed by that instrument like every other row (convention 4), so it sits
    beside a programme result rather than overwriting it.
    """
    from llmlc.db import create_all, session as db_session
    from llmlc.db.store import save as save_result

    create_all()
    profile = hardware.detect(settings.hardware_profile).profile
    with db_session() as s:
        save_result(s, result, job_id=None, hardware_profile=profile)
