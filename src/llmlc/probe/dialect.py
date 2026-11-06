"""The five dialect probes.

Each asks a different question, and they come apart in practice — which is why
they are five probes and not one score. A model can identify Montenegrin
Serbian on sight and still write generic Serbian when asked for it; another can
write it unprompted and fail to convert a text into it on demand. Collapsing
those into "supports the dialect: yes/no" is what makes a dialect claim
unconvincing, and keeping them separate is what lets a verdict explain itself.

    P1  blind identification   does an attestor name the variety, unlabelled?
    P2  contrast pair          can an attestor tell two varieties apart?
    P3  conversion             does the model change anything when told to?
    P4  self-consistency       does it change the *same* things every time?
    P5  marker grounding       were the cited markers real?

**P3 and P4 need no attestor at all.** That is where cheap breadth lives: they
are the dialect equivalent of the deterministic negative, sound at full breadth
with no panel call and no control text. P1 and P2 are the paid half, and are
only worth spending where the free half found something.

P5 is not a separate call. Grounding happens inside `attest.identify` and
`attest.separate`; this module only aggregates what they found, because a
fabricated marker is evidence about the *attestor* and belongs in the same
place as its verdict.

What is deliberately absent: routing, panels, capability records and the
verdict ladder. A probe reports what happened; deciding what it means about a
model is a later and separate job, and mixing them is how an aggregate comes to
hide the disagreement it was built from.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from llmlc.client import OpenAICompatClient
from llmlc.probe import attest
from llmlc.probe import designator as dsg
from llmlc.probe.attest import Blind, Identification, Separation
from llmlc.probe.corpus import Corpus, Record
from llmlc.probe.gate import GateResult
from llmlc.probe.gate import check as gate_check
from llmlc.scheme import Language, Scheme

#: Above this share of tokens, a "conversion" has stopped converting and started
#: paraphrasing — or translating, which looks the same from here.
#:
#: There is deliberately **no floor**. A dialect conversion is supposed to be a
#: small edit: ekavian to ijekavian moves a handful of morphemes and leaves the
#: sentence standing, so any floor expressed as a share of the text convicts
#: exactly the models that did the job correctly — a single correct substitution
#: in a long paragraph is a conversion, and scoring it as "changed nothing"
#: would be the wrong answer for the right behaviour. Punctuation and case are
#: already discarded by tokenisation, so any surviving edit is a real word
#: substitution and one is enough.
#:
#: The ceiling is the live risk instead, and it is the one a floor would have
#: missed entirely: a model that rewrites the whole text has produced something
#: that is no longer the same passage, and its diff is unreadable as evidence.
#: P3 separates "touched nothing" from "touched something" from "touched
#: everything"; whether what it touched was the *right* thing is P1 and P2's
#: question.
PARAPHRASED_AT = 0.5

#: Repeats for the self-consistency probe. Two is the minimum that can disagree
#: and the most that is worth paying for at this stage: the question is whether
#: the transformation is systematic or improvised, and an improviser disagrees
#: with itself on the first retry.
CONSISTENCY_RUNS = 2


# -- what an attestor is told, built from the scheme --------------------------

def blind_for(scheme: Scheme, family: list[Language], *, salt: str) -> Blind:
    """The option list for a family, shuffled, naming no expected answer.

    Options are **region names**, not tags: `sr-me-cyrl` would hand the answer
    to anything that can read a tag, and "Montenegro" is also the form the
    designator uses, so attestor and producer are speaking about the same thing.

    The unqualified tag contributes no option. It is the neutral arm — the
    thing a variety is contrasted *against* — and offering it as an answer would
    be offering "none of these" twice, since `generic` already means that.

    **`family` is a list the caller chooses, not everything in the scheme.**
    Spanish carries 22 regional tags and English 11, and a 22-way blind choice
    is a different and much harder task than the one being measured — chance
    falls to 4.5%, and an attestor that knows Mexican from Peninsular Spanish
    perfectly well can still miss by picking Uruguay. Pass the varieties
    actually under test; `family_of` is the convenience that returns all of
    them, not an instruction to use all of them.
    """
    language = next((l.name for l in family if l.name), None) or "this language"
    options = []
    for lang in family:
        if lang.inclusive or not lang.region_name:
            continue
        if lang.region_name not in options:
            options.append(lang.region_name)
    script = next((dsg.script_name_for(l.script) for l in family if l.script), None)
    return Blind(language=language, options=attest.shuffled(options, salt=salt),
                 script_name=script)


def family_of(scheme: Scheme, lang: Language) -> list[Language]:
    """Every tag sharing this one's language, umbrella included.

    Grouped by `lang` rather than by equivalence class, because the class is
    `iso639_3|script` and a family's whole point is that it spans regions. For
    Serbian it also spans scripts, and `sr-me-cyrl` and `sr-me-latn` are the
    same variety written twice — which is why options are de-duplicated by
    region name above.
    """
    return [l for l in scheme.languages.values() if l.lang == lang.lang]


# -- P3 and P4: the free half -------------------------------------------------

CONVERT_SYSTEM = """You are a native speaker of {designator}.

Your task: rewrite the text the user gives you so that it reads as a native \
speaker of this specific variety would write it, changing the grammar, spelling \
and vocabulary wherever that variety differs.
{script_rule}
Change only what this variety requires. Do not translate, do not paraphrase, do \
not add or remove information, and do not explain or comment. If nothing needs \
to change, return the text unchanged.
Output only the rewritten text and nothing else."""


@dataclass
class Conversion:
    """One rewrite of a text into a variety, and what it actually changed."""

    designator: str
    before: str
    after: str | None = None
    gate: GateResult | None = None
    error: str | None = None
    #: Token-level edits, as (from, to) pairs. The evidence a reader audits:
    #: this is where a model says, in its own output, what it thinks the
    #: variety *is*.
    edits: list[tuple[str, str]] = field(default_factory=list)
    rate: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.after)

    @property
    def converted(self) -> bool:
        """Did it make a dialect-sized edit? A direct negative when false,
        settled locally with no judge call."""
        return self.ok and bool(self.edits) and not self.paraphrased

    @property
    def paraphrased(self) -> bool:
        """Rewrote so much that this is no longer the same passage.

        Not a conversion, and not scoreable as one: the diff stops being
        readable evidence, and the edits it lists are sentence rewrites rather
        than the variety's own alternations. Kept distinct from "changed
        nothing" because they are opposite failures and a reader needs to know
        which happened.
        """
        return self.ok and self.rate > PARAPHRASED_AT

    @property
    def signature(self) -> frozenset[tuple[str, str]]:
        """The set of substitutions, order and frequency discarded.

        What self-consistency compares. Two runs that rewrite the same words the
        same way have the same signature even if they reach them in a different
        order or repeat one of them.
        """
        return frozenset(self.edits)

    def as_dict(self) -> dict:
        return {"designator": self.designator, "rate": round(self.rate, 3),
                "converted": self.converted, "paraphrased": self.paraphrased,
                "edits": [list(e) for e in self.edits],
                "gate": self.gate.verdict.value if self.gate else None,
                "error": self.error}


def _tokens(text: str) -> list[str]:
    """Words, lowercased, punctuation dropped.

    Punctuation is dropped so that re-wrapping or a changed comma does not read
    as a dialect edit; case is folded so that a sentence-initial substitution
    counts the same as a medial one.
    """
    return re.findall(r"\w+", text.casefold(), re.UNICODE)


def diff(before: str, after: str) -> tuple[list[tuple[str, str]], float]:
    """Token-level edits and the share of the original they touch.

    `difflib` rather than chrF++ on purpose. chrF++ gives a similarity number
    and nothing a person can read; what a reviewer needs here is *which words
    changed*, because that is how they tell a real dialect conversion from a
    paraphrase. Protocol 020 proposed chrF++ for this and its own text concedes
    the metric does not distinguish the two.
    """
    a, b = _tokens(before), _tokens(after)
    if not a:
        return [], 0.0
    edits: list[tuple[str, str]] = []
    touched = 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if op == "equal":
            continue
        touched += max(i2 - i1, j2 - j1)
        edits.append((" ".join(a[i1:i2]), " ".join(b[j1:j2])))
    return edits, touched / len(a)


def convert(*, client: OpenAICompatClient, engine: str, lang: Language, text: str,
            designator: str, corpus: Corpus, relatives: set[str], accept: set[str],
            abstain: set[str] | None = None, max_tokens: int = 600) -> Conversion:
    """P3. Rewrite macrolanguage text into one variety; measure what moved.

    One producer call, no attestor, no control text. The diff is both the
    measurement and the artifact a human reads, which is what makes this the
    most defensible probe in the battery: a reviewer who distrusts the number
    can look at the substitutions and disagree with them concretely.
    """
    out = Conversion(designator=designator, before=text)
    system = CONVERT_SYSTEM.format(
        designator=designator,
        script_rule=(dsg.SCRIPT_RULE.format(script_name=s)
                     if (s := dsg.script_name_for(lang.script)) else ""))

    gen = client.complete(engine, text, max_tokens=max_tokens, system=system)
    shown = f"{system}\n\n--- user ---\n\n{text}"
    corpus.write(Record("conversion", engine, lang.tag, None, designator, shown,
                        gen.text, gen.error, gen.usage, gen.latency_s))
    if not gen.ok:
        out.error = gen.error or "no output"
        return out

    # Gated like any other generation. A "conversion" that answered in the wrong
    # language is not a small diff, it is a different failure, and the diff
    # would report it as an enormous and meaningless one.
    out.gate = gate_check(gen.text, prompt=shown, expect_lang=lang.iso639_3,
                          expect_script=lang.script, relatives=relatives,
                          accept_lang=accept, abstain_lang=abstain)
    if not out.gate.passed:
        out.error = out.gate.detail or out.gate.verdict.value
        return out

    out.after = gen.text
    out.edits, out.rate = diff(text, gen.text or "")
    return out


@dataclass
class Consistency:
    """P4. Whether repeated conversions agree about what the variety requires."""

    runs: list[Conversion] = field(default_factory=list)
    agreement: float | None = None

    @property
    def ok(self) -> bool:
        return self.agreement is not None

    @property
    def systematic(self) -> bool:
        """Repeatable transformation rather than improvisation.

        The claim this probe can make without any judge: a model cannot
        simulate consistency it does not have. Bluffing produces different
        substitutions each time; genuine command produces the same ones.
        """
        return bool(self.agreement and self.agreement >= 0.5)

    def as_dict(self) -> dict:
        return {"agreement": None if self.agreement is None else round(self.agreement, 3),
                "systematic": self.systematic,
                "runs": [r.as_dict() for r in self.runs]}


def consistency(conversions: list[Conversion]) -> Consistency:
    """Jaccard agreement between the edit signatures of repeated conversions.

    Jaccard rather than a count, so a run that makes every edit the other made
    *plus five more* is not scored as agreement. Both directions matter: adding
    edits is as much a sign of improvisation as omitting them.

    Converted-nothing runs are excluded before scoring. Two empty signatures
    agree perfectly and mean nothing — a model that changed nothing twice is
    consistent in a way that says nothing about dialect command, and scoring it
    1.0 would make the most ignorant possible answer the highest-scoring one.
    That is P3's question, and `systematic` must not be able to answer it.
    """
    out = Consistency(runs=conversions)
    usable = [c for c in conversions if c.converted]
    if len(usable) < 2:
        return out

    scores = []
    for i in range(len(usable)):
        for j in range(i + 1, len(usable)):
            a, b = usable[i].signature, usable[j].signature
            union = a | b
            scores.append(len(a & b) / len(union) if union else 0.0)
    out.agreement = sum(scores) / len(scores)
    return out


# -- P1 and P2: the paid half -------------------------------------------------

@dataclass
class BlindRead:
    """P1. One text, read by one attestor, with the answer the caller expected.

    `expected` lives on the *result*, never on the call. It is how the caller
    scores the answer; the attestor was never shown it. Keeping it here rather
    than passing it down is what makes the blinding checkable by reading one
    function signature.
    """

    attestor: str
    expected: str
    identification: Identification

    @property
    def correct(self) -> bool:
        return (self.identification.decided
                and self.identification.answer == self.expected)

    @property
    def wrong(self) -> bool:
        """Named a different variety. Informative, and not the same as declining."""
        return (self.identification.decided
                and self.identification.answer != self.expected)

    def as_dict(self) -> dict:
        return {"attestor": self.attestor, "expected": self.expected,
                "correct": self.correct, **self.identification.as_dict()}


def blind_read(client: OpenAICompatClient, attestor: str, *, text: str, blind: Blind,
               expected: str, tag: str, corpus: Corpus) -> BlindRead:
    """P1. Ask one attestor, blind, what variety a text is.

    `expected` is consumed here and goes nowhere near `attest.identify`, which
    has no parameter for it. Scoring happens after the answer comes back.
    """
    ident = attest.identify(client, attestor, text=text, blind=blind)
    corpus.write(Record("attestation", attestor, tag, None, None,
                        f"[blind identification: {', '.join(blind.options)}]",
                        ident.raw, ident.error,
                        meta={"answer": ident.answer, "expected": expected,
                              "fabricated": ident.fabricated}))
    return BlindRead(attestor, expected, ident)


@dataclass
class ContrastRead:
    """P2. One attestor's reading of a pair, scored against the true assignment."""

    attestor: str
    expected_first: str
    expected_second: str
    separation: Separation

    @property
    def correct(self) -> bool:
        """Both labels right, accounting for the order the attestor saw.

        `swapped` is the only reason this is not a plain comparison: the pair is
        presented in an order salted by the texts, so that an attestor answering
        the options in the order they were listed cannot score 100% by habit.
        """
        s = self.separation
        if not s.split:
            return False
        first, second = (s.b, s.a) if s.swapped else (s.a, s.b)
        return first == self.expected_first and second == self.expected_second

    @property
    def merged(self) -> bool:
        """Said the two are the same variety. The negative, and a real answer —
        the one the Russian null control must be able to produce."""
        return self.separation.merged

    def as_dict(self) -> dict:
        return {"attestor": self.attestor, "correct": self.correct,
                "expected": [self.expected_first, self.expected_second],
                **self.separation.as_dict()}


def contrast_read(client: OpenAICompatClient, attestor: str, *, first: str, second: str,
                  blind: Blind, expected_first: str, expected_second: str,
                  tag: str, corpus: Corpus) -> ContrastRead:
    """P2. Ask one attestor, blind, to tell two varieties apart."""
    sep = attest.separate(client, attestor, first=first, second=second, blind=blind)
    corpus.write(Record("contrast", attestor, tag, None, None,
                        f"[blind pair: {', '.join(blind.options)}]",
                        sep.raw, sep.error,
                        meta={"a": sep.a, "b": sep.b, "swapped": sep.swapped,
                              "expected": [expected_first, expected_second],
                              "fabricated": sep.fabricated}))
    return ContrastRead(attestor, expected_first, expected_second, sep)


# -- P5: aggregating what grounding found -------------------------------------

@dataclass
class Grounding:
    """P5. How much of an attestor's cited evidence was real.

    Not a call of its own: `attest.identify` and `attest.separate` ground their
    own results, and this counts what they found. A fabricated marker is
    evidence about the *attestor*, so it belongs beside that attestor's verdict
    rather than in a probe of its own.
    """

    cited: int = 0
    fabricated: int = 0

    @property
    def rate(self) -> float | None:
        """Share of cited markers actually present. None when none were cited —
        which is not the same as zero, and must not be read as a failure."""
        return None if not self.cited else 1.0 - (self.fabricated / self.cited)

    @property
    def unreliable(self) -> bool:
        """Cited evidence that is not there at all.

        A single invented quotation is enough: a model that fabricates one
        marker to support a verdict has told us the verdict was not read off the
        text, which is the whole claim it was making.
        """
        return self.fabricated > 0

    def as_dict(self) -> dict:
        return {"cited": self.cited, "fabricated": self.fabricated,
                "rate": None if self.rate is None else round(self.rate, 3),
                "unreliable": self.unreliable}


def grounding(results) -> Grounding:
    """Tally markers and fabrications over any mix of reads."""
    out = Grounding()
    for r in results:
        inner = getattr(r, "identification", None) or getattr(r, "separation", None)
        if inner is None:
            continue
        out.cited += len(inner.markers)
        out.fabricated += len(inner.fabricated)
    return out
