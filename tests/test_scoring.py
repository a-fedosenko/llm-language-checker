"""Eligibility, adequacy, the derived tier, and the refusal to round away uncertainty.

The scale these tests pin was rebuilt by protocol 018 after protocols 014, 016
and 017 showed the five-tier one measured two things at most. Several tests below
exist to stop a specific defect of the old scale coming back, and say which.
"""
import pytest

from llmlc.probe.score import (ELIGIBLE_MIN_LANG, ORDER, PROFICIENT_MIN_CONTENT,
                               Evidence, Tier, bootstrap_ci, is_eligible, score,
                               tier_for)


# -- the shape of the scale ---------------------------------------------------

def test_the_tier_is_derived_from_eligibility_then_adequacy():
    assert tier_for(1.0, 1.0) is Tier.PROFICIENT
    assert tier_for(1.0, 0.5) is Tier.ASSISTED
    assert tier_for(0.0, 1.0) is Tier.UNUSABLE, "wrong language is unusable whatever it says"


def test_eligibility_is_one_threshold_not_three():
    """Protocol 017: s_lang moves in steps of 1/n, so 0.95 / 0.90 / 0.80 need
    n >= 20 items to tell apart. At three items they were one threshold."""
    assert is_eligible(1.0) and is_eligible(2 / 3)
    assert not is_eligible(1 / 3)
    assert tier_for(0.80, 1.0) is tier_for(0.90, 1.0) is tier_for(1.0, 1.0)


def test_the_tier_is_monotonic_in_adequacy():
    """The defect that sank the old scale: `Usable` ranked below `None` on real
    data, because the function hard-gated and then binned. Nothing derived from a
    single ascending cut can invert, and this asserts it stays that way."""
    seen = [ORDER.index(tier_for(1.0, c / 20)) for c in range(21)]
    assert seen == sorted(seen)


def test_every_tier_is_reachable():
    """`Basic` was never assigned in 40 real results. A tier no measurement can
    produce is not a tier."""
    produced = {tier_for(0.0, 0.0), tier_for(1.0, 0.5), tier_for(1.0, 1.0)}
    assert produced == set(ORDER)


def test_the_old_tier_names_are_gone():
    """A 1.x row must fail to parse rather than read as comparable."""
    for old in ("Strong", "Usable", "Basic", "Token", "None"):
        with pytest.raises(ValueError):
            Tier(old)


# -- eligibility over the items the gate would rule on ------------------------

def test_a_voided_item_leaves_the_denominator_rather_than_counting_as_failure():
    """probe/gate.py calls a low-confidence LID "too weak to count against the
    model". Before protocol 018 the arithmetic counted it anyway."""
    s = score(lang_pass=[True, False], content=[1.0], evidence=Evidence.FACT_RECALL,
              voided=1)
    assert s.s_lang == 1.0, "one pass, one void, no accusation"
    assert s.eligible and s.tier is Tier.PROFICIENT
    assert s.voided == 1
    assert any("declined to rule" in n for n in s.notes)


def test_a_convicted_item_still_counts_against_eligibility():
    s = score(lang_pass=[True, False], content=[1.0], evidence=Evidence.FACT_RECALL)
    assert s.s_lang == pytest.approx(0.5)
    assert s.eligible, "0.5 is the threshold and the threshold is inclusive"


def test_wrong_language_more_often_than_not_is_unusable():
    s = score(lang_pass=[False, False, True], content=[0.9],
              evidence=Evidence.FACT_RECALL)
    assert s.s_lang == pytest.approx(1 / 3)
    assert not s.eligible
    assert s.tier is Tier.UNUSABLE


def test_perfect_adequacy_cannot_rescue_an_ineligible_language():
    """Protocol 016: fact recall is script-blind and language-blind. The filter is
    what stops "fluent Indonesian" being reported as Acehnese support."""
    s = score(lang_pass=[False] * 3, content=[1.0] * 3, evidence=Evidence.FACT_RECALL)
    assert s.s_content == 1.0 and s.tier is Tier.UNUSABLE


# -- adequacy is published, not just banded -----------------------------------

def test_the_number_survives_into_the_output():
    """Protocol 017's conclusion 4: whatever scale ships, the continuous score
    belongs in the output. The tier is a lossy view of it, never a replacement."""
    s = score(lang_pass=[True] * 3, content=[0.8, 0.9, 0.7], evidence=Evidence.FACT_RECALL)
    d = s.as_dict()
    assert d["s_content"] == pytest.approx(0.8)
    assert d["eligible"] is True
    assert d["ci"] and d["tier"] == "Assisted"


def test_the_adequacy_cut_sits_at_the_top_of_the_floor():
    """Protocol 016 measured adequacy as near-binary above a threshold, so the one
    cut a floor can carry belongs at its top edge, not in the middle."""
    assert PROFICIENT_MIN_CONTENT == 0.95
    assert ELIGIBLE_MIN_LANG == 0.50


# -- intervals ----------------------------------------------------------------

def test_borderline_is_flagged_not_rounded():
    s = score(lang_pass=[True] * 6, content=[1.0, 0.9, 1.0, 0.9, 1.0, 0.9],
              evidence=Evidence.FACT_RECALL)
    assert s.borderline, "an interval spanning the adequacy cut must say so"
    assert s.ci[0] < PROFICIENT_MIN_CONTENT < s.ci[1]


def test_confident_result_is_not_borderline():
    s = score(lang_pass=[True] * 6, content=[1.0] * 6, evidence=Evidence.FACT_RECALL)
    assert s.tier is Tier.PROFICIENT
    assert not s.borderline


def test_bootstrap_is_deterministic_and_bounded():
    v = [0.2, 0.4, 0.6, 0.8, 1.0]
    assert bootstrap_ci(v) == bootstrap_ci(v)
    lo, hi = bootstrap_ci(v)
    assert 0.0 <= lo <= sum(v) / len(v) <= hi <= 1.0


def test_single_item_interval_is_degenerate_not_invented():
    assert bootstrap_ci([0.7]) == (0.7, 0.7)


# -- evidence kinds that settle the result without grading it -----------------

def test_deterministic_negative_needs_no_judge_and_no_interval():
    s = score(lang_pass=[False] * 3, content=[], evidence=Evidence.DETERMINISTIC_NEGATIVE)
    assert s.tier is Tier.UNUSABLE
    assert s.evidence is Evidence.DETERMINISTIC_NEGATIVE
    assert s.n_gated == 3
    assert s.ci == (0.0, 0.0)


def test_unverified_says_why_and_does_not_claim_a_tier():
    s = score(lang_pass=[True] * 3, content=[], evidence=Evidence.UNVERIFIED)
    assert s.tier is Tier.UNUSABLE
    assert s.evidence is Evidence.UNVERIFIED
    assert any("not assessable" in n for n in s.notes)


def test_unverified_beats_content_even_when_items_were_graded():
    """A correct model must not be scored by an instrument that cannot read it."""
    s = score(lang_pass=[True] * 3, content=[0.1, 0.0, 0.2], evidence=Evidence.UNVERIFIED)
    assert s.tier is Tier.UNUSABLE and s.evidence is Evidence.UNVERIFIED


def test_unverified_is_not_the_same_claim_as_unusable_the_measurement():
    """Both report the same tier; only the evidence field separates "we could not
    look" from "we looked and it failed". `no-control` is never a pass."""
    blind = score(lang_pass=[True] * 3, content=[], evidence=Evidence.UNVERIFIED)
    failed = score(lang_pass=[False] * 3, content=[],
                   evidence=Evidence.DETERMINISTIC_NEGATIVE)
    assert blind.tier is failed.tier
    assert blind.evidence is not failed.evidence


def test_workflow_meaning_travels_with_the_tier():
    s = score(lang_pass=[True] * 3, content=[1.0] * 3, evidence=Evidence.FACT_RECALL)
    assert s.workflow and s.as_dict()["workflow"] == s.workflow


# -- refusal is a willingness signal, not a capability one --------------------

def test_refusals_do_not_make_a_capable_model_look_incapable():
    """Real case: gpt-4o wrote perfect Uyghur twice and refused once. Scoring that
    as unusable would be a false statement."""
    s = score(lang_pass=[True, True], content=[1.0, 1.0], evidence=Evidence.FACT_RECALL,
              refusals=1)
    assert s.tier is Tier.PROFICIENT
    assert s.reliability == pytest.approx(2 / 3)
    assert s.refusals == 1
    assert any("Refused 1 of 3" in n for n in s.notes)


def test_reliability_is_one_when_nothing_was_refused():
    s = score(lang_pass=[True] * 3, content=[1.0] * 3, evidence=Evidence.FACT_RECALL)
    assert s.reliability == 1.0
    assert s.refusals == 0
    assert not any("Refused" in n for n in s.notes)


def test_total_refusal_is_a_deterministic_negative_with_zero_reliability():
    s = score(lang_pass=[], content=[], evidence=Evidence.DETERMINISTIC_NEGATIVE,
              refusals=3)
    assert s.tier is Tier.UNUSABLE
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
    """gpt-4o wrote perfect Uyghur once and refused twice. "light review" was true
    about the text and silent about how rarely it arrived."""
    from llmlc.probe.score import Availability
    s = score(lang_pass=[True], content=[1.0], evidence=Evidence.FACT_RECALL, refusals=2)
    assert s.tier is Tier.PROFICIENT, "capability is not restated as inability"
    assert s.availability is Availability.UNRELIABLE
    assert "fallback" in s.workflow and "2 refusal(s) of 3" in s.workflow


def test_a_reliable_result_gets_no_caveat():
    s = score(lang_pass=[True] * 3, content=[1.0] * 3, evidence=Evidence.FACT_RECALL)
    assert s.workflow == "light review"


def test_unusable_carries_no_availability_caveat():
    """'do not offer -- expect retries' would be noise: there is nothing to offer."""
    s = score(lang_pass=[False, False], content=[], evidence=Evidence.DETERMINISTIC_NEGATIVE,
              refusals=1)
    assert s.tier is Tier.UNUSABLE
    assert s.workflow == "do not offer"


def test_availability_is_serialised_alongside_reliability():
    s = score(lang_pass=[True], content=[1.0], evidence=Evidence.FACT_RECALL, refusals=2)
    d = s.as_dict()
    assert d["availability"] == "unreliable"
    assert d["reliability"] == 0.333
