"""The shared scan runner: job bookkeeping, cancellation, and finalisation.

The CLI and the HTTP trigger are the same code path, so these cover both. No
network: `scan` itself is stubbed, because what is under test here is what
happens around it.
"""
import pytest

from llmlc import runner
from llmlc.config import settings
from llmlc.db import reset_for_tests, session
from llmlc.db.models import Job
from llmlc.db.repo import pending_items
from llmlc.probe.scan import ScanBudget, ScanResult, scan


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    reset_for_tests(f"sqlite+pysqlite:///{tmp_path/'t.db'}")
    monkeypatch.setattr(settings, "aggregator_base_url", "https://example.invalid")
    monkeypatch.setattr(settings, "aggregator_admin_api_key", "k")
    yield
    runner.CANCELLED.clear()


def req(**kw) -> runner.ScanRequest:
    base = dict(engine="m", tags=["de", "de-AT", "fr"], max_calls=50)
    return runner.ScanRequest(**{**base, **kw})


def test_the_panel_never_contains_the_model_under_test():
    r = runner.ScanRequest(engine="m", tags=["de"], backtranslator="a,m,b")
    assert r.panel == ["a", "b"]


def test_create_registers_one_item_per_class_not_per_tag():
    job_id = runner.create(req())
    with session() as s:
        job = s.get(Job, job_id)
        assert job.status == "running"
        assert {i.cls for i in job.items} == {"deu|Latn", "fra|Latn"}
        assert sorted(i.representative for i in job.items) == ["de", "fr"]


def test_unknown_tags_are_recorded_on_the_job_rather_than_dropped():
    job_id = runner.create(req(tags=["de", "zz-nope"]))
    with session() as s:
        assert s.get(Job, job_id).unknown_tags == ["zz-nope"]


def test_refuses_without_an_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "aggregator_admin_api_key", None)
    with pytest.raises(runner.ScanRefused):
        runner.create(req())


def test_a_failed_scan_finalises_the_job_instead_of_leaving_it_running(monkeypatch):
    """A job left `running` after its process is gone looks identical to one still
    working, and the UI would wait on it forever."""
    def boom(**kw):
        raise RuntimeError("gateway on fire")
    monkeypatch.setattr(runner, "scan", boom)

    job_id = runner.create(req())
    with pytest.raises(RuntimeError):
        runner.execute(req(), job_id)
    with session() as s:
        job = s.get(Job, job_id)
        assert job.status == "failed"
        assert "gateway on fire" in job.error
        assert job.finished_at is not None


def test_a_cancelled_scan_stops_and_keeps_its_unreached_classes_pending(monkeypatch):
    seen = []

    def fake_scan(**kw):
        # Stand in for the real loop: check the stop predicate between classes.
        out = ScanResult()
        for cls in ("deu|Latn", "fra|Latn"):
            if kw["should_stop"]():
                out.stopped_early, out.stop_reason = True, "cancelled"
                break
            seen.append(cls)
            out.classes_probed += 1
        return out

    monkeypatch.setattr(runner, "scan", fake_scan)
    job_id = runner.create(req())
    runner.cancel(job_id)
    runner.execute(req(), job_id)

    assert seen == [], "cancellation is checked before the first class too"
    with session() as s:
        job = s.get(Job, job_id)
        assert job.status == "stopped"
        assert "cancelled" in job.error
        assert len(pending_items(s, job_id)) == 2, "unreached classes are the resume set"


def test_cancellation_is_cleared_once_the_job_ends(monkeypatch):
    monkeypatch.setattr(runner, "scan", lambda **kw: ScanResult())
    job_id = runner.create(req())
    runner.cancel(job_id)
    runner.execute(req(), job_id)
    assert not runner.is_cancelled(job_id), "a stale flag would cancel a reused id"


def test_running_job_id_reports_the_one_writer():
    assert runner.running_job_id() is None
    job_id = runner.create(req())
    assert runner.running_job_id() == job_id


def test_scan_checks_the_stop_predicate_between_classes(monkeypatch):
    """The predicate is wired into the real `scan`, not only the fake one above."""
    from llmlc.scheme import load_scheme
    out = scan(scheme=load_scheme("default"), tags=["de", "fr"], engine="m",
               client=None, backtranslators=[], judge_model="j", specs=[],
               corpus=None, budget=ScanBudget(), should_stop=lambda: True)
    assert out.stopped_early and out.stop_reason == "cancelled"
    assert out.classes_probed == 0, "nothing was spent"


def test_orphaned_jobs_are_reaped_rather_than_blocking_every_future_scan():
    """A `running` job whose process is gone looks exactly like one still working."""
    job_id = runner.create(req())
    assert runner.reap_orphans() == [job_id]
    with session() as s:
        job = s.get(Job, job_id)
        assert job.status == "failed"
        assert "Interrupted" in job.error
        assert len(pending_items(s, job_id)) == 2, "the resume set survives the reap"
    assert runner.running_job_id() is None
