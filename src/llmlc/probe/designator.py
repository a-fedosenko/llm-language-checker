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
               region_name: str | None = None,
               qualify_script: bool | None = None) -> list[Designator]:
    """Candidate designators, best-guess first.

    `qualify_script` forces the script into the name. Without it the rule was
    "name the script unless it is Latin", which is right for most languages and
    exactly wrong for the ones that matter here: Kazakh's *marked* script is
    Latin, so `kk-Latn` was asked for as plain "Kazakh" and answered, correctly,
    in Cyrillic. We then recorded that as the model failing to produce Latin
    Kazakh, when it was the right answer to the question we actually asked
    (docs/02: a negative must mean "none under our best designator").
    """
    out: list[Designator] = []
    name = lang.name or lang.tag

    # A -- English name, qualified by script and region.
    #
    # The region is named from method 3.0.0. Protocol 010 rejected it at 1.x and
    # was right about what it tested: a bare `name (Country)` designator pulls a
    # model toward that country's dominant language, and it turned Swiss German
    # into Standard German. What is being tested now is different -- the region
    # is named *and* the model is told what to do with it, in a system message
    # that casts it as a speaker of that variety. Protocol 020 measures whether
    # that difference holds. 010 described itself as a screening test, not a
    # measurement, and named this as the experiment that would settle it.
    qualifiers = []
    if region_name:
        qualifiers.append(region_name)
    name_script = qualify_script or (qualify_script is None
                                     and lang.script and lang.script not in ("Latn",))
    if name_script and lang.script:
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


#: The task, as a system message. Split from the material on purpose: a single
#: blob invites a model to *continue* the text rather than carry out the
#: instruction, and the half that never changes is the half a provider can
#: cache. Introduced at method 3.0.0 -- see protocol 020, which measures whether
#: the split and the role framing change the verdict rather than assuming it.
SYSTEM_PROMPT = """You are a native speaker of {designator}.

Your task: write {n} sentences describing the situation the user gives you, \
using the grammar, spelling and vocabulary a native speaker of this specific \
variety would use.
{script_rule}
Write naturally — do not translate word for word, and do not explain or \
comment. Output only the {designator} text and nothing else.
If you cannot write {designator}, reply with exactly CANNOT and nothing else."""

#: Said on its own line, and only where the script is known.
#:
#: The designator already names the script, and that is not always enough. A
#: model asked for "Serbian (Montenegro, Cyrillic script)" returned fluent,
#: correctly ijekavian Montenegrin -- in Latin. Montenegro uses both alphabets
#: and Latin is the commoner in practice, so naming the region pulls toward the
#: region's script the way protocol 010 found it pulls toward the region's
#: dominant language. Observed once in sixteen generations: rare, and fatal
#: when it happens, because the gate convicts the whole item on script before
#: anything else about it is looked at.
SCRIPT_RULE = ("\nWrite every word in the {script_name} alphabet. Do not use "
               "any other alphabet, not even for names or single words.\n")

#: The material. Everything that varies between items lives here, so the system
#: half stays identical across a language's whole run.
USER_PROMPT = """{scenario}"""


def generation_prompt(designator: str, scenario: str, n: int = 3,
                      script_name: str | None = None) -> tuple[str, str]:
    """The (system, user) pair for one item.

    Returns both halves rather than one string because the caller has to send
    them as separate messages; joining them back together is only done for the
    gate's copy check, which needs to know everything the model was shown.

    `script_name` adds an explicit alphabet rule. Omitted where the script is
    unknown, because an instruction naming no alphabet is worse than none.
    """
    rule = SCRIPT_RULE.format(script_name=script_name) if script_name else ""
    return (SYSTEM_PROMPT.format(designator=designator, n=n, script_rule=rule),
            USER_PROMPT.format(scenario=scenario))


def script_name_for(script: str | None) -> str | None:
    """The alphabet's English name, or None where we have no name for it.

    Falls back to nothing rather than to the ISO 15924 code: "write every word
    in the Tfng alphabet" instructs a model in a code it has no reason to read
    as a writing system, which is the same mistake as putting `ME` in a prompt.
    """
    return SCRIPT_NAMES.get(script or "") if script else None
