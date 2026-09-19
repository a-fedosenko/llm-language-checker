"""Measuring the pivot language.

Back-translating English into English grades nothing, so `en` reported
`unverified` -- true, and useless, on the best-supported language in the
catalogue. These cover the swap to a fallback pivot and the three things it has
to get right: the control, the instrument identity, and not silently colliding
with a result measured the ordinary way.
"""
import pytest

from llmlc.bt import RemoteBackTranslator
from llmlc.bt.qualify import load_controls, pivot_control
from llmlc.probe import pivot as pivot_mod
from llmlc.scheme import load_scheme


@pytest.fixture(scope="module")
def scheme():
    return load_scheme("default")


# -- which language needs a different pivot ----------------------------------

def test_the_pivot_language_is_measured_through_a_fallback(scheme):
    assert pivot_mod.resolve(scheme, scheme.get("en"), "en") == pivot_mod.DEFAULT_FALLBACK


def test_every_other_language_keeps_the_requested_pivot(scheme):
    for tag in ("de", "cv", "ru", "kk-Latn"):
        assert pivot_mod.resolve(scheme, scheme.get(tag), "en") == "en"


def test_regional_variants_of_the_pivot_are_caught_too(scheme):
    """en-AU is English; translating it into English grades nothing either."""
    for tag in ("en-AU", "en-GB"):
        assert pivot_mod.resolve(scheme, scheme.get(tag), "en") == pivot_mod.DEFAULT_FALLBACK


def test_a_non_english_pivot_moves_which_language_is_special(scheme):
    """With a German pivot it is German that cannot be measured, not English."""
    assert pivot_mod.resolve(scheme, scheme.get("de"), "de") != "de"
    assert pivot_mod.resolve(scheme, scheme.get("en"), "de") == "de"


def test_the_fallback_falls_through_rather_than_moving_the_blind_spot(scheme):
    """With --pivot de, German is the one language that cannot be measured
    through German. It falls through to the next candidate instead."""
    assert pivot_mod.resolve(scheme, scheme.get("de"), "de") == "fr"


def test_when_every_candidate_is_the_target_the_failure_stays_visible(scheme):
    """Returning the original pivot yields a result that visibly fails to grade,
    which beats a swap that quietly did nothing."""
    assert pivot_mod.resolve(scheme, scheme.get("de"), "de", fallbacks=("de",)) == "de"


def test_every_fallback_can_actually_be_named_in_a_prompt():
    """"Translate into de" is a worse prompt than "Translate into German"."""
    from llmlc.bt.remote import PIVOT_NAMES
    assert all(p in PIVOT_NAMES for p in pivot_mod.FALLBACKS)


# -- the control -------------------------------------------------------------

def test_the_pivot_control_is_the_aligned_pair_read_backwards():
    """Every FLORES control is (target text -> English reference). Measuring
    English needs (English text -> German reference), which is the same data."""
    controls = {"de": {"kind": "reference",
                       "items": [{"text": "Der Hund bellt.", "reference": "The dog barks."}]}}
    derived = pivot_control(controls, "de")
    assert derived["items"] == [{"text": "The dog barks.", "reference": "Der Hund bellt."}]
    assert derived["derived_from"] == "de"


def test_no_control_is_invented_where_the_pivot_has_none():
    """Grading a back-translator against text nobody checked would be worse than
    reporting that we cannot grade it."""
    assert pivot_control({}, "de") is None
    assert pivot_control({"de": {"kind": "facts", "items": [1]}}, "de") is None


def test_loading_controls_for_a_fallback_pivot_supplies_english():
    """Skipped where the FLORES controls are not present locally -- they are
    licence-encumbered and not committed.

    The guard asks for a *reference* control specifically. The committed seed
    controls include `de`, but as `facts` rather than aligned text, and a facts
    control has no reference side to read backwards -- so merely checking that
    `de` is present passed in a fresh clone and then failed on the inversion.
    """
    entry = load_controls("en").get(pivot_mod.DEFAULT_FALLBACK)
    if not entry or entry.get("kind") != "reference":
        pytest.skip("FLORES reference controls not built locally")
    assert "en" not in load_controls("en"), "English needs no control when it is the pivot"
    assert load_controls("de")["en"]["items"], "a German pivot gives English a control"


# -- instrument identity -----------------------------------------------------

def test_the_pivot_rides_in_the_back_translator_id():
    """Same model translating into German is a different instrument."""
    assert RemoteBackTranslator(None, "m", "en").id == "remote:m"
    assert RemoteBackTranslator(None, "m", "de").id == "remote:m@de"


def test_english_stays_unsuffixed_so_existing_rows_keep_their_identity():
    """Otherwise every result and cached qualification written before this would
    be orphaned by a rename."""
    assert "@" not in RemoteBackTranslator(None, "m", "en").id


def test_two_pivots_produce_two_results_rather_than_overwriting_one(tmp_path):
    """The uniqueness constraint is (engine, tag, method_version, backtranslator).
    Because the pivot is part of the instrument id, a row measured through German
    cannot silently replace one measured through English -- which matters, since
    the two are not comparable."""
    from datetime import datetime, timezone

    from llmlc.db import reset_for_tests, session
    from llmlc.db.repo import results_for, upsert_result
    reset_for_tests(f"sqlite+pysqlite:///{tmp_path/'t.db'}")

    def row(**kw):
        base = dict(engine="m", tag="en", cls="eng|Latn", tier="None",
                    evidence="unverified", s_lang=1.0, s_content=0.0, ci_low=0.0,
                    ci_high=0.0, borderline=False, designator="English",
                    backtranslator="remote:bt", judge="j", pivot="en",
                    method_version="1.0.0", tested_at=datetime.now(timezone.utc))
        base.update(kw)
        return base

    with session() as s:
        upsert_result(s, row())
        upsert_result(s, row(backtranslator="remote:bt@de", pivot="de",
                             tier="Strong", evidence="fact-recall", s_content=1.0))
    with session() as s:
        rows = {r.pivot: r.tier for r in results_for(s)}
    assert rows == {"en": "None", "de": "Strong"}


# -- the panel ---------------------------------------------------------------

def test_the_panel_is_rebuilt_only_for_the_pivot_language(scheme):
    panel = [RemoteBackTranslator(None, "a", "en"), RemoteBackTranslator(None, "b", "en")]
    same, pivot, controls = pivot_mod.panel_for(scheme, scheme.get("cv"), "en", panel)
    assert same is panel and pivot == "en" and controls is None

    swapped, pivot, controls = pivot_mod.panel_for(scheme, scheme.get("en"), "en", panel)
    assert [b.id for b in swapped] == ["remote:a@de", "remote:b@de"]
    assert pivot == "de"
    assert [b.model for b in swapped] == ["a", "b"], "the panel order and models are preserved"
