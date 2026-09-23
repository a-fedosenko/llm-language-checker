"""Qualification, routing and caching -- what separates a model failure from an instrument failure."""
import json

import pytest

from llmlc.bt import QualStatus, QualificationCache, load_controls, qualify, route
from tests.conftest import FakeBackTranslator, FakeClient

FACT_CONTROLS = {"cv": {"kind": "facts", "items": [
    {"text": "Эпĕ чăвашла пĕлетĕп. Паян çанталăк питĕ аван.",
     "facts": ["The speaker knows Chuvash.", "The weather is good."]}]}}

REF_CONTROLS = {"kk": {"kind": "reference", "items": [
    {"text": "Дүйсенбі күні ғалымдар жаңа құралды жариялады.",
     "reference": "On Monday, scientists announced a new tool."}]}}


# -- reference controls, graded by chrF++ with no judge call ------------------

def test_reference_qualifies_a_faithful_back_translator():
    bt = FakeBackTranslator(default="On Monday, scientists announced a new tool.")
    q = qualify(bt, FakeClient([]), "judge", "kk", REF_CONTROLS)
    assert q.status is QualStatus.QUALIFIED
    assert q.kind == "reference"
    assert q.score > 90


def test_reference_rejects_a_fabricating_back_translator():
    """gpt-4o rendered known Chuvash as 'A man is walking. He is wearing a white shirt.'"""
    bt = FakeBackTranslator(default="A man is walking. He is wearing a white shirt.")
    q = qualify(bt, FakeClient([]), "judge", "kk", REF_CONTROLS)
    assert q.status is QualStatus.FAILED
    assert "cannot read the language" in q.detail


def test_reference_path_makes_no_judge_calls():
    client = FakeClient([])
    qualify(FakeBackTranslator(default="On Monday, scientists announced a new tool."),
            client, "judge", "kk", REF_CONTROLS)
    assert client.calls == [], "chrF++ grading must not cost a judge call"


# -- fact controls, for languages FLORES lacks (Chuvash among them) -----------

def test_facts_path_qualifies():
    bt = FakeBackTranslator(default="I know Chuvash. The weather is very nice today.")
    q = qualify(bt, FakeClient(['{"verdicts": ["present", "present"]}']), "judge", "cv", FACT_CONTROLS)
    assert q.status is QualStatus.QUALIFIED and q.kind == "facts"


def test_facts_path_fails_below_threshold():
    bt = FakeBackTranslator(default="Something about the weather.")
    q = qualify(bt, FakeClient(['{"verdicts": ["missing", "present"]}']), "judge", "cv", FACT_CONTROLS)
    assert q.status is QualStatus.FAILED


def test_no_control_is_an_admission_not_a_pass():
    q = qualify(FakeBackTranslator(default="x"), FakeClient([]), "judge", "zzz", REF_CONTROLS)
    assert q.status is QualStatus.NO_CONTROL
    assert not q.trustworthy, "absence of a control must never count as qualification"


# -- routing -----------------------------------------------------------------

def test_routing_picks_the_first_back_translator_that_can_read_the_language():
    bad = FakeBackTranslator(default="The sun rises in the east.")
    good = FakeBackTranslator(default="On Monday, scientists announced a new tool.")
    bad.id, good.id = "bt:cannot-read", "bt:can-read"
    chosen, q = route([bad, good], FakeClient([]), "judge", "kk", REF_CONTROLS)
    assert chosen is good
    assert q.trustworthy


def test_routing_reports_the_last_failure_when_none_qualify():
    a = FakeBackTranslator(default="The sun rises in the east.")
    b = FakeBackTranslator(default="A man is walking.")
    a.id, b.id = "bt:a", "bt:b"
    _, q = route([a, b], FakeClient([]), "judge", "kk", REF_CONTROLS)
    assert not q.trustworthy
    assert q.detail, "the caller must be able to say why no back-translator was usable"


# -- cache -------------------------------------------------------------------

def test_cache_avoids_repaying_qualification(tmp_path):
    cache = QualificationCache(tmp_path / "cache.json")
    bt = FakeBackTranslator(default="On Monday, scientists announced a new tool.")
    bt.id = "bt:x"
    first = qualify(bt, FakeClient([]), "judge", "kk", REF_CONTROLS, cache)

    bt.mapping, bt.default = {}, None      # any further call would now fail
    second = qualify(bt, FakeClient([]), "judge", "kk", REF_CONTROLS, cache)
    assert second.status is first.status and second.score == first.score


def test_cache_survives_a_restart(tmp_path):
    path = tmp_path / "cache.json"
    bt = FakeBackTranslator(default="On Monday, scientists announced a new tool.")
    bt.id = "bt:x"
    qualify(bt, FakeClient([]), "judge", "kk", REF_CONTROLS, QualificationCache(path))
    assert QualificationCache(path).get("bt:x", "kk").trustworthy


def test_cache_tolerates_a_corrupt_file(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("{not json", encoding="utf-8")
    assert QualificationCache(path).get("bt:x", "kk") is None


def test_cache_is_keyed_per_back_translator(tmp_path):
    cache = QualificationCache(tmp_path / "c.json")
    good = FakeBackTranslator(default="On Monday, scientists announced a new tool.")
    good.id = "bt:good"
    qualify(good, FakeClient([]), "judge", "kk", REF_CONTROLS, cache)
    assert cache.get("bt:other", "kk") is None


# -- the shipped control set -------------------------------------------------

def test_shipped_controls_cover_flores_breadth_and_the_hand_seeded_gap():
    c = load_controls()
    if not any(e.get("kind") == "reference" for e in c.values()):
        pytest.skip("FLORES controls not built locally; they are licence-encumbered "
                    "and not committed. Build with scripts/build_controls.py")
    assert len(c) > 150, "FLORES ingestion should provide broad coverage"
    assert c["cv"]["kind"] == "facts", "Chuvash is absent from FLORES and must fall back"
    assert c["kk"]["kind"] == "reference"
