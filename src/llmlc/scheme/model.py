"""Canonical language identity.

The core speaks plain BCP-47 (`kk`, `kk-Latn`, `sr-Cyrl-RS`). Systems with other
tag conventions -- including orders that differ from BCP-47, such as putting the
script last -- reach the core through a `SchemeAdapter`, never by changing this
model. That keeps one internal identity no matter whose locale list is loaded.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Scope = Literal["individual", "macrolanguage"]


class Language(BaseModel):
    tag: str = Field(description="Canonical BCP-47 tag; the identity used everywhere in the core")
    full: str | None = Field(None, description="Fully resolved language-Script-Region")
    lang: str
    iso639_3: str | None = None
    iso639_1: str | None = None
    script: str | None = None
    region: str | None = None
    name: str | None = None
    local_name: str | None = None
    scope: Scope = "individual"
    type: str | None = Field(None, description="ISO 639-3 type: L living, E extinct, H historical, A ancient, C constructed")
    macro: str | None = Field(None, description="ISO 639-3 code of the macrolanguage this belongs to")
    members: list[str] = Field(default_factory=list, description="ISO 639-3 codes of members, if a macrolanguage")
    cls: str = Field(description="Equivalence class `iso639_3|script`; base-language capability is probed once per class")
    aliases: list[str] = Field(default_factory=list)

    @property
    def is_macro(self) -> bool:
        return self.scope == "macrolanguage"


class SchemeMeta(BaseModel):
    name: str
    description: str | None = None
    canonical_tag_format: str | None = None
    generated_at: str | None = None
    generator: str | None = None
    sources: dict[str, str] = Field(default_factory=dict)
    attribution: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)


class Scheme(BaseModel):
    """A loaded locale list: the shipped public catalogue, or a user's own."""

    meta: SchemeMeta
    languages: dict[str, Language]

    def get(self, tag: str) -> Language | None:
        return self.languages.get(tag) or self.languages.get(tag.lower())

    def classes(self) -> dict[str, list[str]]:
        """Equivalence class -> tags. The ladder walks classes, not tags."""
        out: dict[str, list[str]] = {}
        for tag, lang in self.languages.items():
            out.setdefault(lang.cls, []).append(tag)
        return out

    def variants_of(self, tag: str) -> list[str]:
        """Other tags sharing this tag's equivalence class."""
        lang = self.get(tag)
        if lang is None:
            return []
        return [t for t in self.classes().get(lang.cls, []) if t != lang.tag]

    def macro_for(self, tag: str) -> Language | None:
        """The macrolanguage a tag inherits from, if any.

        A dialect with no marker list inherits its macrolanguage's tier as a
        placeholder -- see `variant_evidence` in docs/01.
        """
        lang = self.get(tag)
        if lang is None or not lang.macro:
            return None
        for cand in self.languages.values():
            if cand.iso639_3 == lang.macro and cand.is_macro:
                return cand
        return None
