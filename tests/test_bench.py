"""The bench: the real pipeline, one step at a time.

What is tested here is the session layer, not the ladder -- the ladder has its
own tests, and the point of the design is that this module does not re-implement
it. So: that a session advances the one generator, that the gate on spending
money is the same gate a scan has, and that a run whose specifications were
edited is kept out of the results.
"""
import pytest
from fastapi.testclient import TestClient

from llmlc.api import bench as bench_sessions
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
    bench_sessions.reset_for_tests()


@pytest.fixture
def client():
    return TestClient(app)


def body(**kw):
    # A tag the *active* scheme has. These tests are about session mechanics --
    # capping, closing, editing specs -- so the tag only has to resolve; the
    # ones that genuinely need Chuvash (no FLORES control, hand-seeded) name it
    # together with `scheme="default"`, because `cv` is not in a TMS locale list.
    return {"engine": "some-engine", "tag": "de", **kw}


# -- specifications, and what editing one costs ------------------------------

def test_unedited_specs_are_the_shipped_ones():
    specs, modified = bench_sessions.specs_for(None)
    assert specs == load_specs() and modified is False


def test_passing_the_shipped_specs_back_unchanged_is_not_an_edit():
    """The page sends them back so they can be shown and edited. Round-tripping
    them untouched must not quarantine the run."""
    shipped = load_specs()
    rows = [{"id": s.id, "scenario": s.scenario, "facts": list(s.facts)} for s in shipped]
    specs, modified = bench_sessions.specs_for(rows)
    assert modified is False and specs == shipped


def test_rewriting_a_scenario_is_an_edit():
    shipped = load_specs()
    rows = [{"id": s.id, "scenario": s.scenario, "facts": list(s.facts)} for s in shipped]
    rows[0]["scenario"] = "A dog chases a car."
    _, modified = bench_sessions.specs_for(rows)
    assert modified is True


def test_rewriting_the_facts_is_an_edit():
    shipped = load_specs()
    rows = [{"id": s.id, "scenario": s.scenario, "facts": list(s.facts)} for s in shipped]
    rows[0]["facts"] = ["something else"]
    _, modified = bench_sessions.specs_for(rows)
    assert modified is True


def test_an_unknown_spec_id_is_an_edit():
    _, modified = bench_sessions.specs_for(
        [{"id": "invented", "scenario": "x", "facts": ["a"]}])
    assert modified is True


# -- the gate on spending money ----------------------------------------------

def test_starting_a_session_is_gated_like_a_scan(client, monkeypatch):
    """It reaches a model with the user's own key. Cheaper than a scan is not
    the same as free."""
    monkeypatch.setattr(settings, "scan_trigger", "off")
    r = client.post("/bench", json=body())
    assert r.status_code == 403
    assert "SCAN_TRIGGER" in r.json()["detail"]


def test_an_unconfigured_endpoint_refuses_before_opening_a_session(client, monkeypatch):
    monkeypatch.setattr(settings, "aggregator_base_url", None)
    assert client.post("/bench", json=body()).status_code == 400
    assert bench_sessions.listing() == []


def test_an_unknown_tag_is_a_404_not_an_empty_run(client):
    r = client.post("/bench", json=body(tag="zz-nope"))
    assert r.status_code == 404 and "zz-nope" in r.json()["detail"]


def test_a_panel_emptied_by_the_family_guard_is_refused(client):
    """A model back-translating itself measures self-consistency (protocol 005)."""
    r = client.post("/bench", json=body(engine="gemini-x", backtranslator="gemini-y"))
    assert r.status_code == 400 and "self-consistency" in r.json()["detail"]


def test_sessions_are_capped(client, monkeypatch):
    monkeypatch.setattr(bench_sessions, "MAX_SESSIONS", 1)
    assert client.post("/bench", json=body()).status_code == 201
    r = client.post("/bench", json=body())
    assert r.status_code == 409 and "limit" in r.json()["detail"]


# -- the session itself ------------------------------------------------------

def test_a_new_session_has_spent_nothing(client):
    d = client.post("/bench", json=body()).json()
    assert d["status"] == "running" and d["steps"] == [] and d["result"] is None


def test_an_edited_run_is_marked_and_never_persisted(client):
    rows = [{"id": s.id, "scenario": "A dog chases a car.", "facts": ["a dog ran"]}
            for s in load_specs()[:1]]
    d = client.post("/bench", json=body(specs=rows)).json()
    assert d["specs_modified"] is True
    assert d["persisted"] is False


def test_closing_a_session_removes_it(client):
    sid = client.post("/bench", json=body()).json()["id"]
    assert client.delete(f"/bench/{sid}").json()["closed"] is True
    assert client.get(f"/bench/{sid}").status_code == 404


def test_stepping_an_unknown_session_is_a_404_not_a_new_run(client):
    assert client.post("/bench/nope/step").status_code == 404


def test_the_listing_shows_open_sessions(client):
    client.post("/bench", json=body())
    d = client.get("/bench").json()
    assert len(d["sessions"]) == 1 and d["max_sessions"] == bench_sessions.MAX_SESSIONS


# -- saying what the run will actually ask for -------------------------------

def test_the_region_reaches_the_prompt_by_name_not_by_code():
    """Method 3.0.0. A model has no reason to read `ME` as a place, so the
    designator carries "Montenegro"."""
    from llmlc.api.bench import plan_for
    from llmlc.scheme import load_scheme

    plan = plan_for(load_scheme("default"), "sr-Cyrl-ME")
    assert plan["region"] == "ME" and plan["region_name"] == "Montenegro"
    assert plan["primary"] == "Serbian (Montenegro, Cyrillic script)"
    assert plan["unnamed_subtags"] == []


def test_a_region_with_no_name_is_reported_as_unnamed():
    """The catalogue names 9,490 of 9,589 regions. For the rest the prompt
    cannot say where, and the page has to say that rather than imply it did."""
    from llmlc.api.bench import plan_for
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
    scan probes a class once and the rest inherit. So the bench shows a prompt a
    scan would never send, and has to say so."""
    from llmlc.api.bench import plan_for
    from llmlc.scheme import load_scheme

    scheme = load_scheme("default")
    a = plan_for(scheme, "sr-Cyrl-ME")
    b = plan_for(scheme, "sr")
    assert a["cls"] == b["cls"], "the premise has changed: classes now differ"
    assert a["primary"] != b["primary"], "the region is no longer reaching the prompt"
    assert "sr" in a["divergent_siblings"]
    assert a["sibling_designators"]["sr"] == b["primary"]


def test_the_plan_reaches_the_session_before_anything_is_spent(client):
    d = client.post("/bench", json=body(tag="sr", scheme="default")).json()
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


# -- sessions the page has lost ----------------------------------------------

def test_the_listing_is_enough_to_recover_a_lost_session(client):
    """Reloading mid-run orphans a session: the page forgets the id, the server
    keeps the run. Four of those filled the limit and locked the tab out for an
    hour with no way to reach them, so the listing has to carry what the page
    needs to adopt or close one."""
    started = client.post("/bench", json=body(tag="cv", scheme="default")).json()
    listed = client.get("/bench").json()["sessions"]
    assert [s["id"] for s in listed] == [started["id"]]
    assert {"id", "engine", "tag", "status", "steps"} <= set(listed[0])
    assert listed[0]["status"] == "running"


def test_a_session_can_be_read_back_whole_after_the_page_forgot_it(client):
    """Adopting one means re-rendering what it has already done, so the state
    endpoint has to return the steps and the plan, not just a status."""
    sid = client.post("/bench", json=body(tag="cv", scheme="default")).json()["id"]
    d = client.get(f"/bench/{sid}").json()
    assert d["status"] == "running"
    assert "steps" in d and d["plan"]["primary"]


def test_hitting_the_limit_says_where_to_look(client, monkeypatch):
    """A dead end is worse than a refusal. The message names the place the
    sessions can be closed, because there was no way to reach them."""
    monkeypatch.setattr(bench_sessions, "MAX_SESSIONS", 1)
    client.post("/bench", json=body())
    detail = client.post("/bench", json=body()).json()["detail"]
    assert "listed above" in detail and "reloading" in detail.lower()


def test_closing_a_session_frees_its_place(client, monkeypatch):
    monkeypatch.setattr(bench_sessions, "MAX_SESSIONS", 1)
    sid = client.post("/bench", json=body()).json()["id"]
    assert client.post("/bench", json=body()).status_code == 409
    client.delete(f"/bench/{sid}")
    assert client.post("/bench", json=body()).status_code == 201


# -- choosing and showing the reader -----------------------------------------

def test_route_records_every_candidate_it_tried():
    """"Why this reader" should be answerable from the page. Without the
    attempt list the bench could show the winner and nothing about the one that
    failed first, which is the interesting half when a panel member is dropped."""
    from llmlc.bt import Qualification, QualStatus, route

    class Reader:
        def __init__(self, i): self.id = f"remote:r{i}"

    def fake_qualify(bt, *a, **kw):
        ok = bt.id.endswith("2")
        return Qualification(QualStatus.QUALIFIED if ok else QualStatus.FAILED,
                             80.0 if ok else 12.0, bt.id, "cv", "reference", "")

    import importlib

    # `llmlc.bt` re-exports the function under the submodule's own name, so
    # `import llmlc.bt.qualify as q` binds the function, not the module.
    q = importlib.import_module("llmlc.bt.qualify")
    original, q.qualify = q.qualify, fake_qualify
    try:
        tried = []
        bt, qual = route([Reader(1), Reader(2)], None, "j", "cv", attempts=tried)
    finally:
        q.qualify = original
    assert [a.backtranslator for a in tried] == ["remote:r1", "remote:r2"]
    assert bt.id == "remote:r2" and qual.trustworthy


def test_a_bench_can_name_its_own_panel_and_judge(client):
    # Distinct vendor prefixes on purpose: `some-engine` and `some-reader` share
    # the family `some`, and the guard would drop the reader before the test
    # reached what it meant to check.
    d = client.post("/bench", json=body(engine="alpha-engine", tag="cv",
                                       scheme="default",
                                       backtranslator="beta-reader",
                                       judge="gamma-judge")).json()
    assert d["status"] == "running"


def test_the_family_guard_still_applies_to_a_named_panel(client):
    """Naming the panel by hand does not buy past the rule that a model may not
    grade itself (protocol 005)."""
    r = client.post("/bench", json=body(engine="gemini-a", backtranslator="gemini-b"))
    assert r.status_code == 400 and "self-consistency" in r.json()["detail"]


def test_the_plan_names_the_panel_and_what_the_family_guard_dropped(client):
    """By the time the qualification step runs the dropped member is simply
    absent, and nothing explains why the panel is shorter than the one asked
    for. Scanning deepseek-v4-pro drops deepseek-v4-flash, which is most of the
    default panel."""
    d = client.post("/bench", json=body(engine="alpha-pro", tag="cv", scheme="default",
                                       backtranslator="alpha-flash,beta-reader")).json()
    assert d["plan"]["panel"] == ["beta-reader"]
    assert d["plan"]["panel_dropped"] == ["alpha-flash"]
    assert d["plan"]["judge"]


# -- the dialect battery, driven from the bench ------------------------------

def dialect_body(**kw):
    return {"engine": "alpha-pro", "tag": "sr-me-cyrl", **kw}


def test_a_dialect_session_is_gated_like_a_scan(client, monkeypatch):
    monkeypatch.setattr(settings, "scan_trigger", "off")
    r = client.post("/bench/dialect", json=dialect_body())
    assert r.status_code == 403 and "SCAN_TRIGGER" in r.json()["detail"]


def test_an_unknown_tag_is_a_404(client):
    r = client.post("/bench/dialect", json=dialect_body(tag="zz-nope"))
    assert r.status_code == 404 and "zz-nope" in r.json()["detail"]


def test_a_dialect_session_says_what_it_will_ask_before_spending(client):
    d = client.post("/bench/dialect", json=dialect_body()).json()
    assert d["kind"] == "dialect" and d["steps"] == []
    plan = d["plan"]
    assert plan["neutral"] == "sr"
    assert {v["tag"] for v in plan["varieties"]} == {"sr-me-cyrl", "sr-rs-cyrl"}
    # The designators are the ladder's, not a second opinion on them.
    assert any("Montenegro" in v["designator"] for v in plan["varieties"])


def test_a_family_with_no_second_named_variety_is_refused_with_a_reason(client):
    """Rather than opening a session that cannot ask a question. The umbrella is
    the conversion source, not a contrast arm."""
    r = client.post("/bench/dialect", json=dialect_body(tag="sr", varieties=["sr"]))
    assert r.status_code == 400 and "two named varieties" in r.json()["detail"]


def test_the_panel_can_be_forced_by_hand(client):
    d = client.post("/bench/dialect",
                    json=dialect_body(attestors=["beta-reader"])).json()
    assert d["plan"]["attestors_asked"] == ["beta-reader"]


def test_forcing_the_panel_does_not_buy_past_the_family_guard(client):
    """Naming the panel is a preference; not grading your own output is a rule
    (protocol 005)."""
    r = client.post("/bench/dialect",
                    json=dialect_body(attestors=["alpha-sibling"]))
    assert r.status_code == 400 and "self-consistency" in r.json()["detail"]


def test_a_dialect_session_is_listed_beside_a_ladder_one(client):
    client.post("/bench/dialect", json=dialect_body())
    kinds = {s.get("kind") for s in client.get("/bench").json()["sessions"]}
    assert kinds == {"dialect"}


def test_a_dialect_session_closes_like_any_other(client):
    sid = client.post("/bench/dialect", json=dialect_body()).json()["id"]
    assert client.delete(f"/bench/{sid}").json()["closed"] is True


def test_the_default_sibling_is_the_home_variety_not_catalogue_order(client):
    """The umbrella's likely-subtag region is the variety an unqualified request
    actually gets -- `sr` resolves to Serbia -- so that is what a reader means
    by "the other one", and it is the sibling markers/serbian.json already
    expresses itself against. Catalogue order paired Montenegro with Bosnia,
    which is a real contrast but not the one anyone asked for."""
    d = client.post("/bench/dialect", json=dialect_body()).json()
    assert {v["tag"] for v in d["plan"]["varieties"]} == {"sr-me-cyrl", "sr-rs-cyrl"}


def test_the_varieties_can_be_named_explicitly(client):
    """Spanish carries 22 regional tags and a 22-way blind choice is a harder
    task than the one being measured, so the caller chooses the field."""
    d = client.post("/bench/dialect",
                    json=dialect_body(tag="es-mx",
                                      varieties=["es-es", "es-mx"])).json()
    assert {v["tag"] for v in d["plan"]["varieties"]} == {"es-es", "es-mx"}
    assert d["plan"]["neutral"] == "es"


def test_the_russian_null_control_opens_with_real_options(client):
    """The probe has to be *able* to find a distinction here and report that it
    did not, rather than never asking."""
    d = client.post("/bench/dialect",
                    json=dialect_body(tag="ru-by",
                                      varieties=["ru-ru", "ru-by"])).json()
    assert set(d["plan"]["options"]) == {"Russia", "Belarus"}
