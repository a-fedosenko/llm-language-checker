"""Running a scan, once, for every caller.

The CLI and the HTTP trigger must not be two implementations of "run a scan".
They differ only in how they report progress and in who is allowed to start one,
so everything else -- job row, item bookkeeping, budget, artifacts, finalisation
-- lives here and takes a callback.

Cancellation is cooperative and lives in `CANCELLED`: a scan spends real money on
someone else's API key, so the person watching it must be able to stop it without
killing the process the UI is served from.
"""
from __future__ import annotations

import pathlib
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from llmlc import hardware
from llmlc.bt import RemoteBackTranslator
from llmlc.client import OpenAICompatClient
from llmlc.config import settings
from llmlc.db import create_all, session
from llmlc.db.models import Job, JobItem
from llmlc.db.qualcache import DbQualificationCache
from llmlc.db.repo import add_job_items, create_job
from llmlc.db.store import save as save_result
from llmlc.export import write as write_artifacts
from llmlc.export.artifacts import METHOD_VERSION
from llmlc.probe.corpus import Corpus
from llmlc.probe.scan import ScanBudget, plan, scan
from llmlc.probe.specs import load_specs
from llmlc.scheme import load_scheme

DEFAULT_PANEL = "gemini-gemini-3-8-flash,deepseek-deepseek-v4-pro"

#: Job ids asked to stop. A set rather than a flag because the id is the handle
#: the UI already has, and because a cancelled job that has already finished
#: should be a no-op rather than an error.
CANCELLED: set[int] = set()
_lock = threading.Lock()


def cancel(job_id: int) -> None:
    with _lock:
        CANCELLED.add(job_id)


def is_cancelled(job_id: int) -> bool:
    with _lock:
        return job_id in CANCELLED


def running_job_id() -> int | None:
    """The scan currently in flight, if any.

    One writer at a time: SQLite is single-writer, and two scans would in any
    case interleave their spending against one budget nobody set.
    """
    from sqlalchemy import select
    create_all()
    with session() as s:
        return s.scalar(select(Job.id).where(Job.status == "running").order_by(Job.id.desc()))


def reap_orphans() -> list[int]:
    """Fail jobs left `running` by a process that is no longer here.

    A scan lives in the process that started it, so a `running` job at startup
    was orphaned by a crash or a restart. Left alone it is indistinguishable from
    work in progress: the UI would wait on it forever and `running_job_id` would
    refuse every new scan. Its finished items keep their `done` status, so the
    rest is still the resume set.
    """
    from sqlalchemy import select
    create_all()
    with session() as s:
        orphans = list(s.scalars(select(Job).where(Job.status == "running")))
        for job in orphans:
            job.status = "failed"
            job.error = ("Interrupted: the process running this scan exited. "
                         "Re-run to continue from the classes that did not finish.")
            job.finished_at = datetime.now(timezone.utc)
        return [j.id for j in orphans]


class ScanRefused(Exception):
    """A scan could not be started. The message is shown to the user verbatim."""


@dataclass
class ScanRequest:
    engine: str
    tags: list[str]
    scheme: str | None = None
    backtranslator: str = DEFAULT_PANEL
    judge: str | None = None
    pivot: str = "en"
    max_calls: int | None = None
    sweep_all: bool = False
    out: str = "data/results"

    @property
    def panel(self) -> list[str]:
        """The back-translator panel, with the model under test removed.

        A model back-translating itself measures self-consistency, not
        intelligibility (protocol 005).
        """
        return [m.strip() for m in self.backtranslator.split(",")
                if m.strip() and m.strip() != self.engine]


@dataclass
class ScanOutcome:
    job_id: int
    result: object | None = None
    artifacts: tuple[str, str] | None = None
    corpus_path: str | None = None
    calls: dict[str, int] = field(default_factory=dict)
    error: str | None = None


def prepare(req: ScanRequest):
    """Validate a request without spending anything. Returns (scheme, groups, unknown)."""
    if not settings.aggregator_base_url or not settings.aggregator_admin_api_key:
        raise ScanRefused("No endpoint configured. Copy .env.example to .env and fill it in.")
    if not req.tags:
        raise ScanRefused("No languages selected.")
    if not req.panel:
        raise ScanRefused("No back-translator left after excluding the model under test.")
    scheme = load_scheme(req.scheme or settings.scheme)
    groups, unknown = plan(scheme, req.tags)
    if not groups:
        raise ScanRefused(f"None of the requested tags are in scheme {scheme.meta.name!r}: "
                          f"{', '.join(unknown[:8])}")
    return scheme, groups, unknown


def create(req: ScanRequest) -> int:
    """Create the job row and its items, and return the id.

    Separate from `execute` so an HTTP caller can be handed an id to watch before
    the first model call is made.
    """
    scheme, groups, unknown = prepare(req)
    create_all()
    profile = hardware.detect(settings.hardware_profile).profile
    with session() as s:
        job = create_job(s, engine=req.engine, scheme=scheme.meta.name, pivot=req.pivot,
                         judge=req.judge or settings.judge_model,
                         backtranslator_panel=req.panel, method_version=METHOD_VERSION,
                         hardware_profile=profile, status="running",
                         requested_tags=req.tags, unknown_tags=unknown,
                         max_calls=req.max_calls)
        add_job_items(s, job, groups)
        return job.id


def execute(req: ScanRequest, job_id: int, *, on_result=None) -> ScanOutcome:
    """Run a job that `create` has already registered.

    Every exit path finalises the job row. A job left `running` after the process
    that owned it has gone is indistinguishable from one still working, and the
    UI would wait on it forever.
    """
    scheme, groups, _ = prepare(req)
    profile = hardware.detect(settings.hardware_profile).profile
    client = OpenAICompatClient(settings.aggregator_base_url, settings.aggregator_admin_api_key)
    bts = [RemoteBackTranslator(client, m, req.pivot) for m in req.panel]
    budget = ScanBudget(max_calls=req.max_calls)
    out = ScanOutcome(job_id=job_id)

    def progress(r) -> None:
        with session() as s:
            save_result(s, r, job_id=job_id, hardware_profile=profile)
            if not r.inherited_from and r.language is not None:
                _finish_item(s, job_id, r.language.cls)
        if on_result:
            on_result(r)

    try:
        with Corpus() as corpus:
            result = scan(scheme=scheme, tags=req.tags, engine=req.engine, client=client,
                          backtranslators=bts, judge_model=req.judge or settings.judge_model,
                          specs=load_specs(), corpus=corpus, pivot=req.pivot,
                          sweep_all=req.sweep_all, cache=DbQualificationCache(),
                          budget=budget, on_result=progress,
                          should_stop=lambda: is_cancelled(job_id))
            out.corpus_path = str(corpus.path)
        out.result = result
        out.calls = result.calls
        for r in result.results:
            out.artifacts = write_artifacts(r, pathlib.Path(req.out))
        _finalise(job_id, status="stopped" if result.stopped_early else "done",
                  calls_used=sum(result.calls.values()),
                  error=f"stopped: {result.stop_reason}" if result.stopped_early else None)
    except Exception as e:  # noqa: BLE001 -- recorded on the job, then re-raised
        out.error = f"{type(e).__name__}: {e}"
        _finalise(job_id, status="failed", calls_used=budget.calls, error=out.error)
        raise
    finally:
        with _lock:
            CANCELLED.discard(job_id)
    return out


def run(req: ScanRequest, *, on_result=None) -> ScanOutcome:
    return execute(req, create(req), on_result=on_result)


def run_in_background(req: ScanRequest, job_id: int) -> threading.Thread:
    """Run an already-created job off the request thread.

    A thread, not a process or a queue: one scan at a time, in the same process
    that owns the SQLite file, is the whole concurrency story here. The work is
    entirely network-bound, so the GIL costs nothing.
    """
    def target() -> None:
        try:
            execute(req, job_id)
        except Exception:  # noqa: BLE001 -- already recorded on the job row
            pass

    t = threading.Thread(target=target, name=f"llmlc-scan-{job_id}", daemon=True)
    t.start()
    return t


def _finish_item(s, job_id: int, cls: str) -> None:
    from sqlalchemy import select
    item = s.scalar(select(JobItem).where(JobItem.job_id == job_id, JobItem.cls == cls))
    if item is not None:
        item.status = "done"
        item.finished_at = datetime.now(timezone.utc)


def _finalise(job_id: int, *, status: str, calls_used: int, error: str | None) -> None:
    with session() as s:
        job = s.get(Job, job_id)
        if job is None:
            return
        job.status = status
        job.calls_used = calls_used
        job.error = error
        job.finished_at = datetime.now(timezone.utc)
        # Unfinished items stay `pending` deliberately: that is the resume set,
        # and rewriting them to "stopped" would erase the only record of which
        # classes a cancelled scan never reached.
