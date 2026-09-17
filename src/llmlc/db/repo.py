"""Reading and writing results.

The merge rule lives here and nowhere else: **higher method_version wins, then
newer tested_at**. A result is never silently replaced by an older one.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from llmlc.db.models import Generation, Job, JobItem, Qualification, Result


def _aware(dt: datetime | None) -> datetime | None:
    """Normalise to aware UTC.

    SQLite discards tzinfo on round-trip while Postgres preserves it, so stored
    timestamps must be normalised before they are compared or the merge rule
    raises on one backend and not the other.
    """
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _version_key(v: str | None) -> tuple:
    """Sortable form of a dotted version, tolerating odd strings."""
    parts = (v or "0").split(".")
    out = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return tuple(out)


def upsert_result(s: Session, row: dict) -> tuple[Result, str]:
    """Insert or update one result. Returns (row, "inserted"|"updated"|"kept").

    `kept` means an existing row was newer by method version or timestamp and was
    left alone -- a stale re-run must never overwrite a fresher measurement.
    """
    existing = s.scalar(select(Result).where(
        Result.engine == row["engine"], Result.tag == row["tag"],
        Result.method_version == row["method_version"],
        Result.backtranslator == row["backtranslator"]))

    if existing is None:
        obj = Result(**row)
        s.add(obj)
        return obj, "inserted"

    new_at = _aware(row.get("tested_at")) or datetime.now(timezone.utc)
    old_at = _aware(existing.tested_at)
    new_v, old_v = _version_key(row["method_version"]), _version_key(existing.method_version)
    if new_v < old_v or (new_v == old_v and old_at is not None and new_at < old_at):
        return existing, "kept"

    for k, v in row.items():
        setattr(existing, k, v)
    return existing, "updated"


def results_for(s: Session, *, engine: str | None = None, tier: str | None = None,
                evidence: str | None = None, limit: int | None = None) -> list[Result]:
    stmt = select(Result)
    if engine:
        stmt = stmt.where(Result.engine == engine)
    if tier:
        stmt = stmt.where(Result.tier == tier)
    if evidence:
        stmt = stmt.where(Result.evidence == evidence)
    stmt = stmt.order_by(Result.engine, Result.tag)
    if limit:
        stmt = stmt.limit(limit)
    return list(s.scalars(stmt))


def stale(s: Session, current_method_version: str, engine: str | None = None) -> list[Result]:
    """Results measured under an older method version -- the re-run candidates.

    This is the other half of incremental growth: new languages are a batch over
    new tags, and a method change is a batch over whatever this returns.
    """
    rows = results_for(s, engine=engine)
    cur = _version_key(current_method_version)
    return [r for r in rows if _version_key(r.method_version) < cur]


def missing(s: Session, engine: str, tags: list[str], method_version: str) -> list[str]:
    """Requested tags with no result at this method version -- the other re-run set."""
    have = {r.tag for r in s.scalars(select(Result).where(
        Result.engine == engine, Result.method_version == method_version))}
    return [t for t in tags if t not in have]


def record_generation(s: Session, row: dict) -> Generation:
    obj = Generation(**row)
    s.add(obj)
    return obj


def get_qualification(s: Session, backtranslator: str, tag: str,
                      method_version: str) -> Qualification | None:
    return s.scalar(select(Qualification).where(
        Qualification.backtranslator == backtranslator, Qualification.tag == tag,
        Qualification.method_version == method_version))


def put_qualification(s: Session, row: dict) -> Qualification:
    existing = get_qualification(s, row["backtranslator"], row["tag"], row["method_version"])
    if existing:
        for k, v in row.items():
            setattr(existing, k, v)
        return existing
    obj = Qualification(**row)
    s.add(obj)
    return obj


def create_job(s: Session, **kw) -> Job:
    job = Job(**kw)
    s.add(job)
    s.flush()
    return job


def add_job_items(s: Session, job: Job, groups: dict[str, list[str]]) -> None:
    for cls, members in groups.items():
        s.add(JobItem(job_id=job.id, cls=cls, representative=members[0], members=members))


def pending_items(s: Session, job_id: int) -> list[JobItem]:
    """Items still to do. A killed job resumes from here rather than from zero."""
    return list(s.scalars(select(JobItem).where(
        JobItem.job_id == job_id, JobItem.status.in_(("pending", "running")))
        .order_by(JobItem.id)))
