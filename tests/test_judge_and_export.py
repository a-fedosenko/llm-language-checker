"""Judge parsing, and the merge function that must never corrupt a master file."""
from llmlc.export import merge_support
from llmlc.probe.judge import FactVerdict, judge
from tests.conftest import FakeClient

FACTS = ["A woman missed a bus.", "It rained.", "The office was closed."]


def test_judge_parses_three_valued_verdicts():
    c = FakeClient(['{"verdicts": ["present", "missing", "contradicted"]}'])
    j = judge(c, "judge-model", "A woman missed the bus.", FACTS)
    assert j.ok
    assert j.verdicts == [FactVerdict.PRESENT, FactVerdict.MISSING, FactVerdict.CONTRADICTED]
    assert j.recall == 1 / 3
    assert j.contradictions == 1


def test_judge_tolerates_prose_around_the_json():
    c = FakeClient(['Sure! Here is the result:\n{"verdicts": ["present","present","present"]}\nDone.'])
    assert judge(c, "m", "text", FACTS).recall == 1.0


def test_judge_reports_a_count_mismatch_rather_than_guessing():
    c = FakeClient(['{"verdicts": ["present"]}'])
    j = judge(c, "m", "text", FACTS)
    assert not j.ok and "expected 3" in (j.error or "")


def test_judge_never_sees_the_target_language_text():
    c = FakeClient(['{"verdicts": ["present","present","present"]}'])
    judge(c, "m", "A woman missed the bus.", FACTS)
    _, prompt = c.calls[0]
    assert "Чăваш" not in prompt and "designator" not in prompt.lower()


def test_merge_is_a_per_engine_upsert():
    existing = {"cv": {"mt.google": "cv"}, "de": {"mt.google": "de"}}
    merged = merge_support(existing, {"cv": {"mt.openai-gpt-4o": "Chuvash"}})
    assert merged["cv"] == {"mt.google": "cv", "mt.openai-gpt-4o": "Chuvash"}
    assert merged["de"] == {"mt.google": "de"}, "other keys must be untouched"


def test_absent_key_never_means_delete():
    existing = {"cv": {"mt.google": "cv"}, "ru": {"mt.google": "ru"}}
    merged = merge_support(existing, {"de": {"mt.x": "German"}})
    assert set(merged) == {"cv", "ru", "de"}
    assert merged["ru"] == {"mt.google": "ru"}


def test_measured_unsupported_leaves_other_engines_alone():
    existing = {"cv": {"mt.google": "cv"}}
    merged = merge_support(existing, {"cv": {}})
    assert merged["cv"] == {"mt.google": "cv"}


def test_merge_does_not_mutate_its_input():
    existing = {"cv": {"mt.google": "cv"}}
    merge_support(existing, {"cv": {"mt.new": "x"}})
    assert existing == {"cv": {"mt.google": "cv"}}
