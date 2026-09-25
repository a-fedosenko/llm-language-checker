"""Export adapters: canonical results -> an external system's file shape.

The core emits results keyed by canonical BCP-47. Any consuming system with its
own tag convention gets an adapter, so that no organisation's locale list is
baked into this project. The Logrus TMS adapter -- whose tags put script last --
lives outside this repository, because that list is not ours to publish.

The merge rule matters more than the shapes: **per-key, per-engine upsert**. A
key absent from a run never means delete, and a run for one engine must never
disturb another's data. This is the one function where a bug silently corrupts a
consuming system's master file.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from llmlc.export.artifacts import MERGEABLE_FROM

#: Tiers that earn a designator in the mergeable file, as the strings a stored
#: row carries. Derived from `MERGEABLE_FROM` rather than restated: this file
#: held its own hand-written copy of the set, which protocol 018's rename would
#: have turned into a silent empty export -- every tier excluded, no error, a
#: consuming system quietly told nothing is supported.
MERGEABLE_TIERS = {t.value for t in MERGEABLE_FROM}


@runtime_checkable
class ExportAdapter(Protocol):
    name: str

    def external_tag(self, canonical_tag: str) -> str | None:
        """External key for a canonical tag, or None to omit it entirely."""

    def engine_key(self, engine: str) -> str:
        """External engine identifier."""


class CanonicalAdapter:
    """Identity: canonical tags, `mt.<engine>` keys.

    `mt.*` covers both MT engines and LLMs, because an LLM can be used as an MT
    engine and the consuming system generates one list of engines.
    """

    name = "canonical"

    def external_tag(self, canonical_tag: str) -> str | None:
        return canonical_tag

    def engine_key(self, engine: str) -> str:
        return engine if engine.startswith("mt.") else f"mt.{engine}"


class MappedAdapter(CanonicalAdapter):
    """Adapter driven by an explicit canonical -> external tag map.

    This is how an organisation plugs its own locale list in without shipping it:
    the map is a gitignored JSON file.
    """

    def __init__(self, name: str, mapping: dict[str, str],
                 engine_names: dict[str, str] | None = None) -> None:
        self.name = name
        self.mapping = mapping
        self.engine_names = engine_names or {}

    def external_tag(self, canonical_tag: str) -> str | None:
        return self.mapping.get(canonical_tag)

    def engine_key(self, engine: str) -> str:
        return self.engine_names.get(engine, super().engine_key(engine))


def build_support(rows: list[dict], adapter: ExportAdapter | None = None) -> dict:
    """Mergeable artifact: {external_tag: {engine_key: designator}}.

    A measured-but-unsupported language appears with an empty mapping, matching
    the convention of the consuming file, so the difference between "measured,
    no support" and "never measured" survives the export.
    """
    adapter = adapter or CanonicalAdapter()
    out: dict[str, dict] = {}
    for row in rows:
        tag = adapter.external_tag(row["tag"])
        if tag is None:
            continue
        entry = out.setdefault(tag, {})
        if row.get("tier") in MERGEABLE_TIERS:
            entry[adapter.engine_key(row["engine"])] = row["designator"]
    return out


def merge_support(existing: dict, new: dict) -> dict:
    """Per-key, per-engine upsert.

    Keys absent from `new` are preserved. Engines absent from `new[key]` are
    preserved. Nothing is ever deleted implicitly.
    """
    out = {k: dict(v) for k, v in existing.items()}
    for tag, engines in new.items():
        out.setdefault(tag, {})
        out[tag].update(engines)
    return out


def removals(existing: dict, new: dict, engine_key: str) -> dict:
    """Explicit removal set: keys where this engine previously claimed support
    and the new run measured none. Returned rather than applied, so dropping a
    claim is always a deliberate act by the caller.
    """
    out = {}
    for tag, engines in new.items():
        if engine_key not in engines and engine_key in existing.get(tag, {}):
            out[tag] = existing[tag][engine_key]
    return out
