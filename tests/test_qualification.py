"""Back-translator qualification -- the check that separates a model failure from an instrument failure."""
from llmlc.bt import QualStatus, qualify
from tests.conftest import FakeBackTranslator, FakeClient

CONTROLS = {"cv": [{"text": "Эпĕ чăвашла пĕлетĕп. Паян çанталăк питĕ аван.",
                    "facts": ["The speaker knows Chuvash.", "The weather is good."]}]}


def test_qualified_when_facts_are_recovered():
    bt = FakeBackTranslator(default="I know Chuvash. The weather is very nice today.")
    client = FakeClient(['{"verdicts": ["present", "present"]}'])
    q = qualify(bt, client, "judge", "cv", CONTROLS)
    assert q.status is QualStatus.QUALIFIED
    assert q.trustworthy


def test_failed_when_the_back_translator_fabricates():
    """gpt-4o rendered known Chuvash as 'A man is walking. He is wearing a white shirt.'"""
    bt = FakeBackTranslator(default="A man is walking. He is wearing a white shirt.")
    client = FakeClient(['{"verdicts": ["missing", "missing"]}'])
    q = qualify(bt, client, "judge", "cv", CONTROLS)
    assert q.status is QualStatus.FAILED
    assert not q.trustworthy
    assert "cannot read the language" in q.detail


def test_no_control_is_an_admission_not_a_pass():
    bt = FakeBackTranslator(default="anything")
    q = qualify(bt, FakeClient([]), "judge", "xyz", CONTROLS)
    assert q.status is QualStatus.NO_CONTROL
    assert not q.trustworthy, "absence of a control must never be treated as qualification"


def test_partial_recovery_below_threshold_fails():
    bt = FakeBackTranslator(default="Something about weather.")
    client = FakeClient(['{"verdicts": ["missing", "present"]}'])   # 0.5 < MIN_RECALL
    assert qualify(bt, client, "judge", "cv", CONTROLS).status is QualStatus.FAILED
