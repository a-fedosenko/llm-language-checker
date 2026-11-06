"""Attestation: asking a model what variety a text is, without telling it.

The instrument this replaces was sound and unscalable. A closed marker set
discriminates cleanly -- protocol 012 measured 1.00 against 0.00 on identical
contexts -- but each set needs somebody who reads the language, and seven exist
for 534 variant tags. The gap was never going to close, so the measurement moves
from *a corpus we author* to *evidence the models produce and we verify*.

**The one rule everything else rests on: an attestor is never told the answer.**
"Is this Montenegrin Serbian?" is a question with a presupposition in it, and a
model handed a presupposition will generally oblige -- inventing markers to
justify a yes, which is precisely the false evidence the whole redesign exists
to avoid. So an attestor is asked what the text *is*, from a list of varieties
it could be, and never which one was asked for.

That rule is enforced **by signature, not by prompt wording**. The expected tag
is not a parameter of any function here, so it cannot leak into a prompt by
accident -- not through a format string, not through a stray f-string, not
through a later edit by someone who did not read this docstring. `Blind` carries
what an attestor may see and nothing else, and it is the only way to address
one. A rule enforced by discipline is a rule that survives until the first
hurried change.

Three further rules, each from a protocol rather than from taste:

  gated first   eligibility is deterministic and is never handed to a model
                (016: 15/15 against 0/15). An attestor only ever sees text that
                already passed the gate.
  grounded      a cited marker must actually occur in the text. Marker scoring
                is string matching, so a fabricated marker yields a plausible
                number with nothing to flag it (convention 15).
  not itself    a model never attests its own output (005, and the S8 family
                guard). Enforced by the caller that picks the panel.

What this module does *not* do: decide verdicts, route panels, or aggregate.
Those are the probes and the record. Here there is one model call per function
and a parsed answer.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from llmlc.client import OpenAICompatClient

#: What an attestor may answer when the text carries nothing to go on. Offered
#: explicitly, because the failure we are guarding against is a model guessing
#: to be helpful. Protocol 012 measured a 25% void rate from elicitation
#: contexts that forced no choice; three sentences of neutral prose frequently
#: *is* generic, and "generic" is then the true answer, not a non-answer.
GENERIC = "generic"

#: And when it does not know the language well enough to judge at all. Recorded
#: when volunteered, never depended on: models rarely admit this, which is why
#: competence is established by manufactured controls instead.
UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class Blind:
    """Everything an attestor is allowed to see about a text's provenance.

    Deliberately not a `Language`, and deliberately frozen. A `Language` carries
    `tag`, `region_name` and `full`, any one of which names the answer; passing
    one into a prompt builder is a single careless line away from leaking it.
    This type cannot leak what it does not hold.

    `options` is the closed set of answers, already shuffled. `language` is the
    family name the attestor is told -- "Serbian", "Portuguese" -- which is not
    a giveaway: the question is which *variety*, and withholding the language
    would make the task a different one.
    """

    language: str
    options: tuple[str, ...]
    script_name: str | None = None

    def __post_init__(self) -> None:
        if len(set(self.options)) != len(self.options):
            raise ValueError(f"duplicate options would make the answer ambiguous: "
                             f"{self.options}")
        if len(self.options) < 2:
            raise ValueError("an identification with fewer than two options is "
                             "not a question")

    @property
    def answerable(self) -> tuple[str, ...]:
        """The options plus the two escapes, which are always available."""
        return (*self.options, GENERIC, UNSUPPORTED)


def shuffled(options: list[str], *, salt: str) -> tuple[str, ...]:
    """Order the options deterministically but not meaningfully.

    Deterministic so a run can be reproduced exactly, and so the bench shows what
    the batch run showed. Salted by the text rather than fixed, so the answer
    does not sit in the same position across a family's items -- a model with a
    position bias would otherwise score above chance on ordering alone, and we
    would read it as dialect knowledge.
    """
    digest = hashlib.sha256(salt.encode("utf-8")).digest()
    return tuple(sorted(options, key=lambda o: hashlib.sha256(
        digest + o.encode("utf-8")).digest()))


IDENTIFY_SYSTEM = """You are a linguist and a native speaker of {language}, \
asked to judge which regional variety a piece of text is written in.

You will be shown a text. Decide which of the listed varieties it is written in, \
judging only from the text itself.

Answer "{generic}" if the text is written in {language} but contains nothing \
that distinguishes one of these varieties from another. Neutral prose with no \
distinguishing feature is common, and "{generic}" is the correct answer for it \
— do not guess.
Answer "{unsupported}" if you do not know these varieties well enough to tell \
them apart.

For every marker you cite, quote the exact word or phrase as it appears in the \
text. Do not cite a marker that is not present in the text.

Reply with JSON only, exactly: \
{{"answer": "<one of the options>", "markers": [{{"text": "<quoted from the \
text>", "why": "<what it shows>"}}], "confidence": "high"|"medium"|"low"}}
No other text."""

IDENTIFY_USER = """Varieties it may be:
{options}

TEXT:
{text}"""


@dataclass
class Identification:
    """One attestor's blind reading of one text."""

    answer: str | None
    markers: list[dict] = field(default_factory=list)
    confidence: str | None = None
    raw: str | None = None
    error: str | None = None
    #: Markers the attestor cited that are **not** in the text it was shown.
    #: Filled by `ground`, not by the model.
    fabricated: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.answer)

    @property
    def declined(self) -> bool:
        """Said it cannot judge this family. A fact about the attestor."""
        return self.answer == UNSUPPORTED

    @property
    def generic(self) -> bool:
        """Said the text carries nothing to go on. A fact about the text."""
        return self.answer == GENERIC

    @property
    def decided(self) -> bool:
        """Named an actual variety, as opposed to taking either escape."""
        return self.ok and not self.declined and not self.generic

    def as_dict(self) -> dict:
        return {"answer": self.answer, "confidence": self.confidence,
                "markers": self.markers, "fabricated": self.fabricated,
                "error": self.error}


def _parse(raw: str) -> tuple[dict | None, str | None]:
    """The first JSON object in a response, or a reason there is none."""
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None, "no JSON object in the response"
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return None, f"unparseable JSON: {e}"
    if not isinstance(data, dict):
        return None, "JSON was not an object"
    return data, None


def _markers(data: dict) -> list[dict]:
    """Normalise the cited markers into `{text, why}` pairs.

    Tolerant of shape -- a bare list of strings, or objects under other keys --
    because a marker is evidence we verify ourselves, and discarding it over
    punctuation would throw away the thing that makes a verdict checkable. It is
    not tolerant about *content*: whatever is extracted gets ground against the
    text.
    """
    out: list[dict] = []
    for m in (data.get("markers") or []):
        if isinstance(m, str):
            out.append({"text": m, "why": ""})
        elif isinstance(m, dict):
            text = m.get("text") or m.get("marker") or m.get("word") or ""
            out.append({"text": str(text),
                        "why": str(m.get("why") or m.get("comment")
                                    or m.get("explanation") or "")})
    return [m for m in out if m["text"].strip()]


def ground(ident: Identification, text: str) -> Identification:
    """Check every cited marker actually occurs in the text it was cited for.

    This is the hallucination gate, and it is the piece of the marker instrument
    worth keeping: markers survive the redesign demoted from ground truth to
    evidence under verification. An attestor that says "yes, definitely, trust
    me" with three invented quotations is the failure mode a yes/no answer
    cannot catch, and a substring check catches it for nothing.

    Mutates and returns `ident` so a caller cannot accidentally keep the
    ungrounded copy.
    """
    hay = re.sub(r"\s+", " ", text).casefold()
    ident.fabricated = [m["text"] for m in ident.markers
                        if re.sub(r"\s+", " ", m["text"]).strip().casefold() not in hay]
    return ident


def identify(client: OpenAICompatClient, model: str, *, text: str,
             blind: Blind, max_tokens: int = 500) -> Identification:
    """Ask one attestor, blind, which variety a text is.

    Note what is absent from this signature: the expected tag, the producing
    model, any other attestor's answer. None of them can reach the prompt
    because none of them reach this function. That is the whole of the blinding
    mechanism, and it is why `Blind` exists rather than a `Language`.
    """
    options = "\n".join(f"- {o}" for o in blind.options)
    system = IDENTIFY_SYSTEM.format(language=blind.language, generic=GENERIC,
                                    unsupported=UNSUPPORTED)
    user = IDENTIFY_USER.format(options=options, text=text.strip())

    completion = client.complete(model, user, max_tokens=max_tokens, system=system)
    if not completion.ok:
        return Identification(None, error=completion.error, raw=completion.text)

    data, err = _parse(completion.text or "")
    if data is None:
        return Identification(None, raw=completion.text, error=err)

    answer = str(data.get("answer") or "").strip()
    # Matched case-insensitively against the closed set: a model answering
    # "Brazilian Portuguese" where the option read "brazilian portuguese" has
    # answered, and scoring that as unparseable would throw away a real result.
    match = next((o for o in blind.answerable if o.casefold() == answer.casefold()),
                 None)
    if match is None:
        return Identification(None, raw=completion.text,
                              markers=_markers(data),
                              confidence=str(data.get("confidence") or "") or None,
                              error=f"answer {answer!r} is not one of the options")

    ident = Identification(match, markers=_markers(data),
                           confidence=str(data.get("confidence") or "") or None,
                           raw=completion.text)
    return ground(ident, text)


#: What an attestor answers when two texts cannot be told apart -- because they
#: are the same variety, or because neither carries anything distinguishing.
#:
#: Offering it is what makes the contrast probe able to return a *negative*. A
#: forced two-way assignment has a floor of 0.5 by guessing, so without this
#: escape a model that can see no difference still scores half the pairs right
#: and the null control could never come back clean. The Russian set is the case
#: that matters: it must be possible to answer "these are the same", because
#: that is the true answer there.
INDISTINGUISHABLE = "indistinguishable"


SEPARATE_SYSTEM = """You are a linguist and a native speaker of {language}, \
asked to judge two texts.

You will be shown two texts, A and B. Decide which regional variety each one is \
written in, judging only from the texts themselves.

Answer "{indistinguishable}" for both if the two cannot be told apart — because \
they are written in the same variety, or because neither contains anything that \
distinguishes one variety from another. Two texts being different texts does not \
make them different varieties. This is a common and correct answer — do not \
invent a difference to avoid it.
Answer "{unsupported}" for both if you do not know these varieties well enough \
to tell them apart.

For every marker you cite, quote the exact word or phrase as it appears in the \
text, and say which text it came from. Do not cite a marker that is not present.

Reply with JSON only, exactly: \
{{"a": "<variety for text A>", "b": "<variety for text B>", \
"markers": [{{"text": "<quoted>", "in": "A"|"B", "why": "<what it shows>"}}], \
"confidence": "high"|"medium"|"low"}}
No other text."""

SEPARATE_USER = """Varieties they may be:
{options}

TEXT A:
{a}

TEXT B:
{b}"""


@dataclass
class Separation:
    """One attestor's blind reading of a pair."""

    a: str | None
    b: str | None
    markers: list[dict] = field(default_factory=list)
    confidence: str | None = None
    raw: str | None = None
    error: str | None = None
    fabricated: list[str] = field(default_factory=list)
    #: Whether the texts were shown in the order the caller passed them. The
    #: caller needs this to score the answer, and nothing in the prompt reveals
    #: it.
    swapped: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.a) and bool(self.b)

    @property
    def declined(self) -> bool:
        return self.a == UNSUPPORTED or self.b == UNSUPPORTED

    @property
    def merged(self) -> bool:
        """Said the two cannot be told apart. The negative result, and a real one."""
        return self.ok and (self.a == INDISTINGUISHABLE or self.b == INDISTINGUISHABLE)

    @property
    def split(self) -> bool:
        """Named two different varieties. The only answer that can be *correct*;
        whether it is correct is the caller's to decide, since only the caller
        knows which text was which."""
        return self.ok and not self.declined and not self.merged and self.a != self.b

    def as_dict(self) -> dict:
        return {"a": self.a, "b": self.b, "swapped": self.swapped,
                "confidence": self.confidence, "markers": self.markers,
                "fabricated": self.fabricated, "error": self.error}


def separate(client: OpenAICompatClient, model: str, *, first: str, second: str,
             blind: Blind, present: bool | None = None,
             max_tokens: int = 600) -> Separation:
    """Ask one attestor, blind, to assign varieties to a pair of texts.

    The pair is presented in an order salted by the texts themselves, so the
    expected answer is not always A. A model that always answers the options in
    the order they were listed would otherwise score 100% on every pair, and we
    would read a formatting habit as dialect knowledge.

    `swapped` on the result says what the attestor actually saw. The caller
    scores against it; the attestor never learns it.

    `present` forces the presentation instead of salting it, and exists for one
    caller: the order control, which must see *both* orders of one pair and
    cannot get them by swapping the arguments. Swapping flips which text is
    `first` and also re-salts the coin, and when the two coins happen to agree
    the attestor is shown the same order twice -- measured at 1,014 of 2,000
    pairs, so the control would have degenerated into a repeat test about half
    the time, passing a position-answering attestor for exactly the half of
    cases it was built to catch.

    It controls order only. Nothing about the expected answer passes through it,
    and `swapped` still reports what was shown.
    """
    swap = _coin(first + second) if present is None else present
    a, b = (second, first) if swap else (first, second)

    options = "\n".join(f"- {o}" for o in blind.options)
    system = SEPARATE_SYSTEM.format(language=blind.language, unsupported=UNSUPPORTED,
                                    indistinguishable=INDISTINGUISHABLE)
    user = SEPARATE_USER.format(options=options, a=a.strip(), b=b.strip())

    completion = client.complete(model, user, max_tokens=max_tokens, system=system)
    if not completion.ok:
        return Separation(None, None, error=completion.error, raw=completion.text,
                          swapped=swap)

    data, err = _parse(completion.text or "")
    if data is None:
        return Separation(None, None, raw=completion.text, error=err, swapped=swap)

    allowed = (*blind.options, INDISTINGUISHABLE, UNSUPPORTED)

    def pick(key: str) -> str | None:
        want = str(data.get(key) or "").strip()
        return next((o for o in allowed if o.casefold() == want.casefold()), None)

    got_a, got_b = pick("a"), pick("b")
    out = Separation(got_a, got_b, markers=_markers(data),
                     confidence=str(data.get("confidence") or "") or None,
                     raw=completion.text, swapped=swap)
    if got_a is None or got_b is None:
        out.error = (f"answers {data.get('a')!r}/{data.get('b')!r} are not both "
                     "in the option set")
        return out
    return ground(out, a + "\n" + b)


def _coin(salt: str) -> bool:
    """A stable coin flip from a string. Same reasoning as `shuffled`."""
    return hashlib.sha256(salt.encode("utf-8")).digest()[0] & 1 == 1
