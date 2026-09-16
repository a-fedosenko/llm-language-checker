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
    """Append-only JSONL, one file per run."""

    def __init__(self, path: pathlib.Path | None = None) -> None:
        self.path = path or DEFAULT_DIR / f"run_{int(time.time())}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")
        self.count = 0

    def write(self, rec: Record) -> Record:
        self._fh.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
        self._fh.flush()
        self.count += 1
        return rec

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "Corpus":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
