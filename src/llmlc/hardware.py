"""Hardware detection, and an honest account of what it currently decides.

The back-translator is the only GPU-hungry component, and how much VRAM exists
would decide quantisation rather than feasibility -- **if a local back-translator
existed.** It does not. `bt/` holds a remote back-translator and its
qualification, and nothing else; the MADLAD/NLLB service planned for S3 and then
S6 was never built, and neither stage recorded the fact.

That mattered more than a missing feature, because `detect()` kept resolving to
`gpu-int8` on a machine with a GPU and that string was stamped on every result as
the instrument that produced it. A row reading `hardware_profile: gpu-int8`
asserts MADLAD-400-3B read the text. Gemini read it. The `backtranslator` column
held the truth and this one contradicted it, on a field whose whole purpose is to
say when two results are comparable (docs/01).

So the two questions are now separated:

  what this machine could run   `detect()`, reported by `/hardware`. Still probes
                                the GPU, because it is worth knowing and it is
                                what a local back-translator would need.
  what actually read the text   the resolved `profile`, which is `api` until a
                                local back-translator exists. This is what gets
                                recorded on a result.
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

#: No local back-translator is implemented. Flip this when `bt/local.py` exists,
#: and `detect()` will start resolving to the GPU and CPU profiles again -- the
#: detection logic below is kept intact for exactly that reason, and is tested.
#: Until then, resolving to `gpu-int8` would name an instrument that never ran.
LOCAL_BACKTRANSLATOR = False

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
    source: str           # "override" | "detected" | "no-local-backtranslator"
    dtype: str | None
    #: What the machine *could* run, when that differs from what it will.
    #: `gpu-int8` here with `profile: api` is the honest reading of a GPU box
    #: whose back-translation still goes over the network.
    capable_of: Profile | None = None

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


def _capability(vram: int | None) -> Profile:
    """What this machine would run if a local back-translator existed."""
    if vram and vram >= FP16_MIN_MB:
        return "gpu-fp16"
    if vram and vram >= INT8_MIN_MB:
        return "gpu-int8"
    return "cpu"


def detect(override: str | None = None) -> Hardware:
    override = override or os.environ.get("HARDWARE_PROFILE") or "auto"
    gpu_name, vram = _probe_gpu()
    capable = _capability(vram)

    if override != "auto":
        profile: Profile = override  # type: ignore[assignment]
        source = "override"
    elif os.environ.get("BT_REMOTE_MODEL"):
        profile, source = "api", "detected"
    elif not LOCAL_BACKTRANSLATOR:
        # The GPU is real and the profile it would earn is in `capable_of`. What
        # runs is the remote panel, and that is what a result must say.
        profile, source = "api", "no-local-backtranslator"
    else:
        profile, source = capable, "detected"

    return Hardware(
        profile=profile,
        gpu_name=gpu_name,
        vram_mb=vram,
        backtranslator=os.environ.get("BT_REMOTE_MODEL") if profile == "api" else BACKTRANSLATOR[profile],
        coverage=COVERAGE_NOTE[profile],
        source=source,
        dtype={"gpu-fp16": "float16", "gpu-int8": "int8", "cpu": "float32", "api": None}[profile],
        capable_of=capable,
    )
