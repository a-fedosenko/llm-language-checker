"""Read-only access to results.

Reads the database when one is reachable, and falls back to the evidence files
on disk otherwise -- so the UI still works for someone who has only ever run the
CLI, and a browser session never becomes a reason to stand up Postgres.
"""
from __future__ import annotations

import json
import pathlib

RESULTS_DIR = pathlib.Path("data/results")


def _from_db() -> list[dict] | None:
    try:
        from llmlc.db import create_all, session
        from llmlc.db.repo import results_for
    except ImportError:
        return None
    try:
        create_all()
        with session() as s:
            rows = results_for(s)
            return [_serialise(r) for r in rows]
    except Exception:
        return None


def _serialise(r) -> dict:
    return {
        "tag": r.tag, "engine": r.engine, "tier": r.tier, "evidence": r.evidence,
        "s_lang": r.s_lang, "s_content": r.s_content, "ci": [r.ci_low, r.ci_high],
        "borderline": r.borderline, "reliability": r.reliability, "refusals": r.refusals,
        "designator": {"winner": r.designator, **(r.designator_detail or {})},
        "provenance": r.provenance, "variant_evidence": r.variant_evidence,
        "inherited_from": r.inherited_from, "resolves_to": r.resolves_to,
        "backtranslator": r.backtranslator,
        "backtranslator_qualification": r.backtranslator_qualification,
        "judge": r.judge, "pivot": r.pivot, "hardware_profile": r.hardware_profile,
        "method_version": r.method_version, "rungs_run": r.rungs_run,
        "calls": r.calls, "items": r.items, "notes": r.notes,
        "language": {"name": None},
        "tested_at": r.tested_at.isoformat() if r.tested_at else None,
        "source": "db",
    }


def _from_files(root: pathlib.Path | None = None) -> list[dict]:
    """Latest row per (engine, tag, method_version) from the append-only files."""
    latest: dict[tuple[str, str, str], dict] = {}
    for path in sorted((root or RESULTS_DIR).glob("evidence.*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                row["source"] = "file"
                latest[(row.get("engine", ""), row.get("tag", ""),
                        row.get("method_version", ""))] = row
    return list(latest.values())


def load_results(root: pathlib.Path | None = None) -> list[dict]:
    rows = _from_db() if root is None else None
    if not rows:
        rows = _from_files(root)
    return sorted(rows, key=lambda r: (r.get("engine", ""), r.get("tag", "")))


def summarise(rows: list[dict]) -> dict:
    tiers: dict[str, int] = {}
    evidence: dict[str, int] = {}
    engines: dict[str, int] = {}
    for r in rows:
        tiers[r.get("tier", "?")] = tiers.get(r.get("tier", "?"), 0) + 1
        evidence[r.get("evidence", "?")] = evidence.get(r.get("evidence", "?"), 0) + 1
        engines[r.get("engine", "?")] = engines.get(r.get("engine", "?"), 0) + 1
    return {"total": len(rows), "tiers": tiers, "evidence": evidence, "engines": engines}
