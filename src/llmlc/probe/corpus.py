"""Raw generation corpus.

Every model call is written to disk with its prompt, designator and usage. This
is the durable asset: when the method changes, the corpus is re-graded offline
instead of re-running every model (docs/01). It is also what makes grading
testable without spending tokens.
"""
from __future__ import annotations

import json
import pathlib
import time
import uuid
from dataclasses import asdict, dataclass, field

DEFAULT_DIR = pathlib.Path("data/corpus")


@dataclass
class Record:
    kind: str                       # generation | backtranslation | judgement
    engine: str
    tag: str
    spec_id: str | None = None
    designator: str | None = None
    prompt: str = ""
    response: str | None = None
    error: str | None = None
    usage: dict = field(default_factory=dict)
    latency_s: float = 0.0
    meta: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    at: float = field(default_factory=time.time)


class Corpus:
    """Append-only JSONL, one file per run, optionally mirrored to the database.

    **The file is authoritative.** It is written first and a database failure
    never costs a record: the corpus is the one artifact that makes a re-grade
    possible without paying for the generations again, so it must survive
    anything the database does.

    The `generation` table has existed since S4 and went unused until the
    calibration study needed to re-grade old generations under a new scorer --
    which is a query, not a file scan. Mirroring is opt-in (`to_db=True`) so
    tests and ad-hoc runs need no database at all.
    """

    def __init__(self, path: pathlib.Path | None = None, *, to_db: bool = False,
                 job_id: int | None = None) -> None:
        self.path = path or DEFAULT_DIR / f"run_{int(time.time())}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")
        self.count = 0
        self.to_db = to_db
        self.job_id = job_id
        self.db_errors = 0

    def write(self, rec: Record) -> Record:
        self._fh.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
        self._fh.flush()
        self.count += 1
        if self.to_db:
            self._mirror(rec)
        return rec

    def _mirror(self, rec: Record) -> None:
        """Best-effort copy into the `generation` table.

        Swallows its own failures on purpose. The record is already on disk, and
        a scan that dies because a mirror write failed would lose far more than
        the mirror was worth.
        """
        try:
            from llmlc.db import session
            from llmlc.db.repo import record_generation
            with session() as s:
                record_generation(s, {
                    "job_id": self.job_id, "kind": rec.kind, "engine": rec.engine,
                    "tag": rec.tag, "spec_id": rec.spec_id, "designator": rec.designator,
                    "prompt": rec.prompt, "response": rec.response, "error": rec.error,
                    "usage": rec.usage or None, "latency_s": rec.latency_s,
                    "meta": rec.meta or None,
                })
        except Exception:  # noqa: BLE001 -- the file already has it
            self.db_errors += 1

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "Corpus":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
