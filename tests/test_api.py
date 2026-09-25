from fastapi.testclient import TestClient

from llmlc.api.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["scheme_loaded"] is True


def test_hardware_reports_a_profile():
    body = client.get("/hardware").json()
    assert body["profile"] in {"gpu-fp16", "gpu-int8", "cpu", "api"}
    assert body["coverage"]


def test_scheme_meta_carries_attribution():
    assert client.get("/scheme").json()["attribution"]


def test_languages_search_and_paging():
    r = client.get("/languages", params={"q": "kazakh", "limit": 5}).json()
    assert r["total"] >= 1
    assert any(x["tag"] == "kk" for x in r["items"])


def test_language_detail_exposes_class_and_family():
    body = client.get("/languages/ar").json()
    assert body["language"]["scope"] == "macrolanguage"
    assert body["class_members"]


def test_unknown_language_404():
    assert client.get("/languages/zz-nope").status_code == 404


# -- results endpoints -------------------------------------------------------

def test_results_endpoint_returns_a_summary():
    body = client.get("/results").json()
    assert "summary" in body and "items" in body
    assert set(body["summary"]) == {"total", "tiers", "evidence", "engines", "variants"}


def test_results_filtering_by_tier():
    body = client.get("/results", params={"tier": "Proficient"}).json()
    assert all(r["tier"] == "Proficient" for r in body["items"])


def test_unknown_result_404s():
    assert client.get("/results/no-such-engine/zz").status_code == 404


def test_index_serves_the_ui():
    r = client.get("/")
    assert r.status_code == 200
    assert "Measured language support" in r.text
    assert "heuristic results, not proof" in r.text, "the limits must be on the page, not buried"


# -- jobs and staleness ------------------------------------------------------

def test_jobs_endpoint_lists_scans():
    body = client.get("/jobs").json()
    assert "items" in body
    assert all({"id", "engine", "status"} <= set(j) for j in body["items"])


def test_stale_endpoint_names_the_current_method():
    body = client.get("/stale").json()
    assert body["current_method_version"]
    assert isinstance(body["tags"], list)


def test_results_survive_with_no_database():
    """The UI must work for someone who has only ever run the CLI."""
    from llmlc.api import results as store
    rows = store._from_files()
    assert isinstance(rows, list)
