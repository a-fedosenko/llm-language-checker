"""Language identification.

LID is deliberately local and deliberately not an LLM: GlotLID covers 2,102
language-script labels, runs on CPU, costs nothing, and is more accurate at this
task than asking a model (docs/01). It is what makes most negatives free.

Falls back to a script-block check when the model file is absent, so the tool
still runs -- with reduced power, which the result records honestly.
"""
from __future__ import annotations

import bisect
import json
import pathlib
from dataclasses import dataclass
from functools import lru_cache

MODEL_PATH = pathlib.Path(__file__).resolve().parents[3] / "data" / "models" / "glotlid_v3.bin"
MODEL_URL = "https://huggingface.co/cis-lmu/glotlid/resolve/main/model_v3.bin"

# Script detection, from Unicode's own data rather than a hand-written list.
#
# Protocol 019: the previous version matched 29 character-name prefixes against
# a catalogue that asks about 202 scripts, and returned `wrong_script` for every
# script it could not name -- an unappealable `Unusable` since protocol 018. ISO
# 15924 codes cannot be derived from character names (`LATIN` is `Latn`, not
# `Lati`), so the table is generated from the UCD by scripts/build_script_table.py
# and committed.
SCRIPT_TABLE = pathlib.Path(__file__).resolve().parents[3] / "data" / "unicode" / "scripts.json"

#: ISO 15924 codes for scripts that exist but are not encoded in Unicode, or are
#: undeciphered, historic-only or invented. A language whose scheme entry asks
#: for one of these cannot have its script verified by any means available here,
#: so the gate must abstain rather than convict.
UNENCODED = frozenset({
    "Afak", "Blis", "Chis", "Cirt", "Inds", "Jurc", "Kitl", "Kpel", "Leke",
    "Loma", "Maya", "Moon", "Nkdb", "Nkgb", "Pelm", "Piqd", "Psin", "Ranj",
    "Roro", "Sara", "Syrj", "Teng", "Toto", "Visp", "Wole", "Zsye", "Zsym",
})

#: Codes that assert no script: undetermined, unwritten, uncoded. Asking whether
#: text is "in Zyyy" is not a question, so the gate skips the check entirely.
NO_SCRIPT_CLAIM = frozenset({"Zyyy", "Zxxx", "Zzzz", "Zinh"})

#: Braille is a transcription of another script, and nothing the tool generates
#: would legitimately be in it.
UNSCANNABLE = frozenset({"Brai"})


@lru_cache(maxsize=1)
def _table() -> dict:
    return json.loads(SCRIPT_TABLE.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _lookup() -> tuple[list[int], list[str]]:
    """Sorted range starts and their scripts, for bisect."""
    rows = _table()["ranges"]
    return [r[0] for r in rows], rows


def _script_of(ch: str) -> str | None:
    starts, rows = _lookup()
    i = bisect.bisect_right(starts, ord(ch)) - 1
    if i < 0:
        return None
    lo, hi, code = rows[i]
    return code if lo <= ord(ch) <= hi else None


def script_is_verifiable(expect: str | None) -> bool:
    """Can the expected script be checked at all?

    False for a script Unicode does not encode, for Braille, and for the codes
    that assert no script. The caller must abstain rather than convict -- before
    protocol 019 these were 1,274 tags that could never pass.
    """
    if not expect:
        return False
    if expect in NO_SCRIPT_CLAIM or expect in UNENCODED or expect in UNSCANNABLE:
        return False
    t = _table()
    if expect in t["composites"] or expect in t["variants"]:
        return True
    if expect in ("Hans", "Hant"):
        return True
    return any(r[2] == expect for r in t["ranges"])


def _han_flavour(text: str) -> str | None:
    """`Hans` or `Hant` for Han text, or None when the sample cannot tell.

    The Unicode script property has one value for Han. Simplified and traditional
    are distinguished by *which* characters appear: a character with a
    traditional variant other than itself is a simplified form, and vice versa.
    Characters shared by both carry no signal, so a short sample of common
    characters legitimately returns None rather than guessing.
    """
    t = _table()
    simp = sum(1 for c in text if c in t["han_simplified_only"])
    trad = sum(1 for c in text if c in t["han_traditional_only"])
    if simp == trad:
        return None
    return "Hans" if simp > trad else "Hant"


def detect_script(text: str, expect: str | None = None) -> str | None:
    """Dominant script of `text` as an ISO 15924 code, ignoring digits and punctuation.

    `expect` does not change what is detected, only how it is *named*: several
    ISO codes describe the same encoded characters. Japanese is Han plus two
    kana; Korean is Hangul plus Han; Fraktur is Latin. Where the detected mix
    satisfies the expected composite, the composite is returned, because "this
    text is Jpan" and "this text is Hani plus Hira plus Kana" are the same
    statement and only one of them matches the catalogue.
    """
    counts: dict[str, int] = {}
    for ch in text:
        if not ch.isalpha():
            continue
        code = _script_of(ch)
        if code and code not in ("Zyyy", "Zinh"):
            counts[code] = counts.get(code, 0) + 1
    if not counts:
        return None

    present = set(counts)
    t = _table()
    dominant = max(counts, key=counts.get)

    # A composite is weighed as a whole: its parts are summed and compared
    # against the largest script that is not one of them. Real output carries
    # proper nouns, acronyms and units in Latin, and "JAS 39C Gripenは午前9時30分頃"
    # splits into nine Latin letters against nine Han and five kana -- enough for
    # Latin to win on any single-script comparison, and plainly Japanese.
    def _wins(parts: set[str]) -> bool:
        mine = sum(n for c, n in counts.items() if c in parts)
        theirs = max((n for c, n in counts.items() if c not in parts), default=0)
        return mine > 0 and mine >= theirs

    if expect in t["composites"] and _wins(set(t["composites"][expect])):
        return expect
    if expect in t["variants"] and _wins({t["variants"][expect]}):
        return expect

    if dominant == "Hani":
        # Han alone is ambiguous between the two Chinese codes; ask the
        # characters. An unsplittable sample keeps `Hani`, which the gate treats
        # as undetermined rather than as a mismatch.
        if expect in ("Hans", "Hant", None) or expect == "Hani":
            return _han_flavour(text) or "Hani"
    # An unrequested composite still reads more honestly than its largest part:
    # text mixing Han with both kana is Japanese, whoever asked.
    for code, parts in t["composites"].items():
        if len(present & set(parts)) > 1 and _wins(set(parts)):
            return code
    return dominant


@dataclass(frozen=True)
class LidResult:
    label: str | None          # GlotLID label, e.g. "chv_Cyrl"
    lang: str | None           # ISO 639-3
    script: str | None         # ISO 15924
    confidence: float
    backend: str               # "glotlid" | "script-only"
    alternatives: list[tuple[str, float]]


@lru_cache(maxsize=1)
def _model():
    import warnings
    import fasttext
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return fasttext.load_model(str(MODEL_PATH))


def available() -> bool:
    return MODEL_PATH.exists()


def identify(text: str, k: int = 5, expect_script: str | None = None) -> LidResult:
    script = detect_script(text, expect_script)
    if not available():
        return LidResult(None, None, script, 0.0, "script-only", [])

    # The python wrapper's predict() breaks under numpy 2; the underlying C++
    # object returns plain (prob, label) tuples and is stable.
    raw = _model().f.predict(" ".join(text.split()), k, 0.0, "strict")
    pairs = [(lbl.removeprefix("__label__"), float(p)) for p, lbl in raw]
    top, conf = pairs[0]
    lang, _, scr = top.partition("_")
    # The deterministic reading wins over GlotLID's label suffix, which is coarse:
    # its Chinese labels are all `_Hani`, so trusting the suffix made simplified
    # and traditional indistinguishable no matter how good the script table got.
    # Protocol 016's 15-of-15 result was measured on `detect_script` directly;
    # this makes the gate use the function that earned it. GlotLID's suffix stays
    # as the fallback for text whose characters name no script.
    return LidResult(top, lang or None, script or scr, conf, "glotlid", pairs[1:])
