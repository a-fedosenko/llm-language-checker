"""Database-backed qualification cache.

Same interface as the file-based cache so the ladder is unchanged; persisting it
means a qualification survives beyond a single run and is shared across jobs.
"""
from __future__ import annotations

from llmlc.bt.qualify import Qualification, QualStatus
from llmlc.db import session
from llmlc.db.repo import get_qualification, put_qualification
from llmlc.export.artifacts import METHOD_VERSION


class DbQualificationCache:
    def __init__(self, method_version: str = METHOD_VERSION) -> None:
        self.method_version = method_version

    def get(self, bt_id: str, tag: str) -> Qualification | None:
        with session() as s:
            row = get_qualification(s, bt_id, tag, self.method_version)
            if row is None:
                return None
            return Qualification(QualStatus(row.status), row.score, bt_id, tag,
                                 row.kind or "", row.detail or "")

    def put(self, q: Qualification) -> None:
        with session() as s:
            put_qualification(s, {"backtranslator": q.backtranslator, "tag": q.tag,
                                  "status": q.status.value, "score": q.score,
                                  "kind": q.kind or None, "detail": q.detail or None,
                                  "method_version": self.method_version})


class DbCapabilityRecord:
    """`panel.CapabilityRecord` backed by the database.

    Same surface as the in-memory one, deliberately: `put`, `get`, `known`,
    `rows` and nothing that answers "is this attestor trustworthy". The
    invariant that the record routes but never vouches has to survive
    persistence, and the way to make sure of that is for the persistent version
    to be unable to express anything the in-memory one cannot.
    """

    def __init__(self, method_version: str = METHOD_VERSION) -> None:
        self.method_version = method_version

    def put(self, cap):
        from llmlc.db.repo import put_capability

        with session() as s:
            put_capability(s, {
                "model": cap.key.model, "tag": cap.key.tag,
                "role": cap.key.role.value, "script": cap.key.script,
                "qualified": cap.qualified, "confidence": cap.confidence,
                "probes": list(cap.probes) or None, "detail": cap.detail or None,
                "method_version": self.method_version,
            })
        return cap

    def get(self, key):
        from llmlc.probe.panel import Capability
        from llmlc.db.repo import get_capability

        with session() as s:
            row = get_capability(s, key.model, key.tag, key.role.value,
                                 self.method_version, key.script)
            if row is None:
                return None
            return Capability(key=key, qualified=row.qualified,
                              confidence=row.confidence, probes=row.probes or [],
                              detail=row.detail or "",
                              measured_at=row.measured_at.timestamp())

    def known(self, attestors: list[str], *, tag: str, role,
              script: str | None = None) -> dict[str, bool]:
        from llmlc.db.repo import capabilities_for

        with session() as s:
            rows = {r.model: r.qualified for r in
                    capabilities_for(s, tag, role.value, self.method_version, script)}
        return {a: rows[a] for a in attestors if a in rows}

    def rows(self) -> list:
        from llmlc.db.models import Capability
        from sqlalchemy import select

        from llmlc.probe.panel import Capability as Cap, CapabilityKey, Role

        with session() as s:
            out = []
            for r in s.scalars(select(Capability).where(
                    Capability.method_version == self.method_version)):
                out.append(Cap(key=CapabilityKey(r.model, r.tag, Role(r.role), r.script),
                               qualified=r.qualified, confidence=r.confidence,
                               probes=r.probes or [], detail=r.detail or "",
                               measured_at=r.measured_at.timestamp()))
            return out
