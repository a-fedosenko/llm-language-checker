"""Turning a ladder result into a persisted row, and back."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from llmlc import __version__
from llmlc.db.models import Result
from llmlc.db.repo import upsert_result
from llmlc.export.artifacts import METHOD_VERSION


def to_row(result, *, job_id: int | None = None, hardware_profile: str | None = None) -> dict:
    s = result.score
    lang = result.language
    return {
        "job_id": job_id,
        "engine": result.engine,
        "tag": result.tag,
        "cls": lang.cls if lang else "",
        "tier": s.tier.value,
        "evidence": s.evidence.value,
        "s_lang": s.s_lang,
        "s_content": s.s_content,
        "ci_low": s.ci[0],
        "ci_high": s.ci[1],
        "borderline": s.borderline,
        "reliability": s.reliability,
        "refusals": s.refusals,
        "designator": result.designator,
        "designator_detail": {
            "kinds": list(getattr(result, "designator_kinds", ()) or ()),
            "tried": [{"kind": t.kind, "kinds": list(t.kinds), "value": t.value,
                       "gate_rate": round(t.rate, 3)}
                      for t in getattr(result, "trials", [])],
            "beat_incumbent": getattr(result, "beat_incumbent", None),
        },
        "provenance": "measured",
        "variant_evidence": None if (lang and lang.is_macro) else "untested",
        "inherited_from": getattr(result, "inherited_from", None),
        "resolves_to": result.resolves_to or None,
        "backtranslator": result.backtranslator,
        "backtranslator_qualification": (result.qualification.as_dict()
                                         if result.qualification else {}),
        "judge": result.judge_model,
        "pivot": result.pivot,
        "hardware_profile": hardware_profile,
        "method_version": METHOD_VERSION,
        "tool_version": __version__,
        "rungs_run": getattr(result, "rungs_run", None),
        "calls": getattr(result, "calls", None),
        "items": [
            {"spec": i.spec_id, "gate": i.gate.verdict.value, "gate_detail": i.gate.detail,
             "lid": i.gate.lid.label if i.gate.lid else None,
             "lid_confidence": round(i.gate.lid.confidence, 3) if i.gate.lid else None,
             "content": i.content, "error": i.error}
            for i in result.items
        ],
        "notes": s.notes,
        "tested_at": datetime.now(timezone.utc),
    }


def save(session: Session, result, **kw) -> tuple[Result, str]:
    return upsert_result(session, to_row(result, **kw))
