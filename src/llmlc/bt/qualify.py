"""Back-translator qualification.

Before a back-translator is trusted for a language, it must recover known meaning
from text whose meaning we already know. This separates "the model under test
cannot write this language" from "our instrument cannot read it" -- a distinction
that moved a real verdict two tiers on the first live run: gpt-4o refuses to
*write* Chuvash but silently *fabricates* a reading of it, rendering known
control text as "A man is walking. He is wearing a white shirt."

A model that cannot read does not refuse; it invents. So writing failures are
visible (refusal, degeneration, wrong language -- all caught free by the gate)
while reading failures are silent and corrupt the score of a model that did
nothing wrong.

Two control kinds:
  reference  FLORES-200 aligned text; graded by chrF++ against the known pivot
             sentence. Deterministic, and costs no judge call.
  facts      hand-seeded text with a fact checklist, for languages FLORES lacks
             (Chuvash among them). Graded by the judge.
"""
from __future__ import annotations

import json
import pathlib
import time
from dataclasses import dataclass
from enum import Enum

from llmlc.bt.remote import RemoteBackTranslator
from llmlc.client import OpenAICompatClient
from llmlc.probe.chrf import chrf
from llmlc.probe.judge import judge as run_judge

CONTROLS_DIR = pathlib.Path(__file__).resolve().parents[3] / "data" / "controls"
SEED_CONTROLS = CONTROLS_DIR / "controls.json"
FLORES_CONTROLS = CONTROLS_DIR / "flores.json"
CACHE_PATH = CONTROLS_DIR / ".qualification_cache.json"

#: chrF++ of a back-translation against the known pivot sentence. Measured on
#: real cases: a fabricating back-translator scored 10.5, a correct one 81.9.
MIN_CHRF = 30.0
#: Share of known facts recovered, for hand-seeded controls.
MIN_RECALL = 0.60


class QualStatus(str, Enum):
    QUALIFIED = "qualified"
    FAILED = "failed"
    NO_CONTROL = "no-control"


@dataclass(frozen=True)
class Qualification:
    status: QualStatus
    score: float
    backtranslator: str
    tag: str
    kind: str = ""          # "reference" | "facts" | ""
    detail: str = ""

    @property
    def trustworthy(self) -> bool:
        """NO_CONTROL is not a pass; it is an admission, recorded on the result."""
        return self.status is QualStatus.QUALIFIED

    def as_dict(self) -> dict:
        return {"status": self.status.value, "score": round(self.score, 2),
                "kind": self.kind, "backtranslator": self.backtranslator,
                "detail": self.detail}


def load_controls(pivot: str = "en") -> dict[str, dict]:
    """Merged control set. FLORES supplies breadth; hand seeds fill its gaps.

    `pivot` only matters for the pivot language itself -- see `pivot_control`.
    Every other control is already expressed against English.
    """
    out: dict[str, dict] = {}
    if FLORES_CONTROLS.exists():
        data = json.loads(FLORES_CONTROLS.read_text(encoding="utf-8"))
        for tag, entry in data.get("controls", {}).items():
            out[tag] = {"kind": "reference", "items": entry["items"]}
    if SEED_CONTROLS.exists():
        data = json.loads(SEED_CONTROLS.read_text(encoding="utf-8"))
        for tag, items in data.get("controls", {}).items():
            out.setdefault(tag, {"kind": "facts", "items": items})
    if pivot != "en":
        derived = pivot_control(out, pivot)
        if derived:
            out["en"] = derived
    return out


def pivot_control(controls: dict[str, dict], pivot: str) -> dict | None:
    """A control for English, built by reading an aligned pair backwards.

    Every FLORES control is (target text -> English reference), so the entry for
    German already contains exactly what is needed to grade a back-translation
    *into* German: swap the sides and it becomes (English text -> German
    reference). The corpus is aligned, so this is the same data, not new data --
    which is why measuring the pivot language needs no extra download and no
    hand-written text.

    Returns None when the chosen pivot has no reference control of its own, since
    inventing one would mean grading a back-translator against text nobody
    checked.
    """
    entry = controls.get(pivot)
    if not entry or entry.get("kind") != "reference":
        return None
    items = [{"text": i["reference"], "reference": i["text"]}
             for i in entry.get("items", []) if i.get("text") and i.get("reference")]
    return {"kind": "reference", "items": items, "derived_from": pivot} if items else None


class QualificationCache:
    """Qualification changes only when the back-translator does, so it is cached
    across runs rather than re-paid per language per run."""

    def __init__(self, path: pathlib.Path | None = None) -> None:
        self.path = path or CACHE_PATH
        self._data: dict[str, dict] = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._data = {}

    @staticmethod
    def _key(bt_id: str, tag: str) -> str:
        return f"{bt_id}||{tag}"

    def get(self, bt_id: str, tag: str) -> Qualification | None:
        row = self._data.get(self._key(bt_id, tag))
        if not row:
            return None
        return Qualification(QualStatus(row["status"]), row["score"], bt_id, tag,
                             row.get("kind", ""), row.get("detail", ""))

    def put(self, q: Qualification) -> None:
        self._data[self._key(q.backtranslator, q.tag)] = {
            **q.as_dict(), "tag": q.tag, "at": time.time()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=1),
                             encoding="utf-8")


def _qualify_reference(bt: RemoteBackTranslator, tag: str, items: list[dict]) -> Qualification:
    scores = []
    for item in items:
        translated = bt.translate(item["text"])
        if not translated.ok:
            return Qualification(QualStatus.FAILED, 0.0, bt.id, tag, "reference",
                                 f"back-translation failed: {translated.error}")
        scores.append(chrf(translated.text or "", item["reference"]))
    mean = sum(scores) / len(scores)
    if mean >= MIN_CHRF:
        return Qualification(QualStatus.QUALIFIED, mean, bt.id, tag, "reference")
    return Qualification(QualStatus.FAILED, mean, bt.id, tag, "reference",
                         f"chrF++ {mean:.1f} against known reference text "
                         "— this back-translator cannot read the language")


def _qualify_facts(bt: RemoteBackTranslator, client: OpenAICompatClient, judge_model: str,
                   tag: str, items: list[dict]) -> Qualification:
    recalls = []
    for item in items:
        translated = bt.translate(item["text"])
        if not translated.ok:
            return Qualification(QualStatus.FAILED, 0.0, bt.id, tag, "facts",
                                 f"back-translation failed: {translated.error}")
        judgement = run_judge(client, judge_model, translated.text or "", item["facts"])
        if not judgement.ok:
            return Qualification(QualStatus.FAILED, 0.0, bt.id, tag, "facts",
                                 f"judge failed during qualification: {judgement.error}")
        recalls.append(judgement.recall)
    mean = sum(recalls) / len(recalls)
    if mean >= MIN_RECALL:
        return Qualification(QualStatus.QUALIFIED, mean, bt.id, tag, "facts")
    return Qualification(QualStatus.FAILED, mean, bt.id, tag, "facts",
                         f"recovered only {mean:.0%} of known facts from text of known "
                         "meaning — this back-translator cannot read the language")


def qualify(bt: RemoteBackTranslator, client: OpenAICompatClient, judge_model: str,
            tag: str, controls: dict[str, dict] | None = None,
            cache: QualificationCache | None = None) -> Qualification:
    if cache is not None:
        cached = cache.get(bt.id, tag)
        if cached is not None:
            return cached

    controls = controls if controls is not None else load_controls()
    entry = controls.get(tag)
    if not entry or not entry.get("items"):
        return Qualification(QualStatus.NO_CONTROL, 0.0, bt.id, tag, "",
                             "No control text for this language; quality is not assessable.")

    if entry["kind"] == "reference":
        q = _qualify_reference(bt, tag, entry["items"])
    else:
        q = _qualify_facts(bt, client, judge_model, tag, entry["items"])

    if cache is not None:
        cache.put(q)
    return q


def route(candidates: list[RemoteBackTranslator], client: OpenAICompatClient,
          judge_model: str, tag: str, controls: dict[str, dict] | None = None,
          cache: QualificationCache | None = None) -> tuple[RemoteBackTranslator, Qualification]:
    """Pick the first back-translator that qualifies for this language.

    No single back-translator reads every language -- gpt-4o fabricates Chuvash,
    deepseek reads it correctly -- so the choice is per language, not per run.
    Returns the last attempt when none qualify, so the caller can report why.
    """
    last = None
    for bt in candidates:
        q = qualify(bt, client, judge_model, tag, controls, cache)
        if q.trustworthy:
            return bt, q
        last = (bt, q)
    return last if last else (candidates[0], Qualification(
        QualStatus.NO_CONTROL, 0.0, candidates[0].id, tag))
