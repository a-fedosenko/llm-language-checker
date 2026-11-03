"""The demo stand: the real pipeline, one step at a time.

What is tested here is the session layer, not the ladder -- the ladder has its
own tests, and the point of the design is that this module does not re-implement
it. So: that a session advances the one generator, that the gate on spending
money is the same gate a scan has, and that a run whose specifications were
edited is kept out of the results.
"""
import pytest
from fastapi.testclient import TestClient

from llmlc.api import demo as demo_sessions
from llmlc.api.main import app
from llmlc.config import settings
from llmlc.probe.specs import load_specs


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    from llmlc.db import reset_for_tests

    reset_for_tests(f"sqlite+pysqlite:///{tmp_path/'t.db'}")
    monkeypatch.setattr(settings, "custom_model_list_path", None)
    monkeypatch.setattr(settings, "aggregator_base_url", "https://example.invalid")
    monkeypatch.setattr(settings, "aggregator_admin_api_key", "k")
    monkeypatch.setattr(settings, "scan_trigger", "any")
    yield
    demo_sessions.reset_for_tests()


@pytest.fixture
def client():
    return TestClient(app)


def body(**kw):
    return {"engine": "some-engine", "tag": "cv", **kw}


# -- specifications, and what editing one costs ------------------------------

def test_unedited_specs_are_the_shipped_ones():
    specs, modified = demo_sessions.specs_for(None)
    assert specs == load_specs() and modified is False


def test_passing_the_shipped_specs_back_unchanged_is_not_an_edit():
    """The page sends them back so they can be shown and edited. Round-tripping
    them untouched must not quarantine the run."""
    shipped = load_specs()
    rows = [{"id": s.id, "scenario": s.scenario, "facts": list(s.facts)} for s in shipped]
    specs, modified = demo_sessions.specs_for(rows)
    assert modified is False and specs == shipped


def test_rewriting_a_scenario_is_an_edit():
    shipped = load_specs()
    rows = [{"id": s.id, "scenario": s.scenario, "facts": list(s.facts)} for s in shipped]
    rows[0]["scenario"] = "A dog chases a car."
    _, modified = demo_sessions.specs_for(rows)
    assert modified is True


def test_rewriting_the_facts_is_an_edit():
    shipped = load_specs()
    rows = [{"id": s.id, "scenario": s.scenario, "facts": list(s.facts)} for s in shipped]
    rows[0]["facts"] = ["something else"]
    _, modified = demo_sessions.specs_for(rows)
    assert modified is True


def test_an_unknown_spec_id_is_an_edit():
    _, modified = demo_sessions.specs_for(
        [{"id": "invented", "scenario": "x", "facts": ["a"]}])
    assert modified is True


# -- the gate on spending money ----------------------------------------------

def test_starting_a_session_is_gated_like_a_scan(client, monkeypatch):
    """It reaches a model with the user's own key. Cheaper than a scan is not
    the same as free."""
    monkeypatch.setattr(settings, "scan_trigger", "off")
    r = client.post("/demo", json=body())
    assert r.status_code == 403
    assert "SCAN_TRIGGER" in r.json()["detail"]


def test_an_unconfigured_endpoint_refuses_before_opening_a_session(client, monkeypatch):
    monkeypatch.setattr(settings, "aggregator_base_url", None)
    assert client.post("/demo", json=body()).status_code == 400
    assert demo_sessions.listing() == []


def test_an_unknown_tag_is_a_404_not_an_empty_run(client):
    r = client.post("/demo", json=body(tag="zz-nope"))
    assert r.status_code == 404 and "zz-nope" in r.json()["detail"]


def test_a_panel_emptied_by_the_family_guard_is_refused(client):
    """A model back-translating itself measures self-consistency (protocol 005)."""
    r = client.post("/demo", json=body(engine="gemini-x", backtranslator="gemini-y"))
    assert r.status_code == 400 and "self-consistency" in r.json()["detail"]


def test_sessions_are_capped(client, monkeypatch):
    monkeypatch.setattr(demo_sessions, "MAX_SESSIONS", 1)
    assert client.post("/demo", json=body()).status_code == 201
    r = client.post("/demo", json=body())
    assert r.status_code == 409 and "limit" in r.json()["detail"]


# -- the session itself ------------------------------------------------------

def test_a_new_session_has_spent_nothing(client):
    d = client.post("/demo", json=body()).json()
    assert d["status"] == "running" and d["steps"] == [] and d["result"] is None


def test_an_edited_run_is_marked_and_never_persisted(client):
    rows = [{"id": s.id, "scenario": "A dog chases a car.", "facts": ["a dog ran"]}
            for s in load_specs()[:1]]
    d = client.post("/demo", json=body(specs=rows)).json()
    assert d["specs_modified"] is True
    assert d["persisted"] is False


def test_closing_a_session_removes_it(client):
    sid = client.post("/demo", json=body()).json()["id"]
    assert client.delete(f"/demo/{sid}").json()["closed"] is True
    assert client.get(f"/demo/{sid}").status_code == 404


def test_stepping_an_unknown_session_is_a_404_not_a_new_run(client):
    assert client.post("/demo/nope/step").status_code == 404


def test_the_listing_shows_open_sessions(client):
    client.post("/demo", json=body())
    d = client.get("/demo").json()
    assert len(d["sessions"]) == 1 and d["max_sessions"] == demo_sessions.MAX_SESSIONS


# -- saying what the run will actually ask for -------------------------------

def test_the_region_reaches_the_prompt_by_name_not_by_code():
    """Method 3.0.0. A model has no reason to read `ME` as a place, so the
    designator carries "Montenegro"."""
    from llmlc.api.demo import plan_for
    from llmlc.scheme import load_scheme

    plan = plan_for(load_scheme("default"), "sr-Cyrl-ME")
    assert plan["region"] == "ME" and plan["region_name"] == "Montenegro"
    assert plan["primary"] == "Serbian (Montenegro, Cyrillic script)"
    assert plan["unnamed_subtags"] == []


def test_a_region_with_no_name_is_reported_as_unnamed():
    """The catalogue names 9,490 of 9,589 regions. For the rest the prompt
    cannot say where, and the page has to say that rather than imply it did."""
    from llmlc.api.demo import plan_for
    from llmlc.scheme import load_scheme

    scheme = load_scheme("default")
    nameless = next((t for t, l in scheme.languages.items()
                     if l.region and not l.region_name), None)
    if nameless is None:
        import pytest
        pytest.skip("this catalogue names every region it carries")
    plan = plan_for(scheme, nameless)
    assert plan["unnamed_subtags"] == ["region"]


def test_siblings_that_now_diverge_are_flagged_as_inheriting_anyway():
    """The sharp edge of naming the region. `sr-Cyrl-ME` and `sr` are asked
    different things now, but they still share the class `srp|Cyrl` — and a
    scan probes a class once and the rest inherit. So the demo shows a prompt a
    scan would never send, and has to say so."""
    from llmlc.api.demo import plan_for
    from llmlc.scheme import load_scheme

    scheme = load_scheme("default")
    a = plan_for(scheme, "sr-Cyrl-ME")
    b = plan_for(scheme, "sr")
    assert a["cls"] == b["cls"], "the premise has changed: classes now differ"
    assert a["primary"] != b["primary"], "the region is no longer reaching the prompt"
    assert "sr" in a["divergent_siblings"]
    assert a["sibling_designators"]["sr"] == b["primary"]


def test_the_plan_reaches_the_session_before_anything_is_spent(client):
    d = client.post("/demo", json=body(tag="sr", scheme="default")).json()
    assert d["plan"]["primary"]
    assert d["steps"] == [] and d["plan"]["designators"]


def test_the_prompt_is_carried_on_the_item_not_only_in_the_corpus():
    """Reading the raw evidence is the convention that has found most of this
    project's real defects, and the prompt is the half you cannot reconstruct
    from the answer."""
    from llmlc.probe.ladder import item_detail
    from llmlc.probe.gate import GateResult, GateVerdict
    from llmlc.probe.steps import ItemOutcome

    item = ItemOutcome("s1", "Serbian (Cyrillic script)", "текст",
                       GateResult(GateVerdict.PASS), prompt="Write 3 sentences in…")
    assert item_detail(item)["prompt"] == "Write 3 sentences in…"
