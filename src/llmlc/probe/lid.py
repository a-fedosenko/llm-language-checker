"""Language identification.

LID is deliberately local and deliberately not an LLM: GlotLID covers 2,102
language-script labels, runs on CPU, costs nothing, and is more accurate at this
task than asking a model (docs/01). It is what makes most negatives free.

Falls back to a script-block check when the model file is absent, so the tool
still runs -- with reduced power, which the result records honestly.
"""
from __future__ import annotations

import pathlib
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

MODEL_PATH = pathlib.Path(__file__).resolve().parents[3] / "data" / "models" / "glotlid_v3.bin"
MODEL_URL = "https://huggingface.co/cis-lmu/glotlid/resolve/main/model_v3.bin"

# Unicode script detection via character-name prefixes: cheap, dependency-free,
# and enough to catch "answered in the wrong script entirely".
_SCRIPT_HINTS = {
    "LATIN": "Latn", "CYRILLIC": "Cyrl", "ARABIC": "Arab", "DEVANAGARI": "Deva",
    "GREEK": "Grek", "HEBREW": "Hebr", "ETHIOPIC": "Ethi", "ARMENIAN": "Armn",
    "GEORGIAN": "Geor", "THAI": "Thai", "BENGALI": "Beng", "TAMIL": "Taml",
    "TIBETAN": "Tibt", "MYANMAR": "Mymr", "KHMER": "Khmr", "SINHALA": "Sinh",
    "GURMUKHI": "Guru", "GUJARATI": "Gujr", "KANNADA": "Knda", "MALAYALAM": "Mlym",
    "TELUGU": "Telu", "ORIYA": "Orya", "HANGUL": "Kore", "HIRAGANA": "Jpan",
    "KATAKANA": "Jpan", "CJK": "Hani", "TIFINAGH": "Tfng", "VAI": "Vaii",
    "NKO": "Nkoo", "ADLAM": "Adlm",
}


def detect_script(text: str) -> str | None:
    """Dominant script of `text` as an ISO 15924 code, ignoring digits and punctuation."""
    counts: dict[str, int] = {}
    for ch in text:
        if not ch.isalpha():
            continue
        try:
            name = unicodedata.name(ch)
        except ValueError:
            continue
        for prefix, code in _SCRIPT_HINTS.items():
            if name.startswith(prefix):
                counts[code] = counts.get(code, 0) + 1
                break
    return max(counts, key=counts.get) if counts else None


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


def identify(text: str, k: int = 5) -> LidResult:
    script = detect_script(text)
    if not available():
        return LidResult(None, None, script, 0.0, "script-only", [])

    # The python wrapper's predict() breaks under numpy 2; the underlying C++
    # object returns plain (prob, label) tuples and is stable.
    raw = _model().f.predict(" ".join(text.split()), k, 0.0, "strict")
    pairs = [(lbl.removeprefix("__label__"), float(p)) for p, lbl in raw]
    top, conf = pairs[0]
    lang, _, scr = top.partition("_")
    return LidResult(top, lang or None, scr or script, conf, "glotlid", pairs[1:])
