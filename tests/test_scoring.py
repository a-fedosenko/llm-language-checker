"""Tiers, intervals and the refusal to round away uncertainty."""
import pytest

from llmlc.probe.score import Evidence, Tier, bootstrap_ci, score, tier_for


def test_tier_thresholds():
    assert tier_for(1.0, 0.9) is Tier.STRONG
    assert tier_for(1.0, 0.6) is Tier.USABLE
    assert tier_for(1.0, 0.4) is Tier.BASIC
    assert tier_for(0.6, 0.9) is Tier.TOKEN, "fluency gates content: wrong language cannot be Strong"
    assert tier_for(0.1, 0.9) is Tier.NONE


def test_borderline_is_flagged_not_rounded():
    s = score(lang_pass=[True] * 6, content=[0.4, 0.6, 0.5, 0.6, 0.4, 0.6],
              evidence=Evidence.FACT_RECALL)
    assert s.borderline, "an interval spanning a tier boundary must say so"
    assert s.ci[0] < 0.5 < s.ci[1]


def test_confident_result_is_not_borderline():
    s = score(lang_pass=[True] * 6, content=[1.0, 1.0, 0.9, 1.0, 0.9, 1.0],
              evidence=Evidence.FACT_RECALL)
    assert s.tier is Tier.STRONG
    assert not s.borderline


def test_deterministic_negative_needs_no_judge_and_no_interval():
    s = score(lang_pass=[False] * 3, content=[], evidence=Evidence.DETERMINISTIC_NEGATIVE)
    assert s.tier is Tier.NONE
    assert s.evidence is Evidence.DETERMINISTIC_NEGATIVE
    assert s.n_gated == 3
    assert s.ci == (0.0, 0.0)


def test_unverified_says_why_and_does_not_claim_a_tier():
    s = score(lang_pass=[True] * 3, content=[], evidence=Evidence.UNVERIFIED)
    assert s.tier is Tier.NONE
    assert s.evidence is Evidence.UNVERIFIED
    assert any("not assessable" in n for n in s.notes)


def test_unverified_beats_content_even_when_items_were_graded():
    """A correct model must not be scored by an instrument that cannot read it."""
    s = score(lang_pass=[True] * 3, content=[0.1, 0.0, 0.2], evidence=Evidence.UNVERIFIED)
    assert s.tier is Tier.NONE and s.evidence is Evidence.UNVERIFIED


def test_workflow_meaning_travels_with_the_tier():
    s = score(lang_pass=[True] * 3, content=[0.9, 0.9, 0.9], evidence=Evidence.FACT_RECALL)
    assert s.workflow and s.as_dict()["workflow"] == s.workflow


def test_bootstrap_is_deterministic_and_bounded():
    v = [0.2, 0.4, 0.6, 0.8, 1.0]
    assert bootstrap_ci(v) == bootstrap_ci(v)
    lo, hi = bootstrap_ci(v)
    assert 0.0 <= lo <= sum(v) / len(v) <= hi <= 1.0


def test_single_item_interval_is_degenerate_not_invented():
    assert bootstrap_ci([0.7]) == (0.7, 0.7)


# -- refusal is a willingness signal, not a capability one --------------------

def test_refusals_do_not_make_a_capable_model_look_incapable():
    """Real case: gpt-4o wrote perfect Uyghur twice and refused once. Scoring that
    as Token ('recognises it, cannot use it') would be a false statement."""
    s = score(lang_pass=[True, True], content=[1.0, 1.0], evidence=Evidence.FACT_RECALL,
              refusals=1)
    assert s.tier is Tier.STRONG
    assert s.reliability == pytest.approx(2 / 3)
    assert s.refusals == 1
    assert any("Refused 1 of 3" in n for n in s.notes)


def test_reliability_is_one_when_nothing_was_refused():
    s = score(lang_pass=[True] * 3, content=[1.0] * 3, evidence=Evidence.FACT_RECALL)
    assert s.reliability == 1.0
    assert s.refusals == 0
    assert not any("Refused" in n for n in s.notes)


def test_wrong_language_still_counts_against_capability():
    """Refusal is excluded from s_lang; producing the wrong language is not."""
    s = score(lang_pass=[False, False, True], content=[0.9],
              evidence=Evidence.FACT_RECALL)
    assert s.s_lang == pytest.approx(1 / 3)
    assert s.tier is Tier.NONE


def test_total_refusal_is_a_deterministic_negative_with_zero_reliability():
    s = score(lang_pass=[], content=[], evidence=Evidence.DETERMINISTIC_NEGATIVE,
              refusals=3)
    assert s.tier is Tier.NONE
    assert s.reliability == 0.0
    assert s.n_items == 3


# -- availability: willingness as its own axis --------------------------------

def test_availability_bands():
    from llmlc.probe.score import Availability, availability_for
    assert availability_for(1.0) is Availability.RELIABLE
    assert availability_for(0.90) is Availability.RELIABLE
    assert availability_for(0.89) is Availability.INTERMITTENT
    assert availability_for(0.60) is Availability.INTERMITTENT
    assert availability_for(0.59) is Availability.UNRELIABLE
    assert availability_for(0.0, attempts=3) is Availability.REFUSED
    assert availability_for(0.0) is Availability.UNRELIABLE, "nothing attempted is not a refusal"


def test_the_ug_case_says_something_about_availability():
    """gpt-4o wrote perfect Uyghur once and refused twice. 'Strong -- light review'
    was true about the text and silent about how rarely it arrived."""
    from llmlc.probe.score import Availability
    s = score(lang_pass=[True], content=[1.0], evidence=Evidence.FACT_RECALL, refusals=2)
    assert s.tier is Tier.STRONG, "capability is not restated as inability"
    assert s.availability is Availability.UNRELIABLE
    assert "fallback" in s.workflow and "2 refusal(s) of 3" in s.workflow


def test_a_reliable_result_gets_no_caveat():
    s = score(lang_pass=[True] * 3, content=[0.9] * 3, evidence=Evidence.FACT_RECALL)
    assert s.workflow == "light review"


def test_tier_none_carries_no_availability_caveat():
    """'do not offer -- expect retries' would be noise: there is nothing to offer."""
    s = score(lang_pass=[False, False], content=[], evidence=Evidence.DETERMINISTIC_NEGATIVE,
              refusals=1)
    assert s.tier is Tier.NONE
    assert s.workflow == "do not offer"


def test_availability_is_serialised_alongside_reliability():
    s = score(lang_pass=[True], content=[1.0], evidence=Evidence.FACT_RECALL, refusals=2)
    d = s.as_dict()
    assert d["availability"] == "unreliable"
    assert d["reliability"] == 0.333
