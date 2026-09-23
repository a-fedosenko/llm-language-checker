"""The calibration study's scoring: pairing, rank correlation, and the bands.

The correlation maths is the part worth testing hardest. It is the number the
whole method will be judged on, it is computed here rather than pulled from a
library, and a subtly wrong rho would be indistinguishable from a real finding.
"""
import pytest

from llmlc.probe.calibrate import (CalibrationItem, CalibrationResult, correlate,
                                   load_specs, spearman)
from llmlc.probe.score import Evidence


def item(id_="x", chrf=None, recall=None, **kw):
    return CalibrationItem(item_id=id_, source="s", reference="r",
                           chrf=chrf, recall=recall, **kw)


def result(tag="af", items=()):
    return CalibrationResult(tag=tag, engine="m", backtranslator="bt",
                             judge_model="j", pivot="en", items=list(items))


# -- rank correlation --------------------------------------------------------

def test_perfect_agreement_is_one():
    assert spearman([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]) == pytest.approx(1.0)


def test_perfect_disagreement_is_minus_one():
    assert spearman([1, 2, 3, 4, 5], [50, 40, 30, 20, 10]) == pytest.approx(-1.0)


def test_it_measures_ordering_not_linearity():
    """Spearman, not Pearson: the two metrics are on different scales and there is
    no reason to expect a straight line, only the same ordering."""
    assert spearman([1, 2, 3, 4], [1, 4, 9, 16]) == pytest.approx(1.0)


def test_against_the_closed_form_on_tie_free_data():
    """Checked against rho = 1 - 6*sum(d^2)/(n*(n^2-1)), which is only valid when
    there are no ties -- so it cross-checks the general implementation against an
    independent formula rather than against itself."""
    def closed_form(xs, ys):
        n = len(xs)
        rx = {v: i for i, v in enumerate(sorted(xs))}
        ry = {v: i for i, v in enumerate(sorted(ys))}
        d2 = sum((rx[x] - ry[y]) ** 2 for x, y in zip(xs, ys))
        return 1 - 6 * d2 / (n * (n * n - 1))

    for xs, ys in ([[1, 2, 3, 4, 5], [2, 1, 4, 3, 5]],
                   [[10, 20, 30, 40, 50, 60], [3, 1, 2, 6, 4, 5]],
                   [[5, 3, 8, 1], [2, 9, 4, 7]]):
        assert spearman(xs, ys) == pytest.approx(closed_form(xs, ys), abs=1e-9)


def test_ties_are_averaged_rather_than_ordered_arbitrarily():
    """Fact recall over a five-fact checklist takes six values, so ties are the
    norm. Breaking them by position would invent signal that is not there."""
    assert spearman([1, 1, 2, 2], [1, 1, 2, 2]) == pytest.approx(1.0)
    assert spearman([1, 1, 1, 1], [1, 2, 3, 4]) is None, "a constant metric has no ordering"


def test_too_few_points_is_none_rather_than_a_number():
    assert spearman([1, 2], [1, 2]) is None
    assert spearman([], []) is None


def test_mismatched_lengths_are_refused():
    assert spearman([1, 2, 3], [1, 2]) is None


# -- pairing -----------------------------------------------------------------

def test_an_item_is_paired_only_with_both_scores():
    assert item(chrf=50.0, recall=0.8).paired
    assert not item(chrf=50.0).paired
    assert not item(recall=0.8).paired


def test_unpaired_items_are_excluded_from_the_correlation():
    r = result(items=[item("a", 60.0, 0.9), item("b", 40.0), item("c", recall=0.5)])
    assert len(r.paired) == 1
    assert correlate([r])["n_items"] == 1


def test_means_use_whatever_scores_exist():
    """A judge failure should not discard a perfectly good chrF++ reading."""
    r = result(items=[item("a", 60.0, 0.9), item("b", 40.0)])
    assert r.mean_chrf == pytest.approx(50.0)
    assert r.mean_recall == pytest.approx(0.9)


# -- evidence ----------------------------------------------------------------

def test_a_graded_language_carries_gold_reference():
    """The only place this evidence class is produced; S2 expected it to fall out
    of the ordinary probe and it could not."""
    assert result(items=[item(chrf=60.0, recall=0.9)]).evidence == \
        Evidence.GOLD_REFERENCE.value


def test_a_language_with_no_reference_score_is_unverified():
    assert result(items=[item(recall=0.9)]).evidence == Evidence.UNVERIFIED.value


def test_a_language_with_nothing_paired_says_so():
    r = result(items=[item("a", 40.0)])
    from llmlc.probe.calibrate import calibrate_language  # noqa: F401 -- import guard
    assert r.paired == []


# -- the study-level report --------------------------------------------------

def test_both_levels_are_reported():
    """Item level asks whether the proxy tracks quality sentence by sentence;
    language level asks whether it ranks languages the same way, which is what
    the tool actually claims."""
    rs = [result("af", [item(f"a{i}", 90 - i * 10, 0.9 - i * 0.1) for i in range(4)]),
          result("cv", [item(f"c{i}", 30 - i * 5, 0.3 - i * 0.05) for i in range(4)])]
    stats = correlate(rs)
    assert stats["n_items"] == 8 and stats["n_languages"] == 2
    assert stats["item_spearman"] == pytest.approx(1.0)
    assert stats["language_spearman"] is None, "two languages cannot support a rank correlation"


def test_the_offset_says_which_metric_is_more_forgiving():
    """Recall on 0-1 against chrF++ on 0-100, compared on a common scale. A
    positive offset means recall is the forgiving one."""
    rs = [result(items=[item("a", 50.0, 0.9), item("b", 50.0, 0.7)])]
    assert correlate(rs)["mean_offset_recall_minus_chrf"] == pytest.approx(0.3)


def test_offsets_are_banded_so_a_failure_at_the_bottom_is_visible():
    """The predicted shape is agreement at the top and a widening spread below
    chrF++ 40. That is only visible if the bands are reported separately."""
    rs = [result(items=[item("hi", 80.0, 0.8), item("mid", 50.0, 0.7),
                        item("lo", 10.0, 0.6)])]
    bands = correlate(rs)["offset_by_band"]
    assert set(bands) == {"chrf>=60", "chrf 40-60", "chrf<40"}
    assert bands["chrf>=60"]["mean"] == pytest.approx(0.0)
    assert bands["chrf<40"]["mean"] == pytest.approx(0.5), "the proxy is loosest at the bottom"


def test_an_empty_study_does_not_invent_a_correlation():
    stats = correlate([])
    assert stats["n_items"] == 0
    assert stats["item_spearman"] is None and stats["language_spearman"] is None


# -- specs -------------------------------------------------------------------

def test_missing_specs_are_an_empty_dict_not_a_crash(tmp_path):
    """They are derived from FLORES and never committed, so absent is the normal
    state of a fresh clone."""
    assert load_specs(tmp_path / "nope.json") == {}
