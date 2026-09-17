# 003 — Reference hardware and GPU availability

| | |
|---|---|
| **Date** | 2026-09-15 |
| **Status** | valid |
| **Triggered by** | The pivot to a self-hosted tool. Andrei: *"System should detect if GPU is available and run in either CPU or GPU accordingly. Please, check my machine — I know that I have GPU, but I never had chance to use it with local LM."* |
| **Artifacts** | `src/llmlc/hardware.py`, `tests/test_hardware.py` |

## Hypothesis

That a laptop GPU would be enough to run the local back-translator, making the "clone and run" promise credible rather than aspirational — but that 8 GB would be the binding constraint and might force a smaller model.

## What was tested

1. GPU presence, VRAM, compute capability, driver.
2. Whether GPU passthrough into Docker works under WSL2 — the part that usually breaks.
3. Whether the intended models fit in available VRAM.

## Setup

| | |
|---|---|
| Machine | WSL2 on Windows, 20 cores, 15 GB RAM, 928 GB free |
| Probes | `nvidia-smi`, `/usr/lib/wsl/lib`, `docker info`, `docker run --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi` |

## Results

| | |
|---|---|
| GPU | NVIDIA GeForce RTX 4060 Laptop, **8188 MiB**, driver 596.08, compute capability **8.9** (Ada — native bf16/FP8) |
| Docker | 27.5.1 with the **`nvidia` container runtime already registered** |
| Passthrough | **Works** — the container saw all 8188 MiB |
| torch | not installed |

**Memory fit at 8 GB:**

| Component | VRAM | Verdict |
|---|---|---|
| GlotLID (fastText) | CPU only, ~1.2 GB RAM | no GPU needed |
| DeBERTa-v3 NLI | ~0.9 GB fp16 | comfortable |
| MADLAD-400-3B-MT | ~6 GB fp16 / ~3 GB int8 | **the tight one** |
| MADLAD-400-10B | ~20 GB | does not fit |

All required components co-resident at int8 ≈ 5 GB.

## Conclusions

- 8 GB **decides quantisation, not feasibility**. The heavy path runs on a laptop.
- GPU-in-Docker was the real risk and it is already working, which removes the main setup obstacle for the self-hosted design.
- An 8 GB card should resolve to **int8, not fp16**: MADLAD-3B is ~6 GB of weights before activations, and fp16 should not be what a stranger hits on first run.

## Impact

- Validated the deployment pivot: no hosting, no rented GPU, no key custody.
- Four hardware profiles implemented (`gpu-fp16` / `gpu-int8` / `cpu` / `api`) with thresholds at 10 GB and 4 GB, overridable by `HARDWARE_PROFILE`, and **recorded on every result** — results from different back-translators are not comparable.
- The profile is resolved by the library and reported by `api`; it becomes authoritative in the `bt` service, which is the only container that will receive the GPU. `/hardware` inside the `api` container correctly reports `cpu`.
