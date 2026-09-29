"""First-run assets, and the rule that a missing instrument must be stated.

The defect these pin: a fresh clone could `docker compose up`, press the scan
button, and get results measured with half a gate and no back-translator
controls — with nothing anywhere saying so.
"""
import pytest
from fastapi.testclient import TestClient

from llmlc import bootstrap
from llmlc.api.main import app

client = TestClient(app)


def test_every_asset_says_what_breaks_without_it():
    """A readiness list that only says `missing` makes the user guess. Each entry
    names the consequence in the terms the tool reports in."""
    for asset in bootstrap.ASSETS:
        assert asset.degraded and len(asset.degraded) > 40
        assert asset.licence, "licence is why these are not committed; say which"
        assert asset.size_hint


def test_status_is_honest_about_scanning(monkeypatch):
    monkeypatch.setattr(type(bootstrap.ASSETS[0]), "present", property(lambda self: False))
    st = bootstrap.status()
    assert not st["ready"]
    assert not st["scan_meaningful"], "a scan that cannot measure must not read as ready"
    assert "glotlid" in st["missing"]


def test_readiness_endpoint_reports_each_asset():
    body = client.get("/readiness").json()
    assert set(body) >= {"ready", "assets", "missing", "disk_free_mb"}
    assert {a["key"] for a in body["assets"]} == {a.key for a in bootstrap.ASSETS}


def test_bootstrap_is_gated_like_a_scan():
    """It reaches the network and writes 1.6 GB to the user's disk. Same door as
    the other endpoint that spends their resources."""
    assert client.post("/bootstrap", json={}).status_code == 403


def test_an_unknown_asset_is_rejected_not_ignored():
    with pytest.raises(KeyError):
        bootstrap.ensure(["no-such-asset"])


def test_ensure_is_idempotent_when_everything_is_present():
    if not all(a.present for a in bootstrap.ASSETS):
        pytest.skip("assets not built here; run `llmlc bootstrap`")
    out = bootstrap.ensure()
    assert out["fetched"] == [] and out["ready"]


# -- panel policy --------------------------------------------------------------

def test_the_panel_never_contains_the_engines_family():
    """docs/01 asked for "never the model under test, preferably not the same
    family". The preference is enforced: a sibling shares tokenizer, training data
    and failure modes, and is the reader most likely to decode a broken output
    charitably."""
    from llmlc.runner import DEFAULT_PANEL, ScanRequest
    for engine, expected in [
        ("openai-gpt-4o", 2),
        ("gemini-gemini-3-8-flash", 1),      # gemini-3-6-flash is a sibling
        ("deepseek-deepseek-v4-pro", 1),     # deepseek-v4-flash is a sibling
        ("groq-qwen3-8-27b", 2),
    ]:
        panel = ScanRequest(engine=engine, tags=[]).panel
        assert len(panel) == expected, f"{engine} -> {panel}"
        assert all(not m.startswith(engine.split("-", 1)[0]) for m in panel)
    assert "gemini-gemini-3-8-flash" not in DEFAULT_PANEL, \
        "a panel member that is also under test strands that engine on a different instrument"


def test_the_stronger_reader_is_first():
    """`route()` takes the first member that qualifies, so order decides which
    reader most results actually use. Measured: gemini-3-6-flash beats
    deepseek-v4-flash on the hard end (ug 59.3 vs 40.3, am 62.8 vs 48.5)."""
    from llmlc.runner import DEFAULT_PANEL
    assert DEFAULT_PANEL.split(",")[0] == "gemini-gemini-3-6-flash"


def test_model_family_splits_on_the_vendor_prefix():
    from llmlc.runner import model_family
    assert model_family("gemini-gemini-3-8-flash") == "gemini"
    assert model_family("openai-gpt-4o") == model_family("openai-gpt-4o-mini") == "openai"
    assert model_family("groq-qwen3-8-27b") == "groq"
