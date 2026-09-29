"""Hardware profile resolution. Must not require a GPU to run.

Two questions, deliberately separated (protocol 019's cleanup): what this machine
*could* run, and what actually read the text. Until a local back-translator
exists the second is always `api`, and stamping a GPU profile on a result would
name an instrument that never ran.
"""
import llmlc.hardware as hw


# -- what actually runs -------------------------------------------------------

def test_a_gpu_box_still_reports_api_while_no_local_backtranslator_exists():
    """The defect this replaced: every result on the reference machine was stamped
    `gpu-int8`, asserting MADLAD-400-3B read the text. Gemini read it."""
    assert not hw.LOCAL_BACKTRANSLATOR, "flip the tests below when bt/local.py lands"
    h = hw.detect("auto")
    assert h.profile == "api"
    assert h.source == "no-local-backtranslator"


def test_the_gpu_is_still_reported_as_capability(monkeypatch):
    """Detection is not deleted, only demoted: it is what a local back-translator
    would need, and it is worth knowing which box you are on."""
    monkeypatch.setattr(hw, "_probe_gpu", lambda: ("RTX 4060 Laptop GPU", 8188))
    monkeypatch.delenv("BT_REMOTE_MODEL", raising=False)
    h = hw.detect("auto")
    assert h.profile == "api", "what ran"
    assert h.capable_of == "gpu-int8", "what could run"
    assert h.gpu_name and h.vram_mb == 8188


def test_override_still_wins(monkeypatch):
    """An explicit HARDWARE_PROFILE is a deliberate act and is not second-guessed."""
    monkeypatch.delenv("BT_REMOTE_MODEL", raising=False)
    h = hw.detect("cpu")
    assert h.profile == "cpu" and h.source == "override"
    assert h.backtranslator == "facebook/nllb-200-distilled-600M"


def test_remote_backtranslator_env_is_explicit_too(monkeypatch):
    monkeypatch.setattr(hw, "_probe_gpu", lambda: ("RTX 4060", 8188))
    monkeypatch.setenv("BT_REMOTE_MODEL", "gemini-gemini-3-8-flash")
    h = hw.detect("auto")
    assert h.profile == "api"
    assert h.backtranslator == "gemini-gemini-3-8-flash"


# -- the capability logic, kept intact for when a local back-translator lands --

def test_no_gpu_is_cpu_capable():
    assert hw._capability(None) == "cpu"


def test_8gb_card_is_int8_not_fp16():
    """An 8 GB card must not default to fp16: MADLAD-3B is ~6 GB before activations."""
    assert hw._capability(8188) == "gpu-int8"


def test_large_card_is_fp16_capable():
    assert hw._capability(40_000) == "gpu-fp16"
