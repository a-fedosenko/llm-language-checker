"""Deriving a control for a digraphic language's other alphabet.

Qualification needs parallel text in the target language whose English meaning
is already known, and FLORES ships Serbian in Cyrillic only. `sr-Latn` therefore
has no control, no reader can be certified for it, and every result comes back
`unverified` -- not a statement about the model, which wrote perfectly good
Latin Serbian and cleared the gate, but about the instrument.

The general rule that produces this is right and stays: a control may not stand
in for a different writing system (`bt/qualify.py`). Qualifying a reader on
Cyrillic Uzbek says nothing about Latin Uzbek, because reading them is a
different job.

**A digraphic language is the exception, and it is exceptional for a checkable
reason.** Serbian is written in two alphabets with a deterministic, complete
character mapping maintained as part of the orthography; transliterating the
Cyrillic control is not translation, interpretation or generation, and it adds
no information. The English meaning on the other side is untouched, so the
derived control is as good as the one it came from.

The honest limits, which is why this file covers one language:

- **Forward only.** Cyrillic -> Latin is a function; the reverse is not, because
  the Latin digraphs `lj`, `nj` and `dž` are ambiguous across a morpheme
  boundary (*nadživeti* is `nad` + `živeti`, not `na` + `dživeti`). Nothing here
  goes backwards.
- **Complete or nothing.** A text containing a Cyrillic character the table does
  not cover is refused rather than passed through half-converted, because a
  control with a stray Cyrillic letter would qualify a reader on text no one
  writes.
- **Not a general mechanism.** Kazakh, Uzbek and Azerbaijani are also digraphic,
  and their mappings are contested, reformed, or both. Adding one is a decision
  about that language, made with someone who reads it -- not a loop over this
  table.
"""
from __future__ import annotations

#: Serbian Cyrillic to Latin (Gaj's alphabet), the mapping the orthography
#: defines. Order matters nowhere here: every key is a single character.
SR_CYRL_TO_LATN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ђ": "đ", "е": "e",
    "ж": "ž", "з": "z", "и": "i", "ј": "j", "к": "k", "л": "l", "љ": "lj",
    "м": "m", "н": "n", "њ": "nj", "о": "o", "п": "p", "р": "r", "с": "s",
    "т": "t", "ћ": "ć", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "č",
    "џ": "dž", "ш": "š",
}

#: Languages whose Latin spelling can be derived, and from what. One entry, and
#: adding a second is a linguistic decision rather than a configuration change.
DERIVABLE = {"sr-Latn": ("sr", SR_CYRL_TO_LATN)}


class Untransliterable(ValueError):
    """The text holds a character the table does not cover."""


def _cased(ch: str, table: dict[str, str]) -> str | None:
    lower = table.get(ch.lower())
    if lower is None:
        return None
    if ch.islower():
        return lower
    # Џ -> Dž at the start of a word, DŽ inside an all-caps run. Title case is
    # the safe choice for a sentence-cased corpus and is what the orthography
    # uses for a capitalised word.
    return lower[0].upper() + lower[1:]


def to_latin(text: str, table: dict[str, str] = SR_CYRL_TO_LATN) -> str:
    """Transliterate, or refuse.

    Refusing on an unmapped Cyrillic character is the guard: a control that
    silently kept a stray Cyrillic letter would certify a reader against text
    nobody writes, and nothing downstream would show it.
    """
    out, unmapped = [], set()
    for ch in text:
        converted = _cased(ch, table)
        if converted is not None:
            out.append(converted)
        elif "Ѐ" <= ch <= "ӿ":
            unmapped.add(ch)
        else:
            out.append(ch)          # digits, punctuation, Latin already present
    if unmapped:
        raise Untransliterable(
            f"no mapping for {sorted(unmapped)}; refusing to emit a control "
            f"with Cyrillic left in it")
    return "".join(out)


def derive_controls(controls: dict[str, dict]) -> dict[str, dict]:
    """Add derived entries for digraphic languages whose other script is absent.

    Never overwrites. A real control, hand-written or shipped, always beats one
    derived from the other alphabet -- and a derived entry says so in
    `derived_from`, so a result graded through it can be told apart from one
    graded through FLORES.
    """
    for tag, (source, table) in DERIVABLE.items():
        if tag in controls or source not in controls:
            continue
        entry = controls[source]
        try:
            items = [{**item, "text": to_latin(item["text"], table)}
                     for item in entry.get("items", []) if item.get("text")]
        except Untransliterable:
            continue
        if items:
            controls[tag] = {**entry, "items": items,
                             "derived_from": source, "transliterated": True}
    return controls
