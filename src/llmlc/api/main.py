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

from llmlc import __version__, hardware, runner
from llmlc.api import results as results_store
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
    yield


app = FastAPI(
    lifespan=lifespan,
    title="llm-language-checker",
    version=__version__,
    description="Empirical, heuristic checks of which languages a model can actually produce. "
                "Run locally; results are evidence, not proof.",
)


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
) -> dict:
    items = list(get_scheme(settings.scheme).languages.values())
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
        q=q, limit=limit, offset=offset))


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


@app.get("/engines")
def engines() -> dict:
    """Models available to scan, and models already measured.

    `available` comes from the aggregator's model list when one is configured --
    the UI needs a picker, and typing a model name from memory is how you spend
    a budget on a typo. It is advisory: the list is the gateway's, not ours, and
    a name missing from it is still allowed.
    """
    measured = sorted(results_store.page(
        results_store.Query(limit=1)).get("summary", {}).get("engines", {}))
    return {"available": _model_list(), "measured": measured,
            "judge": settings.judge_model,
            "backtranslator_panel": runner.DEFAULT_PANEL.split(",")}


@lru_cache(maxsize=1)
def _model_list() -> list[str]:
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


@app.get("/", include_in_schema=False)
def index():
    page = STATIC / "index.html"
    if not page.exists():
        return {"message": "UI not installed", "docs": "/docs"}
    return FileResponse(page)


# -- jobs and the scan trigger -----------------------------------------------

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


def _trigger_state() -> dict:
    return {"mode": settings.scan_trigger,
            "max_calls": settings.scan_trigger_max_calls,
            "configured": bool(settings.aggregator_base_url
                               and settings.aggregator_admin_api_key)}


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
