#!/usr/bin/env python3
"""Generate `schemes/default.json` — the public language catalogue shipped with
this project.

Built entirely from public sources so that no organisation's private locale list
is needed to run the tool:

  ISO 639-3 code table          (SIL)      language codes, scope, living/extinct
  ISO 639-3 macrolanguages      (SIL)      the official macrolanguage -> member map
  SIL langtags                  (SIL)      resolved lang-Script-Region, endonyms

Canonical identity in this project is plain BCP-47 (`kk`, `kk-Latn`, `sr-Cyrl-RS`).
Systems with other conventions -- including tag orders that differ from BCP-47 --
reach the core through a scheme adapter rather than by changing this format.

Usage:  python scripts/build_default_scheme.py [--refresh]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
OUT = ROOT / "schemes" / "default.json"

SOURCES = {
    "iso-639-3.tab":
        "https://iso639-3.sil.org/sites/iso639-3/files/downloads/iso-639-3.tab",
    "iso-639-3-macrolanguages.tab":
        "https://iso639-3.sil.org/sites/iso639-3/files/downloads/iso-639-3-macrolanguages.tab",
    "langtags.json":
        "https://ldml.api.sil.org/langtags.json",
}

ATTRIBUTION = [
    "ISO 639-3 code tables (c) SIL International, used under the ISO 639-3 terms of use.",
    "SIL langtags (c) SIL International, https://ldml.api.sil.org/langtags.json",
]


def fetch(refresh: bool = False) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    for name, url in SOURCES.items():
        dest = CACHE / name
        if dest.exists() and not refresh:
            continue
        print(f"  downloading {name} ...", file=sys.stderr)
        with urllib.request.urlopen(url, timeout=180) as r:
            dest.write_bytes(r.read())


def read_iso639_3() -> dict[str, dict]:
    """Id -> {part1, scope, type, name}. Scope: I individual, M macro, S special."""
    out = {}
    lines = (CACHE / "iso-639-3.tab").read_text(encoding="utf-8").splitlines()
    for line in lines[1:]:
        if not line.strip():
            continue
        f = line.split("\t")
        out[f[0]] = {"part1": f[3] or None, "scope": f[4], "type": f[5], "name": f[6]}
    return out


def read_macrolanguages() -> tuple[dict[str, str], dict[str, list[str]]]:
    """Returns (member -> macro, macro -> [members]). Retired members are skipped."""
    member_of, members = {}, defaultdict(list)
    lines = (CACHE / "iso-639-3-macrolanguages.tab").read_text(encoding="utf-8").splitlines()
    for line in lines[1:]:
        if not line.strip():
            continue
        macro, member, status = (line.split("\t") + ["", "", ""])[:3]
        if status.strip() == "R":          # retired
            continue
        member_of[member] = macro
        members[macro].append(member)
    return member_of, dict(members)


def build() -> dict:
    iso = read_iso639_3()
    member_of, macro_members = read_macrolanguages()
    langtags = json.loads((CACHE / "langtags.json").read_text(encoding="utf-8"))

    languages: dict[str, dict] = {}
    skipped_special = 0

    for e in langtags:
        tag = e.get("tag", "")
        if tag.startswith("_"):            # _conformance, _globalvar metadata rows
            continue
        iso3 = e.get("iso639_3")
        meta = iso.get(iso3, {}) if iso3 else {}
        if meta.get("scope") == "S":       # special codes (mul, und, zxx ...)
            skipped_special += 1
            continue

        script = e.get("script")
        region = e.get("region")
        scope = {"I": "individual", "M": "macrolanguage"}.get(meta.get("scope", "I"), "individual")

        languages[tag] = {
            "tag": tag,
            "full": e.get("full"),
            "lang": tag.split("-")[0],
            "iso639_3": iso3,
            "iso639_1": meta.get("part1"),
            "script": script,
            "region": region,
            "name": e.get("name"),
            "local_name": e.get("localname"),
            "scope": scope,
            "type": meta.get("type"),               # L living, E extinct, H historical, A ancient, C constructed
            "macro": member_of.get(iso3) if iso3 else None,
            "members": sorted(macro_members.get(iso3, [])) if scope == "macrolanguage" else [],
            # Equivalence class for base-language capability: one probe per class,
            # not per tag. Region never distinguishes a class; script does.
            "cls": f"{iso3 or tag.split('-')[0]}|{script or ''}",
            "aliases": sorted(e.get("tags", [])),
        }

    classes = defaultdict(list)
    for t, v in languages.items():
        classes[v["cls"]].append(t)

    return {
        "meta": {
            "name": "default",
            "description": "Public language catalogue built from ISO 639-3 and SIL langtags.",
            "canonical_tag_format": "BCP-47 (language[-Script][-Region])",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "generator": "scripts/build_default_scheme.py",
            "sources": SOURCES,
            "attribution": ATTRIBUTION,
            "counts": {
                "tags": len(languages),
                "classes": len(classes),
                "macrolanguages": sum(1 for v in languages.values() if v["scope"] == "macrolanguage"),
                "living": sum(1 for v in languages.values() if v["type"] == "L"),
                "skipped_special": skipped_special,
            },
        },
        "languages": languages,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download source tables")
    a = ap.parse_args()

    fetch(a.refresh)
    scheme = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(scheme, ensure_ascii=False, indent=1, sort_keys=False), encoding="utf-8")

    c = scheme["meta"]["counts"]
    print(f"wrote {OUT.relative_to(ROOT)}  "
          f"{c['tags']} tags, {c['classes']} classes, "
          f"{c['macrolanguages']} macrolanguages, {c['living']} living "
          f"({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
