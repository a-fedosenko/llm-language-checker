"""Loading schemes, and the adapter seam for foreign tag conventions."""
from __future__ import annotations

import json
import pathlib
from typing import Protocol, runtime_checkable

from .model import Language, Scheme

SCHEMES_DIR = pathlib.Path(__file__).resolve().parents[3] / "schemes"


def load_scheme(name_or_path: str = "default") -> Scheme:
    """Load `schemes/<name>.json`, or an explicit path.

    A user's own locale list is loaded the same way; it is never committed to
    this repository.
    """
    p = pathlib.Path(name_or_path)
    if not p.exists():
        p = SCHEMES_DIR / f"{name_or_path}.json"
    if not p.exists():
        raise FileNotFoundError(
            f"No scheme {name_or_path!r}. Looked in {SCHEMES_DIR}. "
            "Run `python scripts/build_default_scheme.py` to generate the shipped catalogue."
        )
    return Scheme.model_validate(json.loads(p.read_text(encoding="utf-8")))


@runtime_checkable
class SchemeAdapter(Protocol):
    """Translates between a foreign tag convention and canonical BCP-47.

    Implement one per external system. The Logrus TMS adapter -- whose tags put
    script last -- lives outside this repository, because that locale list is not
    ours to publish.
    """

    name: str

    def to_canonical(self, foreign_tag: str) -> str: ...

    def from_canonical(self, tag: str) -> str: ...


class IdentityAdapter:
    """For schemes already in canonical BCP-47, including the shipped default."""

    name = "identity"

    def to_canonical(self, foreign_tag: str) -> str:
        return foreign_tag

    def from_canonical(self, tag: str) -> str:
        return tag


def subtags(tag: str) -> tuple[str, str | None, str | None]:
    """Split a canonical tag into (language, script, region).

    Script is the 4-letter titlecase subtag, region the 2-letter uppercase or
    3-digit one. Order-independent, so it also tolerates reordered input.
    """
    parts = tag.replace("_", "-").split("-")
    lang, script, region = parts[0].lower(), None, None
    for p in parts[1:]:
        if len(p) == 4 and p.isalpha():
            script = p.title()
        elif (len(p) == 2 and p.isalpha()) or (len(p) == 3 and p.isdigit()):
            region = p.upper()
    return lang, script, region
