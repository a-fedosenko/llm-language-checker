"""Where a model's endpoint and key come from, and in what order.

The ordering is the contract: a custom model list wins over the aggregator
settings wherever both are present, and neither configured is a named refusal
rather than a confusing failure further down. The rest of these cover the
reasons a hand-edited JSON file goes wrong, because that is what a public user
is actually doing.
"""
import json

import pytest

from llmlc.client import (NotConfigured, ModelNotListed, OpenAICompatClient,
                          RoutingClient, build_client, check_models,
                          is_configured, load_custom_models)
from llmlc.config import settings

ENTRIES = [
    {"model_title": "GPT-4o", "model_id": "gpt-4o",
     "api_key": "k-openai", "v1_endpoint": "https://api.openai.com/v1"},
    {"model_title": "DeepSeek Chat", "model_id": "deepseek-chat",
     "api_key": "k-deepseek", "v1_endpoint": "https://api.deepseek.com"},
]


@pytest.fixture
def listfile(tmp_path):
    def write(payload) -> str:
        p = tmp_path / "models.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return str(p)
    return write


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    """Neither route configured unless a test says otherwise. Without this the
    developer's own .env decides what these assert."""
    monkeypatch.setattr(settings, "custom_model_list_path", None)
    monkeypatch.setattr(settings, "aggregator_base_url", None)
    monkeypatch.setattr(settings, "aggregator_admin_api_key", None)


def use_list(monkeypatch, path):
    monkeypatch.setattr(settings, "custom_model_list_path", path)


def use_aggregator(monkeypatch):
    monkeypatch.setattr(settings, "aggregator_base_url", "https://gw.invalid")
    monkeypatch.setattr(settings, "aggregator_admin_api_key", "k-gateway")


# -- the resolution order ----------------------------------------------------

def test_the_custom_list_wins_over_the_aggregator(monkeypatch, listfile):
    use_aggregator(monkeypatch)
    use_list(monkeypatch, listfile({"models": ENTRIES}))
    c = build_client()
    assert isinstance(c, RoutingClient)
    assert c.model_ids == ["deepseek-chat", "gpt-4o"]


def test_the_aggregator_still_works_when_no_list_is_set(monkeypatch):
    use_aggregator(monkeypatch)
    c = build_client()
    assert isinstance(c, OpenAICompatClient)
    assert c.base_url == "https://gw.invalid/v1"


def test_neither_configured_names_both_routes(monkeypatch):
    assert is_configured() is False
    with pytest.raises(NotConfigured) as e:
        build_client()
    msg = str(e.value)
    assert "CUSTOM_MODEL_LIST_PATH" in msg
    assert "AGGREGATOR_BASE_URL" in msg
    assert ".models.json.example" in msg


def test_an_empty_path_is_the_same_as_unset(monkeypatch):
    """A variable left blank in .env arrives as "" and must not be a broken path."""
    use_aggregator(monkeypatch)
    monkeypatch.setattr(settings, "custom_model_list_path", "   ")
    assert isinstance(build_client(), OpenAICompatClient)


# -- per-model routing -------------------------------------------------------

def test_each_model_gets_its_own_endpoint_and_key(monkeypatch, listfile):
    use_list(monkeypatch, listfile({"models": ENTRIES}))
    c = build_client()
    a, b = c.client_for("gpt-4o"), c.client_for("deepseek-chat")
    assert a is not b
    assert a.base_url == "https://api.openai.com/v1"
    # "/v1" is appended where the user left it off, as the single-endpoint
    # client has always done.
    assert b.base_url == "https://api.deepseek.com/v1"
    assert a._key == "k-openai" and b._key == "k-deepseek"


def test_a_model_keeps_one_client_across_calls(monkeypatch, listfile):
    """Per-model state -- chiefly which models reject `reasoning_effort` -- is
    learned once and must not be thrown away between calls."""
    use_list(monkeypatch, listfile({"models": ENTRIES}))
    c = build_client()
    assert c.client_for("gpt-4o") is c.client_for("gpt-4o")


def test_a_title_resolves_to_its_model_id(monkeypatch, listfile):
    use_list(monkeypatch, listfile({"models": ENTRIES}))
    c = build_client()
    assert c.entry_for("GPT-4o").model_id == "gpt-4o"


def test_an_unlisted_model_says_what_the_list_holds(monkeypatch, listfile):
    use_list(monkeypatch, listfile({"models": ENTRIES}))
    c = build_client()
    with pytest.raises(ModelNotListed) as e:
        c.entry_for("claude-opus-5")
    assert "gpt-4o" in str(e.value) and "deepseek-chat" in str(e.value)


# -- checking reachability before spending anything --------------------------

def test_check_models_names_what_the_list_cannot_reach(monkeypatch, listfile):
    use_list(monkeypatch, listfile({"models": ENTRIES}))
    assert check_models(["gpt-4o", "GPT-4o", "gemini-3-6-flash", "qwen"]) == [
        "gemini-3-6-flash", "qwen"]


def test_check_models_is_silent_on_the_aggregator(monkeypatch):
    """A gateway takes any id it recognises, so there is nothing to check up
    front -- its unknowns surface as an HTTP error at call time."""
    use_aggregator(monkeypatch)
    assert check_models(["anything-at-all"]) == []


# -- the ways a hand-edited file goes wrong ----------------------------------

def test_a_missing_file_is_an_error_not_a_silent_fallback(monkeypatch, tmp_path):
    """Set-but-broken must never present as "not configured": that sends the
    reader to the wrong problem."""
    use_aggregator(monkeypatch)
    use_list(monkeypatch, str(tmp_path / "absent.json"))
    with pytest.raises(NotConfigured, match="file not found"):
        build_client()


def test_invalid_json_names_the_file(monkeypatch, tmp_path):
    p = tmp_path / "models.json"
    p.write_text("{not json", encoding="utf-8")
    use_list(monkeypatch, str(p))
    with pytest.raises(NotConfigured, match="JSON"):
        build_client()


def test_a_missing_models_key_says_so(monkeypatch, listfile):
    use_list(monkeypatch, listfile({"engines": ENTRIES}))
    with pytest.raises(NotConfigured, match='"models" key'):
        build_client()


def test_an_empty_list_is_refused(monkeypatch, listfile):
    use_list(monkeypatch, listfile({"models": []}))
    with pytest.raises(NotConfigured, match="non-empty"):
        build_client()


@pytest.mark.parametrize("field", ["model_id", "api_key", "v1_endpoint"])
def test_each_required_field_is_named_when_absent(monkeypatch, listfile, field):
    row = dict(ENTRIES[0])
    row.pop(field)
    use_list(monkeypatch, listfile({"models": [row]}))
    with pytest.raises(NotConfigured, match=field):
        build_client()


def test_a_blank_required_field_counts_as_missing(monkeypatch, listfile):
    """An unfilled placeholder is the common case, and `""` is not a key."""
    use_list(monkeypatch, listfile({"models": [{**ENTRIES[0], "api_key": "  "}]}))
    with pytest.raises(NotConfigured, match="api_key"):
        build_client()


def test_a_duplicate_model_id_is_refused_rather_than_last_wins(monkeypatch, listfile):
    dup = [ENTRIES[0], {**ENTRIES[1], "model_id": "gpt-4o"}]
    use_list(monkeypatch, listfile({"models": dup}))
    with pytest.raises(NotConfigured, match="repeats model_id"):
        build_client()


def test_model_title_is_optional(monkeypatch, listfile):
    row = {k: v for k, v in ENTRIES[0].items() if k != "model_title"}
    use_list(monkeypatch, listfile({"models": [row]}))
    assert build_client().entry_for("gpt-4o").title == "gpt-4o"


def test_a_bare_array_is_tolerated(monkeypatch, listfile):
    use_list(monkeypatch, listfile(ENTRIES))
    assert build_client().model_ids == ["deepseek-chat", "gpt-4o"]


# -- the shipped example -----------------------------------------------------

def test_the_shipped_example_parses_and_covers_every_field(monkeypatch):
    """`.models.json.example` is the only instruction most users will read, so
    a drift between it and the loader is a user-facing bug."""
    entries = load_custom_models(".models.json.example")
    assert len(entries) >= 2
    assert all(e.model_id and e.api_key and e.v1_endpoint and e.model_title
               for e in entries)


# -- the guard in front of a scan --------------------------------------------

def test_a_scan_is_refused_when_the_list_cannot_reach_the_judge_or_panel(
        monkeypatch, listfile, tmp_path):
    """The defaults are this project's own model ids. A stranger's list will not
    hold them, and the first paid call is the wrong place to find out."""
    from llmlc import runner
    from llmlc.db import reset_for_tests

    reset_for_tests(f"sqlite+pysqlite:///{tmp_path/'t.db'}")
    use_list(monkeypatch, listfile({"models": ENTRIES}))
    req = runner.ScanRequest(engine="gpt-4o", tags=["de"], max_calls=10,
                             judge="some-judge", backtranslator="some-reader")
    with pytest.raises(runner.ScanRefused) as e:
        runner.create(req)
    detail = str(e.value)
    assert "some-judge" in detail and "some-reader" in detail
    assert "gpt-4o" not in detail      # the one model it *can* reach


def test_a_scan_proceeds_when_every_model_is_listed(monkeypatch, listfile, tmp_path):
    from llmlc import runner
    from llmlc.db import reset_for_tests

    reset_for_tests(f"sqlite+pysqlite:///{tmp_path/'t.db'}")
    use_list(monkeypatch, listfile({"models": ENTRIES}))
    req = runner.ScanRequest(engine="gpt-4o", tags=["de"], max_calls=10,
                             judge="gpt-4o", backtranslator="deepseek-chat")
    assert runner.create(req) > 0


# -- what the UI is told -----------------------------------------------------

def test_the_engine_picker_offers_the_custom_list(monkeypatch, listfile, tmp_path):
    from fastapi.testclient import TestClient

    from llmlc.api.main import app
    from llmlc.db import reset_for_tests

    reset_for_tests(f"sqlite+pysqlite:///{tmp_path/'t.db'}")
    use_list(monkeypatch, listfile({"models": ENTRIES}))
    d = TestClient(app).get("/engines").json()
    assert d["available"] == ["deepseek-chat", "gpt-4o"]
    # A custom list is the configuration, not a gateway's opinion of itself, so
    # the UI can treat it as the whole of what is scannable.
    assert d["available_is_exhaustive"] is True


def test_a_broken_list_leaves_the_picker_empty_rather_than_breaking_the_page(
        monkeypatch, tmp_path):
    """The readiness story belongs to the scan attempt, which reports the parse
    error. A browse-only visitor should still get a page."""
    from fastapi.testclient import TestClient

    from llmlc.api.main import app
    from llmlc.db import reset_for_tests

    reset_for_tests(f"sqlite+pysqlite:///{tmp_path/'t.db'}")
    use_list(monkeypatch, str(tmp_path / "absent.json"))
    d = TestClient(app).get("/engines").json()
    assert d["available"] == []
    assert d["available_is_exhaustive"] is False
