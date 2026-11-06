"""The five-value support status, and the table built from it.

The status mapping is the part worth testing hard: a wrong branch here does not
look odd, it publishes a false claim. Three of the five values exist precisely
to keep claims apart that a four-value scheme would merge.
"""
import pytest

from llmlc.config import settings
from llmlc.support import (CONFIDENCE_CUTS, MEANING, ORDER, Status,
                           confidence_for, row_for, status_for)


class Row:
    """The attributes `status_for` reads. A stand-in rather than a DB row, so
    these tests state exactly which fields the mapping depends on."""

    def __init__(self, evidence="fact-recall", tier="Proficient", s_content=1.0,
                 ci_low=1.0, ci_high=1.0, borderline=False, inherited_from=None,
                 backtranslator="remote:gemini-gemini-3-6-flash", id=1):
        self.evidence, self.tier, self.s_content = evidence, tier, s_content
        self.ci_low, self.ci_high, self.borderline = ci_low, ci_high, borderline
        self.inherited_from, self.backtranslator, self.id = inherited_from, backtranslator, id


# -- the mapping -------------------------------------------------------------

def test_no_row_is_unchecked():
    assert status_for(None) is Status.UNCHECKED


def test_a_graded_eligible_row_is_supported():
    assert status_for(Row()) is Status.SUPPORTED


def test_assisted_is_supported_because_status_follows_eligibility():
    """`Assisted` means eligible but under the adequacy cut. The tier is a
    routing convenience; the number carries the quality (protocol 018)."""
    assert status_for(Row(tier="Assisted", s_content=0.6)) is Status.SUPPORTED


def test_a_deterministic_negative_is_unsupported():
    assert status_for(Row(evidence="deterministic-negative", tier="Unusable")) is Status.UNSUPPORTED


def test_unverified_is_its_own_status_and_not_unsupported():
    """The distinction the whole table exists to preserve. The row stores tier
    `Unusable` because no-control is never a pass, but that is a statement about
    the instrument, not the model -- reporting it as a model failure is the
    error protocol 005 exists to prevent."""
    row = Row(evidence="unverified", tier="Unusable")
    assert status_for(row) is Status.UNVERIFIABLE
    assert status_for(row) is not Status.UNSUPPORTED
    assert status_for(row) is not Status.UNCHECKED


def test_an_inherited_row_is_supported_via_dialect():
    assert status_for(Row(inherited_from="de")) is Status.SUPPORTED_VIA_DIALECT


def test_inheritance_never_rescues_a_failed_base_language():
    """Order matters: inheritance only ever reclassifies something that would
    otherwise be `supported`. A variant of a language the model cannot write is
    unsupported, not supported-via-dialect."""
    row = Row(evidence="deterministic-negative", tier="Unusable", inherited_from="ace")
    assert status_for(row) is Status.UNSUPPORTED


def test_a_graded_row_that_failed_the_gate_is_unsupported():
    """Eligibility is a floor and failing it is a proven negative however it was
    reached -- five rows in the four-engine programme are fact-recall Unusable."""
    assert status_for(Row(tier="Unusable", s_content=0.0)) is Status.UNSUPPORTED


def test_every_status_has_a_meaning_and_a_place_in_the_order():
    assert set(ORDER) == set(Status)
    assert set(MEANING) == set(Status)


# -- the number and its confidence -------------------------------------------

def test_confidence_comes_from_interval_width():
    assert confidence_for(1.0, 1.0) == "high"
    assert confidence_for(0.85, 1.0) == "high"
    assert confidence_for(0.6, 0.95) == "medium"
    assert confidence_for(0.2, 0.9) == "low"


def test_confidence_is_none_without_an_interval():
    assert confidence_for(None, None) is None


def test_confidence_is_independent_of_borderline():
    """Two different statements, kept as two axes: width says how firm the
    number is, borderline says it straddles the tier cut (cf. tier vs
    availability, protocol 011)."""
    r = row_for("de", Row(ci_low=1.0, ci_high=1.0, borderline=True))
    assert r.confidence == "high" and r.borderline is True


def test_cuts_are_ordered_so_the_first_match_is_the_firmest():
    widths = [c for c, _ in CONFIDENCE_CUTS]
    assert widths == sorted(widths)


def test_an_unsupported_row_shows_no_score():
    """Its s_content is 0.0 by construction, not by measurement. Rendering it
    would invite reading a convention as a result."""
    r = row_for("ace", Row(evidence="deterministic-negative", tier="Unusable", s_content=0.0))
    assert r.status is Status.UNSUPPORTED
    assert r.score is None and r.confidence is None


def test_an_unverifiable_row_shows_no_score_either():
    r = row_for("bi", Row(evidence="unverified", tier="Unusable", s_content=0.0))
    assert r.score is None


def test_a_supported_row_carries_its_number():
    r = row_for("sw", Row(s_content=0.9333333))
    assert r.score == 0.933 and r.as_dict()["status"] == "supported"


# -- the table ---------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    from llmlc.db import reset_for_tests
    reset_for_tests(f"sqlite+pysqlite:///{tmp_path/'t.db'}")


def test_the_scheme_is_the_left_side_of_the_join(db):
    """Every tag in the scheme appears, measured or not. `unchecked` is the
    answer that says what is left to do, and dropping those rows would hide it."""
    from llmlc.api.support_table import build
    from llmlc.scheme import load_scheme

    d = build("never-measured-model")
    # Against the *active* scheme's own census rather than a hardcoded one: the
    # claim is that nothing is dropped from the left side, which is true of any
    # locale list and was never about the public catalogue's size.
    assert d["total"] == len(load_scheme(settings.scheme).languages)
    assert d["counts"]["unchecked"] == d["total"]
    assert all(r["score"] is None for r in d["rows"])


def test_rows_are_sorted_by_language_name(db):
    from llmlc.api.support_table import build

    names = [(r["name"] or r["tag"]).lower() for r in build("m")["rows"]]
    assert names == sorted(names)


def test_a_missing_database_is_an_empty_table_not_an_error(monkeypatch):
    """Browsing must work for someone who has never run a scan."""
    from llmlc.api import support_table

    monkeypatch.setattr(support_table, "_results_for_engine",
                        lambda engine: (_ for _ in ()).throw(RuntimeError("no db")))
    d = support_table.build("m")
    assert d["counts"]["unchecked"] == d["total"]


# -- the canonical reader ----------------------------------------------------

def test_the_preferred_panel_reader_wins_over_a_later_one():
    """gpt-4o holds rows from five back-translators. A table promising one row
    per language has to pick, and panel order is a measured property (S8), so
    preferring it is preferring the better instrument."""
    from llmlc.api.support_table import PANEL_ORDER, _pick

    first, second = PANEL_ORDER[0], PANEL_ORDER[1]
    rows = [Row(backtranslator=f"remote:{second}", id=9),
            Row(backtranslator=f"remote:{first}", id=2)]
    assert _pick(rows).backtranslator == f"remote:{first}"


def test_an_off_panel_reader_loses_to_the_no_instrument_row():
    """A deterministic negative is comparable against every reader (convention
    14), so it beats a reading by a model no longer on the panel."""
    from llmlc.db.models import NO_INSTRUMENT
    from llmlc.api.support_table import _pick

    rows = [Row(backtranslator="remote:some-retired-model", id=9),
            Row(backtranslator=NO_INSTRUMENT, id=1)]
    assert _pick(rows).backtranslator == NO_INSTRUMENT


def test_a_real_reading_beats_the_no_instrument_row():
    from llmlc.db.models import NO_INSTRUMENT
    from llmlc.api.support_table import PANEL_ORDER, _pick

    rows = [Row(backtranslator=NO_INSTRUMENT, id=9),
            Row(backtranslator=f"remote:{PANEL_ORDER[0]}", id=1)]
    assert rows[1] is _pick(rows)


def test_the_pivot_suffix_does_not_hide_a_panel_member():
    """The pivot language rides in the reader id as `remote:model@de`
    (protocol 013), and matching must see through it."""
    from llmlc.api.support_table import PANEL_ORDER, _reader_rank

    assert _reader_rank(f"remote:{PANEL_ORDER[0]}@de") == 0


def test_ties_break_towards_the_most_recent_measurement():
    from llmlc.api.support_table import PANEL_ORDER, _pick

    bt = f"remote:{PANEL_ORDER[0]}"
    assert _pick([Row(backtranslator=bt, id=1), Row(backtranslator=bt, id=7)]).id == 7


def test_collapsed_rows_are_counted_rather_than_hidden(db):
    """Showing one of five readers silently is how a reader comes to believe
    there was only ever one."""
    from llmlc.api import support_table

    monkey = {"de": [Row(id=1), Row(id=2, backtranslator="remote:other")]}
    original = support_table._results_for_engine
    support_table._results_for_engine = lambda engine: monkey
    try:
        # Pinned to the public catalogue, where exactly one tag is `de`. A TMS
        # locale list carries `de-at`, `de-ch`, `de-de` and more, each of which
        # legitimately borrows the stored `de` row through its alias and
        # collapses its own pair -- correct behaviour, but it turns a count of
        # one into a count of however many regional spellings that list happens
        # to hold, which is not what this test is about.
        d = support_table.build("m", "default")
    finally:
        support_table._results_for_engine = original
    assert d["rows_collapsed"] == 1


# -- the endpoints -----------------------------------------------------------

def test_the_endpoint_returns_counts_and_rows(db):
    from fastapi.testclient import TestClient
    from llmlc.api.main import app

    d = TestClient(app).get("/support", params={"engine": "m"}).json()
    assert set(d["counts"]) == {s.value for s in Status}
    assert d["rows"] and {"tag", "status", "score", "confidence"} <= set(d["rows"][0])


def test_a_huge_scheme_is_capped_and_says_so(db):
    """Nobody browses nine thousand rows, and the uncapped response is 2 MB."""
    from fastapi.testclient import TestClient
    from llmlc.api.main import app, SUPPORT_MAX_ROWS

    # Explicitly the 9,589-tag catalogue: the active scheme is a 602-tag locale
    # list, which is under the cap and correctly reports nothing truncated.
    d = TestClient(app).get("/support", params={"engine": "m",
                                                "scheme": "default"}).json()
    assert d["truncated"] > SUPPORT_MAX_ROWS
    assert len(d["rows"]) == SUPPORT_MAX_ROWS
    assert d["total"] == d["truncated"]       # the counts still cover everything


def test_capping_drops_unchecked_rows_and_never_measured_ones(db, monkeypatch):
    """The page filters client-side, so a flat alphabetical slice silently
    shrinks what the filters can reach: the counts said 29 `unverifiable` while
    the table could only show the 5 that fell inside the first 2,000 rows.
    Measured rows are the whole point and are never the ones cut.
    """
    from fastapi.testclient import TestClient

    from llmlc.api import main, support_table

    # One measured row near the end of the alphabet, which a slice would lose.
    late = max(support_table.build("m")["rows"], key=lambda r: (r["name"] or r["tag"]).lower())
    monkeypatch.setattr(support_table, "_results_for_engine",
                        lambda engine: {late["tag"]: [Row(evidence="unverified",
                                                          tier="Unusable")]})
    monkeypatch.setattr(main, "SUPPORT_MAX_ROWS", 50)
    d = TestClient(main.app).get("/support", params={"engine": "m"}).json()

    assert d["counts"]["unverifiable"] == 1
    assert any(r["tag"] == late["tag"] for r in d["rows"]), "a measured row was cut"
    assert d["unchecked_omitted"] == d["counts"]["unchecked"] - (50 - 1)


def test_status_meanings_are_served_from_the_one_definition(db):
    """The page renders these as tooltips. Restating them in the HTML is how
    a label's meaning comes to differ between the code and the UI."""
    from fastapi.testclient import TestClient
    from llmlc.api.main import app

    d = TestClient(app).get("/support/statuses").json()
    assert d["order"] == [s.value for s in ORDER]
    assert d["meaning"]["unverifiable"] == MEANING[Status.UNVERIFIABLE]


# -- a user's own locale list ------------------------------------------------

def test_a_borrowed_result_is_supported_via_dialect_not_supported():
    """A scheme maps `ar-eg` onto the canonical `ar`, so the table can show it
    something. What it shows is a measurement of `ar` -- a weaker claim than a
    measurement of `ar-eg`, and labelled as one (convention 12)."""
    r = row_for("ar-eg", Row(), borrowed_from="ar")
    assert r.status is Status.SUPPORTED_VIA_DIALECT
    assert r.inherited_from == "ar"
    assert r.score == 1.0, "the number is still the number that was measured"


def test_borrowing_never_upgrades_a_negative():
    for ev, expected in (("deterministic-negative", Status.UNSUPPORTED),
                         ("unverified", Status.UNVERIFIABLE)):
        r = row_for("ar-eg", Row(evidence=ev, tier="Unusable"), borrowed_from="ar")
        assert r.status is expected


def test_a_direct_measurement_outranks_nothing_and_stays_supported():
    assert row_for("ar", Row()).status is Status.SUPPORTED


def test_the_schemes_endpoint_lists_what_is_on_disk(db):
    from fastapi.testclient import TestClient
    from llmlc.api.main import app

    d = TestClient(app).get("/schemes").json()
    names = {s["file"] for s in d["schemes"]}
    # The active locale list is always offered. `default` is withheld whenever
    # a real locale list exists beside it -- see `schemes()` for why that is
    # conditional rather than absolute.
    assert settings.scheme in names
    assert all({"name", "file", "count"} <= set(s) for s in d["schemes"])


# -- named groups over the five statuses -------------------------------------

def test_usable_spans_measured_and_inherited():
    from llmlc.support import GROUPS

    assert GROUPS["usable"] == (Status.SUPPORTED, Status.SUPPORTED_VIA_DIALECT)


def test_every_group_names_real_statuses_and_has_a_meaning():
    from llmlc.support import GROUP_MEANING, GROUPS

    assert set(GROUPS) == set(GROUP_MEANING)
    for members in GROUPS.values():
        assert members and all(isinstance(s, Status) for s in members)


def test_groups_are_filters_and_never_a_sixth_status():
    """`usable` spans a measurement and an inheritance on purpose. Promoting it
    to a status would absorb the weaker claim into the label; as a filter, the
    rows under it still say which of the two they are."""
    from llmlc.support import GROUPS

    assert set(GROUPS) & {s.value for s in Status} == set()


def test_the_statuses_endpoint_serves_the_groups(db):
    """The page renders these; restating which statuses a named filter covers
    in the markup is how the two come to disagree."""
    from fastapi.testclient import TestClient
    from llmlc.api.main import app
    from llmlc.support import GROUPS

    d = TestClient(app).get("/support/statuses").json()
    assert d["groups"]["usable"] == ["supported", "supported-via-dialect"]
    assert set(d["groups"]) == set(GROUPS) == set(d["group_meaning"])
    for members in d["groups"].values():
        assert set(members) <= set(d["order"])
