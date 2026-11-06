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


def test_a_tag_label_shows_what_separates_it_from_its_siblings():
    """The language name does not. Eight Portuguese locales produced eight rows
    reading "Portuguese · português" — a choice between eight identical labels,
    which is no choice."""
    d = client.get("/languages", params={"q": "pt-", "limit": 20}).json()
    labels = {x["tag"]: x["label"] for x in d["items"] if x["tag"].startswith("pt-")}
    assert labels.get("pt-br") == "Brazil" and labels.get("pt-pt") == "Portugal"
    assert len(set(labels.values())) == len(labels), "every row must be distinct"


def test_the_script_appears_only_where_the_family_is_written_in_two():
    """`sr-me-cyrl` against `sr-me-latn` needs it. Appending "Latin" to all
    eight Portuguese rows would be the original problem with an extra word."""
    sr = client.get("/languages", params={"q": "sr-me", "limit": 10}).json()["items"]
    by = {x["tag"]: x["label"] for x in sr}
    assert by.get("sr-me-cyrl") == "Montenegro · Cyrillic"
    assert by.get("sr-me-latn") == "Montenegro · Latin"

    pt = client.get("/languages", params={"q": "pt-br", "limit": 5}).json()["items"]
    assert "Latin" not in next(x["label"] for x in pt if x["tag"] == "pt-br")


def test_the_umbrella_falls_back_to_the_language_name():
    """The one row where the language name *is* the distinguishing fact. Keyed
    on the region subtag, not the region name: an unqualified tag has no region
    and still inherits one from the catalogue's likely-subtag resolution, so
    `pt` would otherwise label itself "Brazil" and collide with `pt-br`."""
    d = client.get("/languages", params={"q": "pt", "limit": 40}).json()["items"]
    pt = next((x for x in d if x["tag"] == "pt"), None)
    if pt is None:
        import pytest
        pytest.skip("this locale list has no bare `pt`")
    assert pt["label"] == "Portuguese"


def test_a_tag_is_findable_by_the_place_the_picker_shows():
    """Typing what you can see should find it."""
    d = client.get("/languages", params={"q": "Montenegro", "limit": 10}).json()
    assert {x["tag"] for x in d["items"]} >= {"sr-me-cyrl", "sr-me-latn"}
