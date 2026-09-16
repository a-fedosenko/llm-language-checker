#!/usr/bin/env python3
"""Build back-translator control texts from FLORES-200.

A control is aligned text whose pivot meaning we already know. Handing it to a
back-translator and checking what comes back is the only way to tell "the model
under test cannot write this language" from "our instrument cannot read it" --
a distinction that moved a real verdict by two tiers (docs/03, S1).

FLORES-200 is CC BY-SA 4.0. Share-alike attaches to redistributing derived text,
so the corpus is downloaded on first use and cached under data/, never committed.

Usage:  python scripts/build_controls.py [--items 4] [--refresh]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tarfile
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from llmlc.scheme import load_scheme  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
ARCHIVE = CACHE / "flores200.tar.gz"
EXTRACTED = CACHE / "flores200_dataset"
OUT = ROOT / "data" / "controls" / "flores.json"
URL = "https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz"

PIVOT = "eng_Latn"
ATTRIBUTION = ("FLORES-200 (c) Meta AI, CC BY-SA 4.0. "
               "https://github.com/facebookresearch/flores")


def fetch(refresh: bool = False) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    if not ARCHIVE.exists() or refresh:
        print("  downloading FLORES-200 (~25 MB) ...", file=sys.stderr)
        with urllib.request.urlopen(URL, timeout=600) as r:
            ARCHIVE.write_bytes(r.read())
    if not EXTRACTED.exists() or refresh:
        with tarfile.open(ARCHIVE) as t:
            t.extractall(CACHE, filter="data")


def tag_index(scheme) -> dict[tuple[str, str], str]:
    """(iso639_3, script) -> canonical tag, preferring the shortest form.

    Falls back to the macrolanguage where FLORES names a member code that the
    catalogue represents by its macro tag -- arb under ar, azj under az, khk
    under mn, lvs under lv, and so on.
    """
    index: dict[tuple[str, str], str] = {}
    for tag, lang in scheme.languages.items():
        key = (lang.iso639_3, lang.script)
        if key[0] and (key not in index or len(tag) < len(index[key])):
            index[key] = tag
    # Macro fallback: a member code resolves to its macrolanguage's tag.
    for tag, lang in scheme.languages.items():
        if not lang.is_macro:
            continue
        for member in lang.members:
            key = (member, lang.script)
            index.setdefault(key, tag)
    return index


def build(n_items: int) -> dict:
    scheme = load_scheme("default")
    index = tag_index(scheme)

    pivot_lines = (EXTRACTED / "dev" / f"{PIVOT}.dev").read_text(encoding="utf-8").splitlines()
    # Mid-length sentences: long enough to carry meaning, short enough to
    # back-translate cheaply and to keep chrF++ stable.
    chosen = [i for i, s in enumerate(pivot_lines) if 60 <= len(s) <= 160][:n_items]

    controls: dict[str, dict] = {}
    unmapped: list[str] = []
    for path in sorted((EXTRACTED / "dev").glob("*.dev")):
        code = path.stem
        if code == PIVOT:
            continue
        iso, _, script = code.partition("_")
        tag = index.get((iso, script))
        if not tag:
            unmapped.append(code)
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) != len(pivot_lines):
            unmapped.append(code)
            continue
        # First mapping wins, so a base tag is not overwritten by a variant.
        controls.setdefault(tag, {
            "flores_code": code,
            "items": [{"text": lines[i], "reference": pivot_lines[i]} for i in chosen],
        })

    return {
        "meta": {
            "source": "FLORES-200 dev split",
            "url": URL,
            "license": "CC BY-SA 4.0",
            "attribution": ATTRIBUTION,
            "pivot": "en",
            "kind": "reference",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "items_per_language": len(chosen),
            "counts": {"languages": len(controls), "unmapped": len(unmapped)},
            "unmapped": unmapped,
        },
        "controls": controls,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", type=int, default=4, help="control sentences per language")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()

    fetch(a.refresh)
    data = build(a.items)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    c = data["meta"]["counts"]
    print(f"wrote {OUT.relative_to(ROOT)}  {c['languages']} languages "
          f"x {data['meta']['items_per_language']} items  ({c['unmapped']} unmapped)")


if __name__ == "__main__":
    main()
