"""Persistence: the merge rule, staleness, and resumption."""
from datetime import datetime, timedelta, timezone

import pytest

from llmlc.db import reset_for_tests, session
from llmlc.db.models import Job, Result
from llmlc.db.repo import (add_job_items, create_job, missing, pending_items,
                           put_qualification, get_qualification, results_for,
                           stale, upsert_result)


@pytest.fixture(autouse=True)
def db(tmp_path):
    reset_for_tests(f"sqlite+pysqlite:///{tmp_path/'t.db'}")


def row(**kw):
    base = dict(engine="m", tag="cv", cls="chv|Cyrl", tier="Proficient", evidence="fact-recall",
                s_lang=1.0, s_content=0.9, ci_low=0.8, ci_high=1.0, borderline=False,
                designator="Chuvash", backtranslator="bt:a", judge="j",
                method_version="1.0.0", tested_at=datetime.now(timezone.utc))
    base.update(kw)
    return base


def test_insert_then_update_same_identity():
    # Explicit, increasing timestamps rather than two calls to `now()`. The
    # merge rule compares `tested_at` when the method versions match, so the
    # assertion otherwise depends on the clock advancing between two statements
    # -- which it usually does. Seen to fail once in a full-suite run and not
    # reproducible after; a test whose outcome depends on wall-clock resolution
    # is worth making deterministic whether or not that was the cause.
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with session() as s:
        _, a = upsert_result(s, row(tested_at=t0))
        _, b = upsert_result(s, row(tier="Assisted", tested_at=t0 + timedelta(seconds=1)))
    assert (a, b) == ("inserted", "updated")
    with session() as s:
        assert results_for(s)[0].tier == "Assisted"


def test_a_different_backtranslator_is_a_different_result_not_an_update():
    """Results from different back-translators are not comparable."""
    with session() as s:
        upsert_result(s, row(backtranslator="bt:a"))
        upsert_result(s, row(backtranslator="bt:b", tier="None"))
    with session() as s:
        assert len(results_for(s)) == 2


def test_older_method_version_never_overwrites_newer():
    with session() as s:
        upsert_result(s, row(method_version="1.1.0", tier="Proficient"))
    with session() as s:
        _, action = upsert_result(s, row(method_version="1.1.0", tier="Unusable",
                                         tested_at=datetime.now(timezone.utc) - timedelta(days=1)))
    assert action == "kept", "a stale re-run must not clobber a fresher measurement"
    with session() as s:
        assert results_for(s)[0].tier == "Proficient"


def test_newer_timestamp_wins_at_the_same_version():
    with session() as s:
        upsert_result(s, row(tier="Proficient"))
    with session() as s:
        _, action = upsert_result(s, row(tier="Unusable",
                                         tested_at=datetime.now(timezone.utc) + timedelta(hours=1)))
    assert action == "updated"


def test_stale_lists_results_behind_the_current_method():
    with session() as s:
        upsert_result(s, row(tag="cv", method_version="1.0.0"))
        upsert_result(s, row(tag="de", method_version="2.0.0"))
    with session() as s:
        assert [r.tag for r in stale(s, "2.0.0")] == ["cv"]
        assert stale(s, "1.0.0") == []


def test_version_comparison_is_numeric_not_lexicographic():
    with session() as s:
        upsert_result(s, row(method_version="1.10.0"))
    with session() as s:
        assert stale(s, "1.9.0") == [], "1.10.0 is newer than 1.9.0"


def test_missing_reports_unmeasured_tags():
    with session() as s:
        upsert_result(s, row(tag="cv"))
    with session() as s:
        assert missing(s, "m", ["cv", "de", "fr"], "1.0.0") == ["de", "fr"]


def test_qualification_cache_roundtrip():
    with session() as s:
        put_qualification(s, dict(backtranslator="bt:a", tag="cv", status="qualified",
                                  score=0.9, kind="facts", method_version="1.0.0"))
    with session() as s:
        assert get_qualification(s, "bt:a", "cv", "1.0.0").status == "qualified"
        assert get_qualification(s, "bt:b", "cv", "1.0.0") is None


def test_job_resumes_from_pending_items():
    with session() as s:
        job = create_job(s, engine="m", judge="j", method_version="1.0.0")
        add_job_items(s, job, {"chv|Cyrl": ["cv"], "deu|Latn": ["de", "de-AT"]})
        job_id = job.id
    with session() as s:
        items = pending_items(s, job_id)
        assert len(items) == 2
        items[0].status = "done"
    with session() as s:
        remaining = pending_items(s, job_id)
        assert len(remaining) == 1, "a killed job restarts from where it stopped"


def test_naive_timestamps_from_sqlite_do_not_break_the_merge_rule():
    """SQLite drops tzinfo on round-trip; Postgres keeps it. The comparison must
    work on both rather than raising on one."""
    with session() as s:
        upsert_result(s, row(tested_at=datetime.now()))          # naive
    with session() as s:
        _, action = upsert_result(s, row(tier="Assisted",
                                         tested_at=datetime.now(timezone.utc)))  # aware
    assert action in {"updated", "kept"}


def test_non_sqlite_url_is_rejected_with_a_reason():
    """One backend, deliberately: supporting two cost us a timezone bug."""
    from llmlc.config import settings
    from llmlc.db.session import url
    old = settings.database_url
    try:
        settings.database_url = "postgresql+psycopg://x/y"
        with pytest.raises(ValueError, match="single-tenant"):
            url()
    finally:
        settings.database_url = old


def test_wal_is_enabled_for_reader_writer_concurrency():
    """The CLI writes on the host while the UI reads from the container through
    the same file; in rollback-journal mode a writer would block readers."""
    from sqlalchemy import text
    from llmlc.db import engine
    with engine().connect() as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"
        assert c.execute(text("PRAGMA busy_timeout")).scalar() == 5000


# -- the deterministic negative is instrument-independent ---------------------

def test_a_gate_verdict_and_a_scored_verdict_are_one_result_not_two():
    """The bug this fixes: `kk-Latn` came back settled-by-the-gate on one run and
    scored on the next, and the two rows never collided because "(not needed)"
    sat in an identity column. One language, one model, one method — one row."""
    from llmlc.db.models import NO_INSTRUMENT
    with session() as s:
        upsert_result(s, row(tag="kk-Latn", backtranslator=NO_INSTRUMENT,
                             evidence="deterministic-negative", tier="None"))
        _, status = upsert_result(s, row(tag="kk-Latn", backtranslator="remote:bt",
                                         evidence="unverified", tier="None"))
    assert status == "updated"
    with session() as s:
        rows = [r for r in results_for(s) if r.tag == "kk-Latn"]
    assert len(rows) == 1
    assert rows[0].backtranslator == "remote:bt", "the real instrument replaces the placeholder"


def test_it_collapses_in_the_other_direction_too():
    from llmlc.db.models import NO_INSTRUMENT
    with session() as s:
        upsert_result(s, row(tag="kk-Latn", backtranslator="remote:bt", evidence="unverified"))
        upsert_result(s, row(tag="kk-Latn", backtranslator=NO_INSTRUMENT,
                             evidence="deterministic-negative"))
    with session() as s:
        rows = [r for r in results_for(s) if r.tag == "kk-Latn"]
    assert len(rows) == 1
    assert rows[0].evidence == "deterministic-negative"


def test_real_instruments_still_produce_separate_results():
    """Protocol 005 stands: results from different back-translators are not
    comparable, so they remain different results rather than updates."""
    with session() as s:
        upsert_result(s, row(backtranslator="remote:a"))
        upsert_result(s, row(backtranslator="remote:b", tier="None"))
    with session() as s:
        assert len({r.backtranslator for r in results_for(s)}) == 2


def test_existing_duplicates_are_folded_into_one_row():
    """Rows left behind by the old rule converge on the next write rather than
    surviving as a second answer to the same question."""
    from datetime import datetime, timedelta, timezone

    from llmlc.db.models import NO_INSTRUMENT
    now = datetime.now(timezone.utc)
    with session() as s:
        s.add(Result(**row(tag="kk-Latn", backtranslator=NO_INSTRUMENT,
                           evidence="deterministic-negative", tested_at=now - timedelta(days=2))))
        s.add(Result(**row(tag="kk-Latn", backtranslator="remote:bt",
                           evidence="unverified", tested_at=now - timedelta(days=1))))
    with session() as s:
        assert len([r for r in results_for(s) if r.tag == "kk-Latn"]) == 2
        upsert_result(s, row(tag="kk-Latn", backtranslator="remote:bt",
                             evidence="fact-recall", tier="Proficient", tested_at=now))
    with session() as s:
        rows = [r for r in results_for(s) if r.tag == "kk-Latn"]
    assert len(rows) == 1 and rows[0].tier == "Proficient"


def test_a_stale_rerun_still_cannot_clobber_a_fresher_row():
    """The collapse must not weaken the merge rule."""
    from datetime import datetime, timedelta, timezone

    from llmlc.db.models import NO_INSTRUMENT
    now = datetime.now(timezone.utc)
    with session() as s:
        upsert_result(s, row(tag="kk-Latn", backtranslator="remote:bt",
                             tier="Proficient", tested_at=now))
        _, status = upsert_result(s, row(tag="kk-Latn", backtranslator=NO_INSTRUMENT,
                                         tier="None", tested_at=now - timedelta(days=1)))
    assert status == "kept"
    with session() as s:
        assert [r.tier for r in results_for(s) if r.tag == "kk-Latn"] == ["Proficient"]


def test_the_capability_migration_matches_the_model(tmp_path):
    """A hand-written migration and a declarative model are two statements of
    one schema, and they drift silently: the model is what tests exercise, the
    migration is what a real database gets. A column present in one and not the
    other shows up as an error only on somebody else's machine.
    """
    import sqlalchemy as sa

    from llmlc.db.models import Base, Capability

    url = f"sqlite+pysqlite:///{tmp_path/'mig.db'}"
    engine = sa.create_engine(url)

    import pathlib

    from alembic import command
    from alembic.config import Config

    from llmlc.config import settings

    root = pathlib.Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))

    # `alembic/env.py` overrides `sqlalchemy.url` with `session.url()`, so
    # setting it on the config is not enough -- without this the test migrates
    # the *real* database, which already has its tables and fails with "table
    # job already exists". Found exactly that way.
    before = settings.database_url
    settings.database_url = url
    try:
        command.upgrade(cfg, "head")
    finally:
        settings.database_url = before

    migrated = {c["name"] for c in sa.inspect(engine).get_columns("capability")}
    declared = {c.name for c in Capability.__table__.columns}
    assert migrated == declared, f"drifted: {migrated ^ declared}"
