"""Hardware detection.

The back-translator is the only GPU-hungry component, and how much VRAM exists
decides quantisation rather than feasibility. The resolved profile is recorded on
every result, because results produced by different back-translators are not
comparable (see docs/01).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import Literal

Profile = Literal["gpu-fp16", "gpu-int8", "cpu", "api"]

# MADLAD-400-3B is ~6 GB in fp16 before activations. On an 8 GB card that may
# work but should not be what a stranger hits on first run, so fp16 is only
# chosen well above it.
FP16_MIN_MB = 10_000
INT8_MIN_MB = 4_000

BACKTRANSLATOR = {
    "gpu-fp16": "google/madlad400-3b-mt",
    "gpu-int8": "google/madlad400-3b-mt",
    "cpu": "facebook/nllb-200-distilled-600M",
    "api": None,
}
COVERAGE_NOTE = {
    "gpu-fp16": "~400 languages",
    "gpu-int8": "~400 languages",
    "cpu": "~200 languages",
    "api": "as qualified per language",
}


@dataclass(frozen=True)
class Hardware:
    profile: Profile
    gpu_name: str | None
    vram_mb: int | None
    backtranslator: str | None
    coverage: str
    source: str           # "override" | "detected"
    dtype: str | None

    def as_dict(self) -> dict:
        return asdict(self)


def _probe_gpu() -> tuple[str | None, int | None]:
    """Query the GPU without importing torch, so the API container stays small."""
    if not shutil.which("nvidia-smi"):
        return None, None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15, check=True,
        ).stdout.strip().splitlines()
    except (subprocess.SubprocessError, OSError):
        return None, None
    if not out:
        return None, None
    name, _, mem = out[0].partition(",")
    try:
        return name.strip(), int(mem.strip())
    except ValueError:
        return name.strip(), None


def detect(override: str | None = None) -> Hardware:
    override = override or os.environ.get("HARDWARE_PROFILE") or "auto"
    gpu_name, vram = _probe_gpu()

    if override != "auto":
        profile: Profile = override  # type: ignore[assignment]
        source = "override"
    elif os.environ.get("BT_REMOTE_MODEL"):
        profile, source = "api", "detected"
    elif vram and vram >= FP16_MIN_MB:
        profile, source = "gpu-fp16", "detected"
    elif vram and vram >= INT8_MIN_MB:
        profile, source = "gpu-int8", "detected"
    else:
        profile, source = "cpu", "detected"

    return Hardware(
        profile=profile,
        gpu_name=gpu_name,
        vram_mb=vram,
        backtranslator=os.environ.get("BT_REMOTE_MODEL") if profile == "api" else BACKTRANSLATOR[profile],
        coverage=COVERAGE_NOTE[profile],
        source=source,
        dtype={"gpu-fp16": "float16", "gpu-int8": "int8", "cpu": "float32", "api": None}[profile],
    )
