"""Hardware profile resolution. Must not require a GPU to run."""
import llmlc.hardware as hw


def test_override_wins(monkeypatch):
    monkeypatch.delenv("BT_REMOTE_MODEL", raising=False)
    h = hw.detect("cpu")
    assert h.profile == "cpu"
    assert h.source == "override"
    assert h.backtranslator == "facebook/nllb-200-distilled-600M"


def test_no_gpu_falls_back_to_cpu(monkeypatch):
    monkeypatch.setattr(hw, "_probe_gpu", lambda: (None, None))
    monkeypatch.delenv("BT_REMOTE_MODEL", raising=False)
    h = hw.detect("auto")
    assert h.profile == "cpu"
    assert "200" in h.coverage


def test_8gb_card_picks_int8_not_fp16(monkeypatch):
    """An 8 GB card must not default to fp16: MADLAD-3B is ~6 GB before activations."""
    monkeypatch.setattr(hw, "_probe_gpu", lambda: ("RTX 4060 Laptop GPU", 8188))
    monkeypatch.delenv("BT_REMOTE_MODEL", raising=False)
    h = hw.detect("auto")
    assert h.profile == "gpu-int8"
    assert h.dtype == "int8"


def test_large_card_picks_fp16(monkeypatch):
    monkeypatch.setattr(hw, "_probe_gpu", lambda: ("A100", 40_000))
    monkeypatch.delenv("BT_REMOTE_MODEL", raising=False)
    assert hw.detect("auto").profile == "gpu-fp16"


def test_remote_backtranslator_takes_precedence(monkeypatch):
    monkeypatch.setattr(hw, "_probe_gpu", lambda: ("RTX 4060", 8188))
    monkeypatch.setenv("BT_REMOTE_MODEL", "gemini-gemini-3-8-flash")
    h = hw.detect("auto")
    assert h.profile == "api"
    assert h.backtranslator == "gemini-gemini-3-8-flash"
