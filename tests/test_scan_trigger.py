"""The one endpoint that can spend money.

`POST /scans` is the only write in the API and the only thing here that costs the
user anything, so its guards are tested as carefully as the scoring is: who may
call it, what it refuses, and that nothing starts when it refuses.
"""
import pytest
from fastapi.testclient import TestClient

from llmlc import runner
from llmlc.api.main import app
from llmlc.config import settings
from llmlc.db import reset_for_tests, session
from llmlc.db.models import Job


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    reset_for_tests(f"sqlite+pysqlite:///{tmp_path/'t.db'}")
    monkeypatch.setattr(settings, "aggregator_base_url", "https://example.invalid")
    monkeypatch.setattr(settings, "aggregator_admin_api_key", "k")
    monkeypatch.setattr(settings, "scan_trigger", "loopback")
    monkeypatch.setattr(settings, "scan_trigger_max_calls", 500)
    yield
    runner.CANCELLED.clear()


@pytest.fixture
def client():
    # TestClient presents 'testclient' as the peer address, which is not
    # loopback -- exactly the situation the guard exists for.
    return TestClient(app, client=("127.0.0.1", 50000))


def body(**kw) -> dict:
    return {"engine": "openai-gpt-4o", "tags": ["de"], "max_calls": 10, **kw}


def jobs_count() -> int:
    with session() as s:
        return len(list(s.scalars(__import__("sqlalchemy").select(Job))))


def test_trigger_off_refuses_and_says_what_to_run_instead(client, monkeypatch):
    monkeypatch.setattr(settings, "scan_trigger", "off")
    r = client.post("/scans", json=body())
    assert r.status_code == 403
    assert "llmlc scan" in r.json()["detail"]
    assert jobs_count() == 0, "a refused trigger must not create a job"


def test_non_loopback_caller_is_refused(monkeypatch):
    remote = TestClient(app, client=("10.1.2.3", 51000))
    r = remote.post("/scans", json=body())
    assert r.status_code == 403
    assert "10.1.2.3" in r.json()["detail"]
    assert jobs_count() == 0


def test_forwarded_header_does_not_grant_access():
    """A header any client can set is not an access control."""
    remote = TestClient(app, client=("10.1.2.3", 51000))
    r = remote.post("/scans", json=body(),
                    headers={"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1"})
    assert r.status_code == 403


def test_any_mode_allows_a_non_loopback_caller(monkeypatch):
    monkeypatch.setattr(settings, "scan_trigger", "any")
    monkeypatch.setattr(runner, "run_in_background", lambda req, job_id: None)
    remote = TestClient(app, client=("172.17.0.1", 51000))
    assert remote.post("/scans", json=body()).status_code == 202


def test_budget_is_required(client):
    r = client.post("/scans", json={"engine": "m", "tags": ["de"]})
    assert r.status_code == 422, "a browser-started scan must name its ceiling"


def test_budget_ceiling_is_enforced(client):
    r = client.post("/scans", json=body(max_calls=10_000))
    assert r.status_code == 400
    assert "ceiling" in r.json()["detail"]
    assert jobs_count() == 0


def test_unknown_tags_refuse_before_anything_is_spent(client):
    r = client.post("/scans", json=body(tags=["zz-nope"]))
    assert r.status_code == 400
    assert jobs_count() == 0


def test_self_backtranslation_is_refused(client):
    """A model back-translating itself measures self-consistency (protocol 005)."""
    r = client.post("/scans", json=body(engine="x", backtranslator="x"))
    assert r.status_code == 400
    assert "back-translator" in r.json()["detail"]


def test_one_scan_at_a_time(client, monkeypatch):
    monkeypatch.setattr(runner, "run_in_background", lambda req, job_id: None)
    first = client.post("/scans", json=body())
    assert first.status_code == 202
    second = client.post("/scans", json=body())
    assert second.status_code == 409
    assert str(first.json()["job_id"]) in second.json()["detail"]


def test_a_started_job_is_watchable(client, monkeypatch):
    monkeypatch.setattr(runner, "run_in_background", lambda req, job_id: None)
    job_id = client.post("/scans", json=body(tags=["de", "de-AT", "fr"])).json()["job_id"]
    d = client.get(f"/jobs/{job_id}").json()
    assert d["status"] == "running"
    assert d["classes"] == 2, "de and de-AT are one class; fr is another"
    assert d["classes_done"] == 0
    assert d["requested_tags"] == ["de", "de-AT", "fr"]


def test_cancelling_marks_the_job_and_stops_the_scan(client, monkeypatch):
    monkeypatch.setattr(runner, "run_in_background", lambda req, job_id: None)
    job_id = client.post("/scans", json=body()).json()["job_id"]
    r = client.post(f"/jobs/{job_id}/cancel").json()
    assert r["cancelled"] is True
    assert runner.is_cancelled(job_id)
    assert client.get("/jobs").json()["items"][0]["cancelling"] is True


def test_cancelling_a_finished_job_is_not_an_error(client, monkeypatch):
    monkeypatch.setattr(runner, "run_in_background", lambda req, job_id: None)
    job_id = client.post("/scans", json=body()).json()["job_id"]
    with session() as s:
        s.get(Job, job_id).status = "done"
    r = client.post(f"/jobs/{job_id}/cancel").json()
    assert r["cancelled"] is False


def test_cancelling_is_guarded_like_starting(monkeypatch):
    """Stopping someone else's scan is a write too."""
    monkeypatch.setattr(settings, "scan_trigger", "off")
    remote = TestClient(app, client=("10.1.2.3", 51000))
    assert remote.post("/jobs/1/cancel").status_code == 403


def test_plan_is_free_and_needs_no_trigger(monkeypatch):
    monkeypatch.setattr(settings, "scan_trigger", "off")
    remote = TestClient(app, client=("10.1.2.3", 51000))
    d = remote.get("/scans/plan", params={"engine": "m", "tags": "de, de-AT, fr, zz-nope"}).json()
    assert (d["tags"], d["classes"], d["inherited"]) == (3, 2, 1)
    assert d["unknown"] == ["zz-nope"]
    assert jobs_count() == 0


def test_missing_endpoint_config_refuses_rather_than_failing_mid_scan(client, monkeypatch):
    monkeypatch.setattr(settings, "aggregator_base_url", None)
    r = client.post("/scans", json=body())
    assert r.status_code == 400
    assert ".env" in r.json()["detail"]
    assert jobs_count() == 0
