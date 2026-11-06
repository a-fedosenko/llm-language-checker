"""The verdict ladder, and the capability record once it is persistent.

Two things are pinned hardest here. The ladder must never read an absent
measurement as a negative -- that is protocol 005's error and the easiest one to
make, because for a rare dialect "nobody could check" is the common case. And
the persistent record must be unable to express anything the in-memory one
cannot, or the "routes but never vouches" rule survives only as a comment.
"""
import pytest

from llmlc.probe.attest import Identification, Separation
from llmlc.probe.dialect import BlindRead, Consistency, ContrastRead, Conversion, DialectResult
from llmlc.probe.panel import (Capability, CapabilityKey, CapabilityRecord, Competence,
                               ControlKind, ControlResult, Panel, Role)
from llmlc.probe.variant import NOT_A_CLAIM, POSITIVE, DialectVerdict as V


@pytest.fixture
def db(tmp_path):
    from llmlc.db import reset_for_tests

    reset_for_tests(f"sqlite+pysqlite:///{tmp_path/'t.db'}")


def ok_panel(n=2):
    return Panel([Competence(f"att{i}", "Serbian",
                             controls=[ControlResult(ControlKind.IDENTITY, True)])
                  for i in range(n)])


def read(attestor, expected, answer, markers=None, fabricated=None):
    return BlindRead(attestor, expected,
                     Identification(answer, markers=markers or [],
                                    fabricated=fabricated or []))


def contrast(attestor, a, b, expected=("Serbia", "Montenegro")):
    return ContrastRead(attestor, expected[0], expected[1], Separation(a, b))


def runs(*edits):
    return Consistency(runs=[Conversion("d", "b", "a", edits=list(e), rate=0.3)
                             for e in edits],
                       agreement=1.0 if len({frozenset(e) for e in edits}) == 1 else 0.0)


def result(**kw):
    return DialectResult(tag="sr-me-cyrl", engine="eng", **kw)


# -- the ladder, in the order its checks run ---------------------------------

def test_no_competent_attestor_is_indeterminate_not_a_negative():
    """Checked first, because everything below would otherwise read an absent
    measurement as a negative. "Nobody could check" is a statement about the
    instrument; "the model cannot do it" is about the model."""
    r = result(panel=Panel([Competence("a", "Serbian",
                                       controls=[ControlResult(ControlKind.IDENTITY, False)])]))
    assert r.verdict is V.INDETERMINATE


def test_no_panel_at_all_is_indeterminate():
    assert result().verdict is V.INDETERMINATE


def test_indeterminate_wins_even_when_the_free_half_succeeded():
    """A clean conversion is evidence of *something*, but not of the thing the
    attestors were going to confirm. Promoting it would publish an unverified
    positive."""
    r = result(panel=Panel([]), conversions=runs([("a", "b")], [("a", "b")]))
    assert r.verdict is V.INDETERMINATE


def test_a_fabricated_marker_makes_the_whole_verdict_indeterminate():
    """A verdict propped up by invented quotations was not read off the text, so
    the panel did not measure anything however confident it sounded."""
    r = result(panel=ok_panel(),
               reads=[read("att0", "Montenegro", "Montenegro",
                           markers=[{"text": "x", "why": ""}], fabricated=["x"]),
                      read("att1", "Montenegro", "Montenegro")])
    assert r.verdict is V.INDETERMINATE


def test_blind_identification_confirmed_is_production():
    r = result(panel=ok_panel(),
               reads=[read("att0", "Montenegro", "Montenegro"),
                      read("att1", "Montenegro", "Montenegro")])
    assert r.verdict is V.PRODUCTION


def test_production_plus_repeatable_conversion_is_full_command():
    r = result(panel=ok_panel(),
               reads=[read("att0", "Montenegro", "Montenegro"),
                      read("att1", "Montenegro", "Montenegro")],
               conversions=runs([("дете", "дијете")], [("дете", "дијете")]))
    assert r.verdict is V.FULL_COMMAND


def test_conversion_that_is_not_repeatable_does_not_reach_full_command():
    """Writing it when free and rewriting on request the same way twice are
    different competences, and only the second earns the top of the ladder."""
    r = result(panel=ok_panel(),
               reads=[read("att0", "Montenegro", "Montenegro"),
                      read("att1", "Montenegro", "Montenegro")],
               conversions=runs([("a", "b")], [("c", "d")]))
    assert r.verdict is V.PRODUCTION


def test_separation_without_identification_is_recognition_only():
    """The attestors can tell the pair apart but could not name which was which
    unprompted: real discrimination, weaker than production."""
    r = result(panel=ok_panel(),
               reads=[read("att0", "Montenegro", "Serbia")],
               contrasts=[contrast("att0", "Serbia", "Montenegro"),
                          contrast("att1", "Serbia", "Montenegro")])
    assert r.verdict is V.RECOGNITION_ONLY


def test_nothing_found_is_no_evidence():
    r = result(panel=ok_panel(),
               reads=[read("att0", "Montenegro", "Serbia"),
                      read("att1", "Montenegro", "Serbia")])
    assert r.verdict is V.NO_EVIDENCE


def test_a_merged_pair_does_not_count_as_a_wrong_separation():
    """`indistinguishable` is an abstention about the text, not a vote against
    the model -- and it is the answer the Russian null control produces."""
    from llmlc.probe.attest import INDISTINGUISHABLE

    r = result(panel=ok_panel(),
               contrasts=[contrast("att0", INDISTINGUISHABLE, INDISTINGUISHABLE)])
    assert r.separated.counted == []
    assert r.verdict is V.NO_EVIDENCE


# -- what the levels mean when counted ---------------------------------------

def test_indeterminate_is_not_counted_as_a_negative():
    """Conflating "proven absent" with "not measurable" is how a limit of the
    instrument comes to be published as a property of the model -- the same
    split the project already keeps between Unusable and unverified."""
    assert V.INDETERMINATE in NOT_A_CLAIM
    assert V.INDETERMINATE not in POSITIVE
    assert V.NO_EVIDENCE not in NOT_A_CLAIM and V.NO_EVIDENCE not in POSITIVE


def test_only_production_and_above_assert_an_ability():
    assert POSITIVE == {V.PRODUCTION, V.FULL_COMMAND}


def test_the_ladder_is_separate_from_the_marker_states():
    """Merging them would make `proven` mean two different things depending on
    which instrument ran. The seven authored marker sets stay valid."""
    from llmlc.probe.variant import VariantEvidence

    assert not ({v.value for v in V} & {e.value for e in VariantEvidence})


# -- confidence --------------------------------------------------------------

def test_a_single_qualified_attestor_is_low_confidence():
    """One judge is one opinion. The panel rule says a single-member verdict is
    never silently promoted to a panel result."""
    r = result(panel=ok_panel(1), reads=[read("att0", "Montenegro", "Montenegro")])
    assert r.verdict is V.PRODUCTION and r.confidence == "low"


def test_a_split_panel_is_low_confidence_and_the_split_is_the_finding():
    r = result(panel=ok_panel(3),
               reads=[read("att0", "Montenegro", "Montenegro"),
                      read("att1", "Montenegro", "Montenegro"),
                      read("att2", "Montenegro", "Serbia")])
    assert r.identified.split and r.confidence == "low"
    assert r.verdict is not V.PRODUCTION, "a split panel has not confirmed anything"


def test_an_agreed_panel_of_two_is_high_confidence():
    r = result(panel=ok_panel(2),
               reads=[read("att0", "Montenegro", "Montenegro"),
                      read("att1", "Montenegro", "Montenegro")])
    assert r.confidence == "high"


def test_the_whole_result_serialises_with_its_evidence():
    """A reader who distrusts the verdict reads the probes; one who distrusts
    the probes reads the corpus. That chain is the deliverable."""
    import json

    r = result(panel=ok_panel(), reads=[read("att0", "Montenegro", "Montenegro")],
               conversions=runs([("a", "b")], [("a", "b")]))
    d = r.as_dict()
    json.dumps(d)
    assert d["verdict"] and d["identified"]["votes"] and d["conversion"]["runs"]


# -- the record, once it is persistent ---------------------------------------

def test_the_persistent_record_has_the_same_surface_as_the_memory_one(db):
    """The "routes but never vouches" rule has to survive persistence, and the
    way to be sure is for the stored version to be unable to express anything
    the in-memory one cannot."""
    from llmlc.db.qualcache import DbCapabilityRecord

    mem = {n for n in dir(CapabilityRecord) if not n.startswith("_")}
    dbr = {n for n in dir(DbCapabilityRecord) if not n.startswith("_")}
    assert dbr == mem


def test_a_capability_round_trips(db):
    from llmlc.db.qualcache import DbCapabilityRecord

    r = DbCapabilityRecord()
    key = CapabilityKey("deepseek-v4-pro", "sr-me-cyrl", Role.DISCRIMINATION, "Cyrl")
    r.put(Capability(key, True, confidence="high", probes=["identity", "order"],
                     detail="passed every control"))
    got = r.get(key)
    assert got.qualified and got.probes == ["identity", "order"]
    assert got.measured_at is not None, "the row has to carry its own age"


def test_role_is_part_of_the_identity(db):
    """The three dissociate: a row qualified for discrimination says nothing
    about generation and must not be read across."""
    from llmlc.db.qualcache import DbCapabilityRecord

    r = DbCapabilityRecord()
    r.put(Capability(CapabilityKey("m", "sr", Role.DISCRIMINATION), True))
    assert r.get(CapabilityKey("m", "sr", Role.GENERATION)) is None


def test_script_is_part_of_the_identity(db):
    """One variety written in two scripts is two measurements: `sr-me-cyrl` is
    identified cleanly where `sr-me-latn` cannot be told from Bosnian at all."""
    from llmlc.db.qualcache import DbCapabilityRecord

    r = DbCapabilityRecord()
    r.put(Capability(CapabilityKey("m", "sr-me-cyrl", Role.DISCRIMINATION, "Cyrl"), True))
    assert r.get(CapabilityKey("m", "sr-me-latn", Role.DISCRIMINATION, "Latn")) is None


def test_re_measuring_updates_rather_than_duplicating(db):
    from llmlc.db.qualcache import DbCapabilityRecord

    r = DbCapabilityRecord()
    key = CapabilityKey("m", "sr", Role.DISCRIMINATION)
    r.put(Capability(key, True))
    r.put(Capability(key, False, detail="failed: order"))
    assert len(r.rows()) == 1 and r.get(key).qualified is False


def test_the_routing_query_reads_every_model_for_one_variety(db):
    """"Which model handles which dialect in which role" is plausibly more
    useful to a reader than any single model's verdict."""
    from llmlc.db.qualcache import DbCapabilityRecord

    r = DbCapabilityRecord()
    for m, ok in [("a", True), ("b", False), ("c", True)]:
        r.put(Capability(CapabilityKey(m, "pt-br", Role.DISCRIMINATION), ok))
    assert r.known(["a", "b", "c"], tag="pt-br",
                   role=Role.DISCRIMINATION) == {"a": True, "b": False, "c": True}


def test_an_unmeasured_model_is_absent_rather_than_false(db):
    """Absent means never tried, which is ordered differently from tried and
    failed -- and both are still tried."""
    from llmlc.db.qualcache import DbCapabilityRecord

    r = DbCapabilityRecord()
    r.put(Capability(CapabilityKey("a", "pt-br", Role.DISCRIMINATION), False))
    known = r.known(["a", "b"], tag="pt-br", role=Role.DISCRIMINATION)
    assert known == {"a": False} and "b" not in known


def test_records_are_scoped_to_a_method_version(db):
    """Same rule as every other stored measurement: a record made under one
    method is not evidence about another."""
    from llmlc.db.qualcache import DbCapabilityRecord

    DbCapabilityRecord("9.9.9").put(
        Capability(CapabilityKey("m", "sr", Role.DISCRIMINATION), True))
    assert DbCapabilityRecord("1.0.0").get(
        CapabilityKey("m", "sr", Role.DISCRIMINATION)) is None
