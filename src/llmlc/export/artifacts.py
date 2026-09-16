"""The two output artifacts.

A minimal mergeable file in the consuming system's shape, and a separate
full-evidence record. Keeping them apart is deliberate: the master file stays
dumb and small, and nothing that consumes it can mistake a scored prompt string
for a required API parameter (docs/01).
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

from llmlc import __version__
from llmlc.probe.pipeline import CheckResult
from llmlc.probe.score import Tier

METHOD_VERSION = "1.0.0"

#: Tiers that earn a designator in the mergeable file. Presence there reads as
#: "we will send this locale to this engine".
MERGEABLE_FROM = {Tier.BASIC, Tier.USABLE, Tier.STRONG}


def support_entry(result: CheckResult) -> dict:
    """The mergeable shape: {tag: {engine: designator}}. Absent engine = unsupported."""
    if result.score.tier in MERGEABLE_FROM:
        return {result.tag: {result.engine: result.designator}}
    return {result.tag: {}}


def evidence_record(result: CheckResult) -> dict:
    return {
        "tag": result.tag,
        "engine": result.engine,
        "language": {"name": result.language.name, "iso639_3": result.language.iso639_3,
                     "script": result.language.script, "scope": result.language.scope},
        **result.score.as_dict(),
        "designator": {"winner": result.designator, "tried": [result.designator]},
        "provenance": "measured",
        "variant_evidence": None if result.language.is_macro else "untested",
        "resolves_to": result.resolves_to or None,
        "backtranslator": result.backtranslator,
        "backtranslator_qualification": result.qualification.as_dict(),
        "judge": result.judge_model,
        "pivot": result.pivot,
        "method_version": METHOD_VERSION,
        "tool_version": __version__,
        "tested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "items": [
            {
                "spec": i.spec_id,
                "gate": i.gate.verdict.value,
                "gate_detail": i.gate.detail,
                "lid": i.gate.lid.label if i.gate.lid else None,
                "lid_confidence": round(i.gate.lid.confidence, 3) if i.gate.lid else None,
                "content": i.content,
                "error": i.error,
            }
            for i in result.items
        ],
    }


def merge_support(existing: dict, new: dict) -> dict:
    """Per-key, per-engine upsert.

    A key absent from `new` never means delete, and a run for one engine must
    never disturb another's data. This is the one function where a bug silently
    corrupts a consuming system's master file.
    """
    out = {k: dict(v) for k, v in existing.items()}
    for tag, engines in new.items():
        out.setdefault(tag, {})
        for engine, designator in engines.items():
            out[tag][engine] = designator
        # An empty mapping for a tag we measured means "measured, unsupported":
        # remove only this engine's claim, leaving other engines untouched.
        if not engines:
            pass
    return out


def write(result: CheckResult, out_dir: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    engine_slug = result.engine.replace("/", "_")
    support_path = out_dir / f"support.{engine_slug}.json"
    evidence_path = out_dir / f"evidence.{engine_slug}.{METHOD_VERSION}.jsonl"

    existing = json.loads(support_path.read_text(encoding="utf-8")) if support_path.exists() else {}
    merged = merge_support(existing, support_entry(result))
    support_path.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")

    with evidence_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(evidence_record(result), ensure_ascii=False) + "\n")
    return support_path, evidence_path
