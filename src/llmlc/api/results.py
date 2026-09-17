"""Read-only access to result artifacts on disk.

The UI is deliberately a reader: scans are started from the CLI, and the browser
shows what has been measured. Persistence and a job API arrive in S4.
"""
from __future__ import annotations

import json
import pathlib
from functools import lru_cache

RESULTS_DIR = pathlib.Path("data/results")


def evidence_files(root: pathlib.Path | None = None) -> list[pathlib.Path]:
    return sorted((root or RESULTS_DIR).glob("evidence.*.jsonl"))


@lru_cache(maxsize=1)
def _cache_token() -> float:
    return 0.0


def load_results(root: pathlib.Path | None = None) -> list[dict]:
    """Latest row per (engine, tag, method_version).

    The evidence file is append-only, so a language measured twice appears twice;
    the last write wins, which is what a reader wants to see.
    """
    latest: dict[tuple[str, str, str], dict] = {}
    for path in evidence_files(root):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = (row.get("engine", ""), row.get("tag", ""),
                       row.get("method_version", ""))
                latest[key] = row
    return sorted(latest.values(), key=lambda r: (r.get("engine", ""), r.get("tag", "")))


def summarise(rows: list[dict]) -> dict:
    tiers: dict[str, int] = {}
    evidence: dict[str, int] = {}
    engines: dict[str, int] = {}
    for r in rows:
        tiers[r.get("tier", "?")] = tiers.get(r.get("tier", "?"), 0) + 1
        evidence[r.get("evidence", "?")] = evidence.get(r.get("evidence", "?"), 0) + 1
        engines[r.get("engine", "?")] = engines.get(r.get("engine", "?"), 0) + 1
    return {"total": len(rows), "tiers": tiers, "evidence": evidence, "engines": engines}
