"""Engine and session handling.

**SQLite, deliberately.** This is a single-tenant local tool with one writer and
a few thousand rows; a database server would be the same cargo cult the
deployment pivot removed when it deleted Kafka, Redis and Nginx. It also means
`llmlc scan` works with nothing installed and no services running, which is what
the self-hosted promise requires.

Supporting two backends had a measurable cost -- SQLite discards tzinfo on
round-trip while Postgres preserves it, which broke the merge rule on one and
not the other. One backend, one set of behaviours.

If this is ever hosted for concurrent writers, the job table is the seam and the
URL is a one-line change.
"""
from __future__ import annotations

import pathlib
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from llmlc.config import settings
from llmlc.db.models import Base

DEFAULT_SQLITE = "sqlite+pysqlite:///data/llmlc.db"

_engine = None
_Session: sessionmaker | None = None


def url() -> str:
    u = settings.database_url or DEFAULT_SQLITE
    if not u.startswith("sqlite"):
        raise ValueError(
            f"Only SQLite is supported; got {u.split(':')[0]!r}. "
            "This is a single-tenant local tool -- see docs/03.")
    return u


def engine():
    global _engine, _Session
    if _engine is None:
        u = url()
        if u.startswith("sqlite"):
            pathlib.Path("data").mkdir(parents=True, exist_ok=True)
        _engine = create_engine(u, future=True,
                                connect_args={"check_same_thread": False})
        _Session = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def create_all() -> None:
    """Create tables directly.

    Alembic owns migrations for Postgres; this exists so a fresh SQLite file and
    the test suite need no migration step.
    """
    Base.metadata.create_all(engine())


@contextmanager
def session() -> Iterator[Session]:
    engine()
    assert _Session is not None
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def reset_for_tests(database_url: str) -> None:
    global _engine, _Session
    settings.database_url = database_url
    _engine, _Session = None, None
    create_all()
