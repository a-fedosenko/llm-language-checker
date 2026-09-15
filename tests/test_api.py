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
