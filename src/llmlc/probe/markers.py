"""Variant markers: closed shibboleth sets, and how a generation is scored against one.

The measurement this supports is deliberately narrow. It asks whether a model
*marks* a variant — chooses `boot` over `trunk`, `-ise` over `-ize` — not whether
it has full dialectal competence. That is a proxy, and doc 01 requires us to say
so wherever the number appears.

Two rules carry the whole design:

**Comparative, not absolute.** A hit is a variant marker; a miss is the sibling's
marker in the same slot. Counting variant markers alone would reward verbosity
and punish a short answer that happened not to reach for the word.

**Void the item when neither appears.** That means the elicitation context failed
to force the choice, which is our fault, not the model's. Scoring it zero would
punish the model for a bad context and, worse, would hide the bad context.

The markers are never named in the prompt. Telling a model to write `boot` and
then checking whether it wrote `boot` measures instruction-following; the file
carries elicitation contexts instead, which make the choice unavoidable without
naming it (docs/01, "Marker file schema").
"""
from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field
from functools import lru_cache

from pydantic import BaseModel, Field, model_validator

MARKERS_DIR = pathlib.Path(__file__).resolve().parents[3] / "markers"

#: A marker written `-ise` matches a word *ending* in it, so one entry covers
#: realise/organise/recognise. A bare `-` prefix is the only special syntax.
SUFFIX = "-"


class MarkerAxis(BaseModel):
    """One dimension along which the variants diverge deterministically."""

    axis: str = Field(description="lexis | orthography | grammar")
    variant: list[str]
    sibling: list[str]

    @model_validator(mode="after")
    def _no_overlap(self) -> "MarkerAxis":
        """A string on both sides scores a hit and a miss for the same word.

        Caught at load time because it is invisible at scoring time: the rate
        would simply be wrong, with nothing to indicate it. Two real examples
        from drafting the shipped file -- `chips` (opposite meanings in en-GB and
        en-US) and `on the weekend` (used by both) -- are exactly the kind of
        marker an author reaches for without noticing.
        """
        both = {x.lower() for x in self.variant} & {x.lower() for x in self.sibling}
        if both:
            raise ValueError(f"axis {self.axis!r}: {sorted(both)} appear as both variant and "
                             f"sibling markers, so they cannot discriminate")
        return self


class MarkerSet(BaseModel):
    """One variant's entry in a marker file.

    `status` is what makes remaining work countable:

    - ``markers`` -- a list exists; the variant is testable
    - ``not-distinguishable`` -- a finished decision that the variants do not
      differ in everyday register, so inheriting is *correct* rather than a
      fallback

    A tag absent from every file is neither of those: it is `untested`, an
    unfilled gap. Conflating the two is what makes coverage unmeasurable.
    """

    status: str = Field(pattern="^(markers|not-distinguishable)$")
    sibling: str | None = None
    #: The prompt string that names the variant. Authored rather than derived:
    #: protocol 010 found country-qualified designators unreliable when built
    #: automatically, and this way the choice sits next to the markers a human
    #: reviews.
    designator: str | None = None
    markers: list[MarkerAxis] = Field(default_factory=list)
    elicitation: list[str] = Field(default_factory=list)
    note: str | None = None
    #: Who wrote it and whether a human has checked it. Marker lists are claims
    #: about a language; an unreviewed one should not be mistaken for a reviewed
    #: one just because it is in the repository.
    source: str | None = None
    reviewed: bool = False

    @model_validator(mode="after")
    def _contexts_do_not_name_markers(self) -> "MarkerSet":
        """An elicitation context must not contain a marker from either side.

        Found the hard way (protocol 012): a context reading "leaving a block of
        flats in autumn, walking to the underground station" named three `en-GB`
        markers, and the American arm scored hits by echoing the prompt. The
        measurement then reports the context back to itself.

        This is the same rule as "the markers are never named in the prompt"
        (docs/01), enforced rather than trusted -- the leak is invisible in the
        output, which reads as a perfectly ordinary marker hit.
        """
        every = [m for axis in self.markers for m in (*axis.variant, *axis.sibling)]
        for context in self.elicitation:
            named = sorted({m for m in every if _cached_pattern(m).search(context)})
            if named:
                raise ValueError(
                    f"elicitation context names the markers {named}: "
                    f"{context[:60]!r}. Describe the situation that forces the choice, "
                    f"never the word that resolves it")
        return self

    @model_validator(mode="after")
    def _shape_matches_status(self) -> "MarkerSet":
        if self.status == "markers" and not (self.markers and self.elicitation):
            raise ValueError("status 'markers' needs both markers and elicitation contexts; "
                             "use 'not-distinguishable' for a decided non-difference")
        if self.status == "not-distinguishable" and not self.note:
            raise ValueError("'not-distinguishable' must carry a note saying why -- it is a "
                             "linguistic claim, and an unexplained one cannot be reviewed")
        return self

    @property
    def testable(self) -> bool:
        return self.status == "markers" and bool(self.markers) and bool(self.elicitation)


#: Inflections a single-word marker also matches. Without these, `neighbour`
#: misses "neighbours" while the sibling `neighbor` happens to match "neighbor's"
#: -- an asymmetric miss that moves the score rather than merely lowering it.
#: Found in protocol 012, where a context that plainly elicited the choice scored
#: as void.
INFLECTIONS = ("s", "es", "ed", "ing", "'s", "\u2019s")


def _pattern(marker: str) -> re.Pattern:
    """Compile one marker to a word-boundary-safe pattern.

    Three cases:

    - **Suffix** (`-ise`) -- matches a word ending in it, and needs at least one
      preceding letter or `-our` would match the word "our".
    - **Multi-word** (`car park`, `in hospital`) -- matched exactly. Inflecting a
      phrase is a different problem and these are chosen to be stable.
    - **Single word** -- matched with its regular English inflections, including
      the dropped `e` of *organise -> organising*.
    """
    if marker.startswith(SUFFIX):
        stem = re.escape(marker[len(SUFFIX):])
        return re.compile(rf"\b\w+{stem}\b", re.IGNORECASE)
    if " " in marker:
        return re.compile(rf"(?<!\w){re.escape(marker)}(?!\w)", re.IGNORECASE)

    endings = "|".join(re.escape(s) for s in INFLECTIONS)
    if marker.endswith("e"):
        # organise -> organis(e|es|ed|ing); the bare stem is not a word, so
        # allowing it costs nothing and keeps the pattern simple.
        stem = re.escape(marker[:-1])
        tail = rf"(?:e|{endings})?"
    else:
        stem, tail = re.escape(marker), rf"(?:{endings})?"
    return re.compile(rf"(?<!\w){stem}{tail}(?!\w)", re.IGNORECASE)


@lru_cache(maxsize=2048)
def _cached_pattern(marker: str) -> re.Pattern:
    return _pattern(marker)


def _hits(text: str, markers: list[str]) -> list[str]:
    return [m for m in markers if _cached_pattern(m).search(text)]


@dataclass
class AxisOutcome:
    axis: str
    variant_hits: list[str] = field(default_factory=list)
    sibling_hits: list[str] = field(default_factory=list)

    @property
    def decided(self) -> bool:
        return bool(self.variant_hits or self.sibling_hits)


@dataclass
class VariantOutcome:
    """One generation scored against one marker set."""

    axes: list[AxisOutcome] = field(default_factory=list)
    error: str | None = None

    @property
    def variant_hits(self) -> int:
        return sum(len(a.variant_hits) for a in self.axes)

    @property
    def sibling_hits(self) -> int:
        return sum(len(a.sibling_hits) for a in self.axes)

    @property
    def void(self) -> bool:
        """Neither variant nor sibling appeared: the context failed to force a choice."""
        return not (self.variant_hits or self.sibling_hits)

    @property
    def rate(self) -> float | None:
        """Share of marked choices that went the variant's way. `None` when void."""
        total = self.variant_hits + self.sibling_hits
        return None if not total else self.variant_hits / total

    def as_dict(self) -> dict:
        return {
            "rate": None if self.rate is None else round(self.rate, 3),
            "variant_hits": self.variant_hits,
            "sibling_hits": self.sibling_hits,
            "void": self.void,
            "axes": [{"axis": a.axis, "variant": a.variant_hits, "sibling": a.sibling_hits}
                     for a in self.axes if a.decided],
            "error": self.error,
        }


def score_text(text: str | None, markers: MarkerSet) -> VariantOutcome:
    """Score one generation. Local, free, and deterministic -- no model call."""
    if not text or not text.strip():
        return VariantOutcome(error="empty generation")
    return VariantOutcome(axes=[
        AxisOutcome(axis=a.axis,
                    variant_hits=_hits(text, a.variant),
                    sibling_hits=_hits(text, a.sibling))
        for a in markers.markers
    ])


@lru_cache(maxsize=4)
def load_markers(directory: str | None = None) -> dict[str, MarkerSet]:
    """Every marker set on disk, keyed by tag.

    Files are merged, so the corpus grows by adding a file rather than by editing
    one. A tag defined twice is an authoring error and raises: silently letting
    one file win would make a marker list's meaning depend on filename order.
    """
    root = pathlib.Path(directory) if directory else MARKERS_DIR
    out: dict[str, MarkerSet] = {}
    origin: dict[str, str] = {}
    if not root.is_dir():
        return out
    for path in sorted(root.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        for tag, body in raw.items():
            if tag.startswith("_"):      # file-level metadata, not a tag
                continue
            if tag in out:
                raise ValueError(f"marker set for {tag!r} defined twice: "
                                 f"{origin[tag]} and {path.name}")
            out[tag] = MarkerSet.model_validate(body)
            origin[tag] = path.name
    return out


def coverage(scheme, directory: str | None = None) -> dict:
    """What is decided and what is still a gap.

    The point of this function is that the gap is a number. `untested` is an
    unfilled placeholder, and a placeholder nobody counts is a placeholder nobody
    fills.
    """
    sets = load_markers(directory)
    classes = scheme.classes()
    variants = [t for members in classes.values() if len(members) > 1
                for t in sorted(members, key=lambda x: (len(x), x))[1:]]
    have_markers = [t for t in variants if (s := sets.get(t)) and s.testable]
    settled = [t for t in variants if (s := sets.get(t)) and s.status == "not-distinguishable"]
    return {
        "variant_tags": len(variants),
        "markers": len(have_markers),
        "not_distinguishable": len(settled),
        "untested": len(variants) - len(have_markers) - len(settled),
        "tags": {"markers": sorted(have_markers), "not_distinguishable": sorted(settled)},
    }
