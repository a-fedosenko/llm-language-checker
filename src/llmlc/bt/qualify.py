"""Back-translator qualification.

Before a back-translator's output is trusted for a language, it must recover
known facts from text whose meaning we already know. This is not bookkeeping --
it is what separates "the model under test cannot write this language" from
"our instrument cannot read it".

Observed on the first live run: gpt-4o refuses to *write* Chuvash but silently
*fabricates* a reading of it, rendering a correct Chuvash passage as "The sun
rises in the east." Without this check a correct model scores as a failure.
Writing failures are visible -- refusal, degeneration, wrong language, all caught
free by the gate. Reading failures are invisible without a control.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from enum import Enum

from llmlc.bt.remote import RemoteBackTranslator
from llmlc.client import OpenAICompatClient
from llmlc.probe.judge import judge as run_judge

CONTROLS_PATH = pathlib.Path(__file__).resolve().parents[3] / "data" / "controls" / "controls.json"

#: Share of known facts a back-translator must recover to be trusted for a language.
MIN_RECALL = 0.60


class QualStatus(str, Enum):
    QUALIFIED = "qualified"
    FAILED = "failed"
    NO_CONTROL = "no-control"


@dataclass(frozen=True)
class Qualification:
    status: QualStatus
    recall: float
    backtranslator: str
    tag: str
    detail: str = ""

    @property
    def trustworthy(self) -> bool:
        """NO_CONTROL is not a pass; it is an admission, recorded on the result."""
        return self.status is QualStatus.QUALIFIED

    def as_dict(self) -> dict:
        return {"status": self.status.value, "recall": round(self.recall, 3),
                "backtranslator": self.backtranslator, "detail": self.detail}


def load_controls(path: pathlib.Path | None = None) -> dict[str, list[dict]]:
    p = path or CONTROLS_PATH
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8")).get("controls", {})


def qualify(bt: RemoteBackTranslator, client: OpenAICompatClient, judge_model: str,
            tag: str, controls: dict[str, list[dict]] | None = None) -> Qualification:
    """Run the control texts for `tag` through `bt` and grade what comes back."""
    controls = controls if controls is not None else load_controls()
    items = controls.get(tag) or []
    if not items:
        return Qualification(QualStatus.NO_CONTROL, 0.0, bt.id, tag,
                             "No control text for this language; quality is not assessable.")

    recalls: list[float] = []
    for item in items:
        translated = bt.translate(item["text"])
        if not translated.ok:
            return Qualification(QualStatus.FAILED, 0.0, bt.id, tag,
                                 f"back-translation failed: {translated.error}")
        judgement = run_judge(client, judge_model, translated.text or "", item["facts"])
        if not judgement.ok:
            return Qualification(QualStatus.FAILED, 0.0, bt.id, tag,
                                 f"judge failed during qualification: {judgement.error}")
        recalls.append(judgement.recall)

    recall = sum(recalls) / len(recalls)
    if recall >= MIN_RECALL:
        return Qualification(QualStatus.QUALIFIED, recall, bt.id, tag)
    return Qualification(
        QualStatus.FAILED, recall, bt.id, tag,
        f"recovered only {recall:.0%} of known facts from text of known meaning; "
        "this back-translator cannot read the language")
