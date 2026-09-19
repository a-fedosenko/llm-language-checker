"""Choosing the pivot language for one measurement.

The pivot is the language everything is back-translated into so a judge that does
not read the target language can still grade it. That works for every language
except one: **the pivot itself.**

Asked to measure `en` with `pivot=en`, the pipeline back-translates English into
English and grades the result against a control that does not exist, because
FLORES's English side is the reference for every other language and never a
target. The honest output was `unverified` -- true, and useless, on the single
best-supported language in the catalogue.

So a language that *is* the pivot is measured through a different pivot. Two
consequences follow and are handled rather than hidden:

- **The control must be inverted.** Every FLORES control is (target text ->
  English reference). Measuring English needs (English text -> German reference),
  which is the same aligned pair read the other way round.
- **The result is not comparable** with rows measured through the usual pivot.
  The effective pivot is recorded on the row and is part of the uniqueness
  constraint, so the two cannot overwrite each other.
"""
from __future__ import annotations

from llmlc.scheme import Language, Scheme

#: Pivots tried, in order, when the target language is itself the pivot. All
#: three are high-resource in any back-translator worth using and carry FLORES
#: reference text, which the derived control needs. A list rather than one value
#: so that choosing an unusual pivot does not simply move the blind spot: with
#: `--pivot de`, German falls through to French.
FALLBACKS = ("de", "fr", "es")
DEFAULT_FALLBACK = FALLBACKS[0]


def is_pivot_language(scheme: Scheme, lang: Language, pivot: str) -> bool:
    """Would measuring this language mean translating the pivot into itself?

    Compared by ISO 639-3 rather than by tag, so `en-AU` and `en-GB` are caught
    as well as `en`.
    """
    p = scheme.get(pivot)
    if p is None or not p.iso639_3 or not lang.iso639_3:
        return False
    return lang.iso639_3 == p.iso639_3


def resolve(scheme: Scheme, lang: Language, pivot: str,
            fallbacks: tuple[str, ...] | str = FALLBACKS) -> str:
    """The pivot to actually use for this language.

    Returns `pivot` unchanged for every language but the pivot's own, where it
    returns the first fallback that is not also the target. If every candidate is
    the target -- which takes deliberate effort -- the original pivot is returned,
    because a result that visibly fails to grade beats a swap that quietly did
    nothing.
    """
    if not is_pivot_language(scheme, lang, pivot):
        return pivot
    for candidate in ((fallbacks,) if isinstance(fallbacks, str) else fallbacks):
        if not is_pivot_language(scheme, lang, candidate):
            return candidate
    return pivot


def panel_for(scheme: Scheme, lang: Language, pivot: str, backtranslators: list):
    """(back-translators, effective pivot, controls) for one language.

    Returns its inputs unchanged for every language except the pivot's own, where
    the panel is rebuilt to translate into the fallback pivot and the control is
    the aligned pair read backwards. `controls` is None when nothing changed, so
    the caller keeps the default control set.
    """
    from llmlc.bt import RemoteBackTranslator, load_controls

    effective = resolve(scheme, lang, pivot)
    if effective == pivot:
        return backtranslators, pivot, None
    return ([RemoteBackTranslator(b.client, b.model, effective) for b in backtranslators],
            effective, load_controls(effective))
