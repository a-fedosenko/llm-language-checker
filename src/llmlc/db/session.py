"""Engine and session handling.

Defaults to SQLite so the tool runs with no services at all -- `llmlc scan`
should work on a laptop with nothing installed. Postgres is used when
DATABASE_URL points at it, which is what docker compose does.
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
    return settings.database_url or DEFAULT_SQLITE


def engine():
    global _engine, _Session
    if _engine is None:
        u = url()
        if u.startswith("sqlite"):
            pathlib.Path("data").mkdir(parents=True, exist_ok=True)
        _engine = create_engine(u, future=True,
                                connect_args={"check_same_thread": False}
                                if u.startswith("sqlite") else {})
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
