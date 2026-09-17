"""The adaptive ladder: designator selection, pruning, and rung escalation."""
from llmlc.probe.ladder import DesignatorTrial, LadderResult, VOID
from llmlc.probe.gate import GateVerdict
from llmlc.probe.score import Evidence, Score, Tier


def _result(trials, designator):
    return LadderResult(
        tag="cv", engine="e", language=None, designator=designator,
        designator_kinds=("A",), trials=trials,
        score=Score(Tier.STRONG, 1.0, 0.9, (0.8, 1.0), False, Evidence.FACT_RECALL, 3),
        items=[], backtranslator="bt", judge_model="j", pivot="en",
        qualification=None, rungs_run=2)


def test_beat_incumbent_reported_when_selection_wins():
    trials = [DesignatorTrial("A", "Chuvash (Cyrillic script)", 3, 3),
              DesignatorTrial("E", "chv", 1, 3)]
    assert _result(trials, "Chuvash (Cyrillic script)").beat_incumbent is True


def test_beat_incumbent_is_none_without_an_incumbent():
    assert _result([DesignatorTrial("A", "Chuvash", 3, 3)], "Chuvash").beat_incumbent is None


def test_colliding_incumbent_is_not_a_comparison():
    """When the incumbent string equals another candidate they merge into one
    trial, so there was never a competitor to beat."""
    merged = DesignatorTrial("D", "chv", 3, 3, kinds=("D", "E"))
    assert _result([merged], "chv").beat_incumbent is None


def test_incumbent_winning_is_false_not_none():
    """A comparison that selection lost is a result, not a missing measurement."""
    trials = [DesignatorTrial("A", "Chuvash (Cyrillic script)", 1, 3),
              DesignatorTrial("E", "chv", 3, 3)]
    assert _result(trials, "chv").beat_incumbent is False


def test_void_verdicts_are_excluded_from_evidence():
    """Memorised, too-short and weak-LID items are neither pass nor negative."""
    assert GateVerdict.MEMORISED in VOID
    assert GateVerdict.LOW_CONFIDENCE in VOID
    assert GateVerdict.TOO_SHORT in VOID
    assert GateVerdict.REFUSED not in VOID
    assert GateVerdict.WRONG_LANGUAGE not in VOID


def test_trial_rate():
    assert DesignatorTrial("A", "x", 2, 4).rate == 0.5
    assert DesignatorTrial("A", "x", 0, 0).rate == 0.0
