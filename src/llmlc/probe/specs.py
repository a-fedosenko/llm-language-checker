"""Content specifications: what to say, and the checklist that grades it."""
from __future__ import annotations

import json
import pathlib

from pydantic import BaseModel

SPECS_PATH = pathlib.Path(__file__).resolve().parents[3] / "data" / "specs" / "specs.json"


class Spec(BaseModel):
    id: str
    scenario: str
    facts: list[str]


def load_specs(path: pathlib.Path | None = None) -> list[Spec]:
    raw = json.loads((path or SPECS_PATH).read_text(encoding="utf-8"))
    return [Spec.model_validate(s) for s in raw["specs"]]
