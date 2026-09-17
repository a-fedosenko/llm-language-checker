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
