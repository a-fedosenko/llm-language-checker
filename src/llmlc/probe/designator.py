"""Designator selection.

An LLM has no language-code interface -- whatever string we pass is just tokens
in a prompt, and nothing parses it. So the designator is not a fact to look up
but a prompt parameter to optimise, and a `None` verdict must always mean "none
under our best designator" (docs/01, docs/02).

S1 uses candidate A only. The sweep across candidates is S2, which is why the
candidates are enumerated here already.
"""
from __future__ import annotations

from dataclasses import dataclass

from llmlc.scheme import Language

SCRIPT_NAMES = {
    "Latn": "Latin", "Cyrl": "Cyrillic", "Arab": "Arabic", "Deva": "Devanagari",
    "Hans": "Simplified Chinese", "Hant": "Traditional Chinese", "Grek": "Greek",
    "Hebr": "Hebrew", "Ethi": "Ge'ez", "Armn": "Armenian", "Geor": "Georgian",
    "Thai": "Thai", "Beng": "Bengali", "Taml": "Tamil", "Tibt": "Tibetan",
    "Mymr": "Myanmar", "Khmr": "Khmer", "Sinh": "Sinhala", "Guru": "Gurmukhi",
    "Gujr": "Gujarati", "Knda": "Kannada", "Mlym": "Malayalam", "Telu": "Telugu",
    "Orya": "Odia", "Jpan": "Japanese", "Kore": "Korean", "Tfng": "Tifinagh",
    "Vaii": "Vai", "Nkoo": "N'Ko", "Adlm": "Adlam",
}


@dataclass(frozen=True)
class Designator:
    kind: str                      # A..E, per docs/01
    value: str
    also: tuple[str, ...] = ()     # other candidate kinds that produced the same string

    @property
    def kinds(self) -> tuple[str, ...]:
        return (self.kind, *self.also)

    def is_(self, kind: str) -> bool:
        """True if this string was proposed by candidate `kind`.

        Needed because candidates collide -- an incumbent designator is often
        identical to the ISO-639-3 form -- and S2 must still be able to say
        whether selection beat the incumbent.
        """
        return kind in self.kinds


def candidates(lang: Language, *, incumbent: str | None = None,
               region_name: str | None = None) -> list[Designator]:
    """Candidate designators, best-guess first."""
    out: list[Designator] = []
    name = lang.name or lang.tag

    # A -- English name, qualified by script and region only where they disambiguate.
    qualifiers = []
    if region_name:
        qualifiers.append(region_name)
    if lang.script and lang.script not in ("Latn",):
        qualifiers.append(f"{SCRIPT_NAMES.get(lang.script, lang.script)} script")
    a = f"{name} ({', '.join(qualifiers)})" if qualifiers else name
    out.append(Designator("A", a))

    if lang.local_name and lang.local_name != name:
        out.append(Designator("B", lang.local_name))
    out.append(Designator("C", lang.tag))
    if lang.iso639_3:
        script = SCRIPT_NAMES.get(lang.script or "", lang.script or "")
        out.append(Designator("D", f"{lang.iso639_3} ({script})" if script else lang.iso639_3))
    if incumbent:
        out.append(Designator("E", incumbent))

    # Collapse duplicate strings but keep every candidate kind that proposed
    # them, so a collision never hides the fact that a candidate was tested.
    unique: list[Designator] = []
    index: dict[str, int] = {}
    for d in out:
        if not d.value:
            continue
        if d.value in index:
            prev = unique[index[d.value]]
            unique[index[d.value]] = Designator(prev.kind, prev.value, (*prev.also, d.kind))
        else:
            index[d.value] = len(unique)
            unique.append(d)
    return unique


def best(lang: Language, **kw) -> Designator:
    """S1: candidate A. S2 replaces this with a measured sweep."""
    return candidates(lang, **kw)[0]


GENERATE_PROMPT = """Write {n} sentences in {designator} describing this situation:

{scenario}

Write naturally in {designator} — do not translate word for word, and do not \
explain or comment. Output only the {designator} text.
If you cannot write {designator}, reply with exactly CANNOT and nothing else."""


def generation_prompt(designator: str, scenario: str, n: int = 3) -> str:
    return GENERATE_PROMPT.format(designator=designator, scenario=scenario, n=n)
