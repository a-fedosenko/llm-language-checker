"""Protocol 019 — what the script check can and cannot name.

No model calls. Builds a script-hint table from Unicode character names, compares
its coverage against the shipped hand-written one, and tests the parts of the
problem that a table cannot fix.

    .venv/bin/python scripts/script_audit.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import unicodedata
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from llmlc.probe.lid import _SCRIPT_HINTS, detect_script
from llmlc.scheme.loader import load_scheme

STUDY = pathlib.Path("data/calibration/study.json")

#: Unicode script names (as they appear in character names) -> ISO 15924.
#: Only the entries where the two differ need stating; the rest are derivable by
#: titlecasing the first four letters, which is how ISO 15924 was built.
ALIASES = {
    "CJK": "Hani", "HIRAGANA": "Jpan", "KATAKANA": "Jpan",
    "HANGUL": "Hang",          # the shipped table said "Kore"; the scheme says "Hang"
    "NKO": "Nkoo", "OL CHIKI": "Olck", "LAO": "Laoo", "YI": "Yiii",
    "CANADIAN": "Cans", "MEETEI": "Mtei", "TAI LE": "Tale", "NEW TAI LUE": "Talu",
    "PHAGS-PA": "Phag", "SYLOTI": "Sylo", "SAURASHTRA": "Saur",
}


def derive_hints() -> dict[str, str]:
    """Script prefixes taken from the Unicode database rather than hand-listed.

    Walks the BMP plus the supplementary planes that carry scripts, reads each
    character's name, and keeps the leading words up to the first structural
    keyword (LETTER, SYLLABLE, VOWEL, SIGN, DIGIT, ...). That prefix is the
    script's Unicode name.
    """
    KEYWORDS = {"LETTER", "SYLLABLE", "SYLLABICS", "VOWEL", "SIGN", "DIGIT",
                "CHARACTER", "IDEOGRAPH", "POINT", "ACCENT", "MARK", "TONE",
                "CONSONANT", "NUMBER", "FRACTION", "SEQUENCE"}
    seen: Counter[str] = Counter()
    for cp in list(range(0x0000, 0x30000)):
        ch = chr(cp)
        if not ch.isalpha():
            continue
        try:
            name = unicodedata.name(ch)
        except ValueError:
            continue
        words = name.split()
        prefix = []
        for w in words:
            if w in KEYWORDS:
                break
            prefix.append(w)
        if not prefix:
            continue
        seen[" ".join(prefix)] += 1

    hints: dict[str, str] = {}
    for prefix in seen:
        code = ALIASES.get(prefix)
        if code is None:
            head = prefix.split()[0]
            code = ALIASES.get(head)
        if code is None:
            flat = prefix.replace(" ", "").replace("-", "")
            if len(flat) < 4:
                continue
            code = flat[:4].title()
        hints[prefix] = code
    return hints


def main() -> int:
    scheme = load_scheme("default")
    wanted = Counter(l.script for l in scheme.languages.values() if l.script)
    shipped = set(_SCRIPT_HINTS.values())
    derived_map = derive_hints()
    derived = set(derived_map.values())

    print(f"scheme asks for              {len(wanted)} distinct scripts")
    print(f"shipped table can emit       {len(shipped)}")
    print(f"derived table can emit       {len(derived)}")

    NON_SCRIPT = {"Zyyy", "Zxxx", "Zzzz", "Brai"}
    real = {s: n for s, n in wanted.items() if s not in NON_SCRIPT}
    cov_old = {s for s in real if s in shipped}
    cov_new = {s for s in real if s in derived}
    print()
    print(f"real scripts the scheme wants            {len(real)}")
    print(f"  covered by the shipped table           {len(cov_old)}"
          f"   ({sum(real[s] for s in cov_old)} tags)")
    print(f"  covered by the derived table           {len(cov_new)}"
          f"   ({sum(real[s] for s in cov_new)} tags)")
    still = sorted(real.keys() - cov_new, key=lambda s: -real[s])
    print(f"  still uncovered                        {len(still)}"
          f"   ({sum(real[s] for s in still)} tags)")
    print("   ", ", ".join(f"{s}({real[s]})" for s in still[:20]))

    # -- H1: the six blocked classes in the planned scan ---------------------
    print("\nH1 — the six classes the planned scan could not pass")
    for cls in ("Hang", "Hans", "Hant", "Laoo", "Olck"):
        print(f"  {cls:6} shipped {'yes' if cls in shipped else 'NO ':3}"
              f"   derived {'yes' if cls in derived else 'NO'}")

    # -- H2: can block detection separate Hans from Hant? --------------------
    study = json.loads(STUDY.read_text(encoding="utf-8"))
    by_tag = {r["tag"]: r for r in study["languages"]}
    print("\nH2 — does block detection separate simplified from traditional?")
    codes = Counter()
    for tag in ("zh-CN", "yue"):
        for item in by_tag.get(tag, {}).get("items", []):
            for field in ("translation", "reference"):
                text = item.get(field) or ""
                if text:
                    codes[(tag, field, detect_script(text))] += 1
    for (tag, field, code), n in sorted(codes.items()):
        print(f"  {tag:7} {field:12} -> {code}   x{n}")

    # -- H4: the length floor in dense scripts -------------------------------
    print("\nH4 — MIN_CHARS = 25 against dense scripts")
    DENSE = {"zh-CN": "Hans", "yue": "Hant", "ja": "Jpan", "ko-Hang": "Hang",
             "my": "Mymr", "th": "Thai"}
    short_ok = total = 0
    for tag in DENSE:
        rec = by_tag.get(tag)
        if not rec:
            continue
        for item in rec["items"]:
            text = (item.get("translation") or "").strip()
            if not text:
                continue
            total += 1
            recall = item.get("recall")
            if len(text) < 25:
                flag = "under 25" if recall is None or recall < 0.75 else "UNDER 25, recall ok"
                print(f"  {tag:8} {len(text):3} chars  recall {recall}   {flag}")
                if recall is not None and recall >= 0.75:
                    short_ok += 1
    print(f"  {short_ok} of {total} dense-script items are adequate but under the floor")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
