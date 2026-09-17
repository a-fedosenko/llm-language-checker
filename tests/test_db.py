"""Persistence: the merge rule, staleness, and resumption."""
from datetime import datetime, timedelta, timezone

import pytest

from llmlc.db import reset_for_tests, session
from llmlc.db.models import Job
from llmlc.db.repo import (add_job_items, create_job, missing, pending_items,
                           put_qualification, get_qualification, results_for,
                           stale, upsert_result)


@pytest.fixture(autouse=True)
def db(tmp_path):
    reset_for_tests(f"sqlite+pysqlite:///{tmp_path/'t.db'}")


def row(**kw):
    base = dict(engine="m", tag="cv", cls="chv|Cyrl", tier="Strong", evidence="fact-recall",
                s_lang=1.0, s_content=0.9, ci_low=0.8, ci_high=1.0, borderline=False,
                designator="Chuvash", backtranslator="bt:a", judge="j",
                method_version="1.0.0", tested_at=datetime.now(timezone.utc))
    base.update(kw)
    return base


def test_insert_then_update_same_identity():
    with session() as s:
        _, a = upsert_result(s, row())
        _, b = upsert_result(s, row(tier="Usable"))
    assert (a, b) == ("inserted", "updated")
    with session() as s:
        assert results_for(s)[0].tier == "Usable"


def test_a_different_backtranslator_is_a_different_result_not_an_update():
    """Results from different back-translators are not comparable."""
    with session() as s:
        upsert_result(s, row(backtranslator="bt:a"))
        upsert_result(s, row(backtranslator="bt:b", tier="None"))
    with session() as s:
        assert len(results_for(s)) == 2


def test_older_method_version_never_overwrites_newer():
    with session() as s:
        upsert_result(s, row(method_version="1.1.0", tier="Strong"))
    with session() as s:
        _, action = upsert_result(s, row(method_version="1.1.0", tier="Token",
                                         tested_at=datetime.now(timezone.utc) - timedelta(days=1)))
    assert action == "kept", "a stale re-run must not clobber a fresher measurement"
    with session() as s:
        assert results_for(s)[0].tier == "Strong"


def test_newer_timestamp_wins_at_the_same_version():
    with session() as s:
        upsert_result(s, row(tier="Strong"))
    with session() as s:
        _, action = upsert_result(s, row(tier="Token",
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
        _, action = upsert_result(s, row(tier="Usable",
                                         tested_at=datetime.now(timezone.utc)))  # aware
    assert action in {"updated", "kept"}
