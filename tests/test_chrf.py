"""chrF++ -- used both to qualify a back-translator and to score against gold references."""
import pytest

from llmlc.probe.chrf import chrf


def test_identical_text_scores_100():
    assert chrf("A woman missed the bus.", "A woman missed the bus.") == pytest.approx(100.0)


def test_empty_input_scores_zero_rather_than_raising():
    assert chrf("", "A woman missed the bus.") == 0.0
    assert chrf("A woman missed the bus.", "") == 0.0


def test_paraphrase_scores_well_above_fabrication():
    ref = "A woman missed the morning bus."
    paraphrase = chrf("The woman didn't catch the morning bus.", ref)
    fabrication = chrf("The sun rises in the east.", ref)
    assert paraphrase > 45 > fabrication


def test_real_qualification_cases_separate_cleanly():
    """The measured gap that motivates the threshold."""
    ref = "I know Chuvash. The weather is very good today."
    fabricated = chrf("A man is walking. He is wearing a white shirt.", ref)
    faithful = chrf("I know Chuvash. The weather is very nice today.", ref)
    assert fabricated < 30 < faithful


def test_reordering_is_penalised_but_still_reads_as_related():
    """Word bigrams make chrF++ order-sensitive, which is correct: a reordered
    sentence scores well below identical text, but far above unrelated text."""
    ref = "the quick brown fox jumps"
    shuffled = chrf("quick the fox brown jumps", ref)
    unrelated = chrf("completely different words here", ref)
    assert unrelated < 30 < shuffled < 100


def test_score_is_symmetric_enough_to_be_stable():
    a, b = "A woman missed the bus", "The woman missed a bus"
    assert abs(chrf(a, b) - chrf(b, a)) < 15
