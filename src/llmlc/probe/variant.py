"""Variant probes: does the model actually mark the dialect it was asked for?

Three separate questions, three separate answers (docs/01):

  Does the model support the macrolanguage?   -> probe the base tag, get a tier
  What does the base tag resolve to?          -> `resolves_to`, observed
  Can it produce `en-AU` when asked?          -> **this module**, its own probe

The third is not answerable from the first. "Emitted Cyrillic when asked for
`kk`" is not "produces Cyrillic when asked for `kk-Cyrl`", and a model that
writes excellent English tells you nothing about whether it writes Australian
English when you ask for it.

Two scoring mechanisms, chosen by what the family actually divides on:

**Script** -- where the language splits by script, GlotLID already returns the
script, so the existing probe *is* the discriminating test and no marker list is
needed. 766 languages in the shipped catalogue split this way.

**Markers** -- where the variants differ by country only, a closed shibboleth set
is compared against the sibling's (`markers.py`). 534 variant tags need this or
an explicit `not-distinguishable` decision.

Anything else is `untested`: the tier is inherited as a *placeholder*, and that
is a tracked gap rather than a claim.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from llmlc.client import OpenAICompatClient
from llmlc.probe import designator as dsg
from llmlc.probe.corpus import Corpus, Record
from llmlc.probe.gate import GateVerdict, check as gate_check
from llmlc.probe.markers import MarkerSet, VariantOutcome, score_text
from llmlc.scheme import Language, Scheme


class VariantEvidence(str, Enum):
    """Four states, not two.

    Separating `NOT_DISTINGUISHABLE` from `UNTESTED` is what makes the remaining
    work countable: a finished decision must be distinguishable from an unfilled
    gap, or nobody can tell how much is left.
    """

    PROVEN = "proven"
    PROVEN_FAILED = "proven-failed"
    NOT_DISTINGUISHABLE = "not-distinguishable"
    UNTESTED = "untested"


#: Share of *decided* marker choices that must go the variant's way to call it
#: proven. Scoring is comparative, so 0.5 is the coin flip and this is a clear
#: lean rather than a bare majority. A model that genuinely marks the variant
#: scores near 1.0, so the exact cut matters less than having one written down.
PROVEN_AT = 0.6

#: Items to run for a marker probe. Elicitation contexts are the scarce resource,
#: not the calls: three well-aimed contexts beat ten vague ones.
VARIANT_ITEMS = 3


@dataclass
class VariantItem:
    context: str
    generation: str | None
    outcome: VariantOutcome
    gate_verdict: str | None = None
    error: str | None = None


@dataclass
class VariantResult:
    tag: str
    evidence: VariantEvidence
    mechanism: str                       # markers | script | declared | none
    s_variant: float | None = None
    designator: str | None = None
    sibling: str | None = None
    items: list[VariantItem] = field(default_factory=list)
    voids: int = 0
    note: str | None = None
    calls: int = 0

    def as_dict(self) -> dict:
        return {
            "evidence": self.evidence.value,
            "mechanism": self.mechanism,
            "s_variant": None if self.s_variant is None else round(self.s_variant, 3),
            "designator": self.designator,
            "sibling": self.sibling,
            "voids": self.voids,
            "note": self.note,
            "items": [{"context": i.context[:80], "gate": i.gate_verdict,
                       **i.outcome.as_dict()} for i in self.items],
        }


def splits_by_script(scheme: Scheme, lang: Language) -> bool:
    """Does this language appear under more than one script in the catalogue?"""
    return len(_scripts(scheme, lang)) > 1


def _scripts(scheme: Scheme, lang: Language) -> dict[str, str]:
    """Script -> shortest tag carrying it, for one ISO 639-3 code."""
    out: dict[str, str] = {}
    if not lang.iso639_3:
        return out
    for other in scheme.languages.values():
        if other.iso639_3 != lang.iso639_3 or not other.script:
            continue
        held = out.get(other.script)
        if held is None or (len(other.tag), other.tag) < (len(held), held):
            out[other.script] = other.tag
    return out


def default_script(scheme: Scheme, lang: Language) -> str | None:
    """The script the *base* form of this language carries.

    Taken from the shortest tag rather than from a table: `kk` is Cyrillic and
    `de` is Latin because that is what the catalogue's base tag says, which is
    CLDR's likely-subtag answer and therefore also what an unqualified request
    gets.
    """
    scripts = _scripts(scheme, lang)
    base = min(scripts.values(), key=lambda t: (len(t), t), default=None)
    if base is None:
        return None
    return next((s for s, tag in scripts.items() if tag == base), None)


def is_script_variant(scheme: Scheme, lang: Language) -> bool:
    """Is this tag a *marked* script variant, as opposed to the base form?

    `kk-Latn` is: Kazakh's base form is Cyrillic, so asking for Latin and
    receiving Latin is a real variant result. `kk` is not -- it is the base, and
    "produced Cyrillic when asked for Kazakh" is a fact about the language rather
    than about a variant of it.

    The distinction matters because the catalogue carries fringe scripts for
    major languages: German appears with Fraktur, Braille, Duployan and Runic, so
    "this language has more than one script" is true of `de` and tells you
    nothing about the tag `de`.
    """
    if not lang.script or not splits_by_script(scheme, lang):
        return False
    return lang.script != default_script(scheme, lang)


def from_script(result) -> VariantResult:
    """Read variant evidence off a probe that has already run.

    Costs nothing: the gate checked the script on every item, so the answer is
    already in the result. `WRONG_SCRIPT` is the failure -- the model was asked
    for one script and produced another, which is precisely the variant not being
    marked.
    """
    items = [i for i in result.items if i.gate.verdict is not GateVerdict.TOO_SHORT]
    wrong = sum(1 for i in items if i.gate.verdict is GateVerdict.WRONG_SCRIPT)
    passed = sum(1 for i in items if i.gate.passed)
    decided = wrong + passed
    if not decided:
        # Distinguish "never answered" from "answered in the right script but the
        # wrong language". The second is a base-language failure: gpt-4o asked for
        # Latin-script Kazakh returned Latin text that GlotLID read as Crimean
        # Tatar and Turkmen. The script was not the problem, so the script
        # mechanism has nothing to say and must not claim the variant failed.
        off_language = sum(1 for i in items
                           if i.gate.verdict in (GateVerdict.WRONG_LANGUAGE,
                                                 GateVerdict.RELATIVE_SUBSTITUTION))
        note = ("The requested script was produced but the language was not, so this is a "
                f"base-language failure rather than a variant one ({off_language} of "
                f"{len(items)} items)." if off_language else
                "No item reached the script check.")
        return VariantResult(result.tag, VariantEvidence.UNTESTED, "script", note=note)
    rate = passed / decided
    return VariantResult(
        result.tag,
        VariantEvidence.PROVEN if rate >= PROVEN_AT else VariantEvidence.PROVEN_FAILED,
        "script", s_variant=rate, designator=result.designator,
        note=f"{passed} of {decided} items came back in the requested script.")


def from_markers(
    *, client: OpenAICompatClient, engine: str, lang: Language, markers: MarkerSet,
    corpus: Corpus, scheme: Scheme, n_items: int = VARIANT_ITEMS,
) -> VariantResult:
    """Run the variant's own probe and score it against its marker set.

    The designator is authored in the marker file rather than derived: protocol
    010 found automatically country-qualified designators unreliable, and putting
    the string next to the markers means a reviewer sees both at once.
    """
    designator = markers.designator or lang.tag
    out = VariantResult(lang.tag, VariantEvidence.UNTESTED, "markers",
                        designator=designator, sibling=markers.sibling)

    for context in markers.elicitation[:n_items]:
        prompt = dsg.generation_prompt(designator, context, 3)
        gen = client.complete(engine, prompt, max_tokens=400)
        out.calls += 1
        corpus.write(Record("variant", engine, lang.tag, "variant", designator, prompt,
                            gen.text, gen.error, gen.usage, gen.latency_s))
        gate = gate_check(gen.text, prompt=prompt, expect_lang=lang.iso639_3,
                          expect_script=lang.script)
        if not gate.passed:
            # Wrong language entirely is a base-language failure, not a variant
            # one. Scoring its markers would be scoring noise.
            out.items.append(VariantItem(context, gen.text, VariantOutcome(error=gate.detail),
                                         gate_verdict=gate.verdict.value, error=gate.detail))
            continue
        scored = score_text(gen.text, markers)
        out.items.append(VariantItem(context, gen.text, scored,
                                     gate_verdict=gate.verdict.value))

    rates = [i.outcome.rate for i in out.items if i.outcome.rate is not None]
    out.voids = sum(1 for i in out.items if i.outcome.void and not i.error)

    if not rates:
        # Every item was void or gated out. We learned nothing about the model,
        # so this is not a failure -- it is an untested tag with a reason, and
        # the reason points at our contexts rather than at the model.
        out.evidence = VariantEvidence.UNTESTED
        out.note = (f"No item forced a marker choice ({out.voids} void of {len(out.items)}); "
                    f"the elicitation contexts failed, not the model.")
        return out

    out.s_variant = sum(rates) / len(rates)
    out.evidence = (VariantEvidence.PROVEN if out.s_variant >= PROVEN_AT
                    else VariantEvidence.PROVEN_FAILED)
    out.note = (f"{len(rates)} scoreable item(s), {out.voids} void. "
                f"Variant markers won {out.s_variant:.0%} of decided choices "
                f"against {markers.sibling or 'the sibling variant'}.")
    return out


def declared(tag: str, markers: MarkerSet) -> VariantResult:
    """A variant explicitly recorded as not differing in everyday register.

    Inheriting the base tier here is *correct*, not a fallback, which is why this
    is a separate state from `untested` and why the note is mandatory.
    """
    return VariantResult(tag, VariantEvidence.NOT_DISTINGUISHABLE, "declared",
                         sibling=markers.sibling, note=markers.note)


def untested(tag: str, reason: str) -> VariantResult:
    return VariantResult(tag, VariantEvidence.UNTESTED, "none", note=reason)
