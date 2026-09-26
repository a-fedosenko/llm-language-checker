"""Generate the script-detection table from Unicode's own data.

Protocol 019. `probe/lid.detect_script` used to carry a hand-written list of 29
character-name prefixes, against a catalogue that asks about 202 scripts. Where
it could not name the expected script it returned `wrong_script` regardless of
what the model wrote -- and since protocol 018 that is an unappealable
`Unusable`.

The fix is not a longer hand-written list. ISO 15924 codes are not derivable from
character names (`LATIN` is `Latn`, not `Lati`), so the mapping has to come from
the authority. Three inputs, all from unicode.org:

  Scripts.txt              codepoint ranges -> Unicode script long name
  PropertyValueAliases.txt script long name -> ISO 15924 code
  Unihan_Variants.txt      which Han characters are simplified-only and which
                           traditional-only, which is the one distinction the
                           script property deliberately does not make

Output is committed, so a clean clone needs no network. Regenerate with:

    .venv/bin/python scripts/build_script_table.py --refresh
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.request
import zipfile

CACHE = pathlib.Path("data/cache")
OUT = pathlib.Path("data/unicode/scripts.json")
BASE = "https://www.unicode.org/Public/UCD/latest/ucd"

#: ISO 15924 codes for *combinations* of Unicode scripts. The script property has
#: no value for these -- Japanese text is Han plus Hiragana plus Katakana, and
#: ISO calls that `Jpan`. Without these three rules, switching to Unicode data
#: would have regressed Japanese and Korean, which the old hand-written table
#: happened to get right.
COMPOSITES = {
    "Jpan": ["Hani", "Hira", "Kana"],
    "Kore": ["Hang", "Hani"],
    "Hanb": ["Hani", "Bopo"],
}

#: Typographic variants of a script, not scripts. `Latf` is Fraktur, `Latg` is
#: Gaelic type, `Cyrs` is Old Church Slavonic. A text in any of them is encoded
#: as the parent script, so the parent is what detection can honestly return.
VARIANTS = {"Latf": "Latn", "Latg": "Latn", "Cyrs": "Cyrl", "Syrj": "Syrc",
            "Syrn": "Syrc", "Geok": "Geor", "Aran": "Arab", "Hanb": "Hani"}


def fetch(name: str, refresh: bool) -> pathlib.Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if path.exists() and not refresh:
        return path
    print(f"  fetching {name}", file=sys.stderr)
    urllib.request.urlretrieve(f"{BASE}/{name}", path)
    return path


def han_variants(refresh: bool) -> tuple[str, str]:
    """(simplified-only, traditional-only) Han characters.

    A character that *has* a traditional variant other than itself is a
    simplified form; one that has a simplified variant other than itself is a
    traditional form. Characters that are their own variant, or carry neither
    field, are shared between the two and carry no signal.
    """
    path = CACHE / "Unihan.zip"
    if not path.exists() or refresh:
        print("  fetching Unihan.zip", file=sys.stderr)
        urllib.request.urlretrieve(f"{BASE}/Unihan.zip", path)
    with zipfile.ZipFile(path) as z:
        text = z.read("Unihan_Variants.txt").decode("utf-8")

    simp, trad = set(), set()
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        cp, field, value = parts[0], parts[1], parts[2]
        try:
            ch = chr(int(cp.removeprefix("U+"), 16))
        except ValueError:
            continue
        others = {v for v in value.split() if v != cp}
        if not others:
            continue
        if field == "kTraditionalVariant":
            simp.add(ch)
        elif field == "kSimplifiedVariant":
            trad.add(ch)
    # A character can carry both fields; it then distinguishes nothing.
    both = simp & trad
    return "".join(sorted(simp - both)), "".join(sorted(trad - both))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download the UCD files")
    a = ap.parse_args()

    aliases: dict[str, str] = {}
    for line in fetch("PropertyValueAliases.txt", a.refresh).read_text(
            encoding="utf-8").splitlines():
        if line.startswith("sc ;"):
            p = [x.strip() for x in line.split(";")]
            aliases[p[2]] = p[1]

    ranges: list[tuple[int, int, str]] = []
    version = "unknown"
    for line in fetch("Scripts.txt", a.refresh).read_text(encoding="utf-8").splitlines():
        if line.startswith("# Scripts-"):
            version = line.removeprefix("# Scripts-").removesuffix(".txt").strip()
        line = line.split("#")[0].strip()
        if not line:
            continue
        rng, _, name = line.partition(";")
        name = name.strip()
        lo, _, hi = rng.strip().partition("..")
        code = aliases.get(name, name)
        ranges.append((int(lo, 16), int(hi or lo, 16), code))
    ranges.sort()

    simp, trad = han_variants(a.refresh)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "ucd_version": version,
        "source": BASE,
        "ranges": [list(r) for r in ranges],
        "composites": COMPOSITES,
        "variants": VARIANTS,
        "han_simplified_only": simp,
        "han_traditional_only": trad,
    }, ensure_ascii=False), encoding="utf-8")

    codes = {r[2] for r in ranges}
    print(f"UCD {version}: {len(ranges)} ranges, {len(codes)} scripts, "
          f"{len(simp)} simplified-only / {len(trad)} traditional-only Han chars")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
