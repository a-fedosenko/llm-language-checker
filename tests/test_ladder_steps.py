"""The ladder has one traversal, and two ways to consume it.

`run_ladder` drains the generator; the demo stand advances it a step at a time.
The property that matters is that those cannot disagree -- a second walk of the
ladder would drift, and convention 9 records what that costs: an analysis
harness re-implemented a production call, got it subtly wrong, and 68 bad
verdicts reached a protocol's conclusions.
"""
import pytest

from llmlc.bt import Qualification, QualStatus
from llmlc.probe import ladder as L
from llmlc.probe.gate import GateResult, GateVerdict
from llmlc.probe.judge import FactVerdict, Judgement
from llmlc.probe.specs import Spec
from llmlc.probe.steps import ItemOutcome
from llmlc.scheme import load_scheme


class Reader:
    id = "remote:fake-reader"


def stub(monkeypatch, *, gate=GateVerdict.PASS, recall=1.0, trustworthy=True):
    """Replace the three paid primitives with deterministic ones.

    The control flow is what the refactor changed, so that is what is pinned
    here; the primitives themselves have their own tests.
    """
    calls = {"generate": 0, "judge": 0}

    def fake_generate(*, client, engine, lang, designator, spec, corpus,
                      relatives, accept, n_sentences=3):
        calls["generate"] += 1
        return ItemOutcome(spec.id, designator, f"text for {spec.id}",
                           GateResult(gate, None, ""))

    def fake_judge(item, *, client, judge_model, backtranslator, spec, tag, corpus):
        calls["judge"] += 1
        n = max(1, round(recall * 4))
        item.back_translation = f"back: {spec.id}"
        item.judgement = Judgement(
            [FactVerdict.PRESENT] * n + [FactVerdict.MISSING] * (4 - n), "{}")
        return item

    def fake_route(cands, client, judge_model, tag, *, controls=None, cache=None):
        status = QualStatus.QUALIFIED if trustworthy else QualStatus.NO_CONTROL
        return Reader(), Qualification(status, 80.0 if trustworthy else 0.0,
                                       Reader.id, tag, "reference", "")

    monkeypatch.setattr(L, "generate_and_gate", fake_generate)
    monkeypatch.setattr(L, "judge_item", fake_judge)
    monkeypatch.setattr(L, "route", fake_route)
    monkeypatch.setattr(L.pivot_mod, "panel_for",
                        lambda scheme, lang, pivot, bts: (bts, pivot, None))
    return calls


@pytest.fixture
def kw():
    scheme = load_scheme("default")
    specs = [Spec(id=f"s{i}", scenario=f"scenario {i}", facts=["a", "b", "c", "d"])
             for i in range(9)]

    class NullCorpus:
        def write(self, record): pass

    return dict(scheme=scheme, tag="cv", engine="m", client=object(),
                backtranslators=[Reader()], judge_model="j", specs=specs,
                corpus=NullCorpus(), pivot="en")


def drain(gen):
    """Step a generator to exhaustion, keeping every step and the return value."""
    steps = []
    while True:
        try:
            steps.append(next(gen))
        except StopIteration as done:
            return steps, done.value


# -- the invariant -----------------------------------------------------------

@pytest.mark.parametrize("case", [
    {"gate": GateVerdict.PASS, "recall": 1.0},
    {"gate": GateVerdict.PASS, "recall": 0.5},
    {"gate": GateVerdict.WRONG_SCRIPT, "recall": 1.0},     # deterministic negative
    {"gate": GateVerdict.REFUSED, "recall": 1.0},          # refused everything
    {"gate": GateVerdict.PASS, "recall": 1.0, "trustworthy": False},  # unverified
])
def test_draining_and_stepping_reach_the_same_result(monkeypatch, kw, case):
    stub(monkeypatch, **case)
    drained = L.run_ladder(**kw)
    stub(monkeypatch, **case)
    _, stepped = drain(L.ladder_steps(**kw))

    assert drained.score.as_dict() == stepped.score.as_dict()
    assert drained.designator == stepped.designator
    assert drained.rungs_run == stepped.rungs_run
    assert drained.backtranslator == stepped.backtranslator
    assert drained.calls == stepped.calls


@pytest.mark.parametrize("case", [
    {"gate": GateVerdict.PASS, "recall": 1.0},
    {"gate": GateVerdict.WRONG_SCRIPT, "recall": 1.0},
])
def test_stepping_spends_exactly_what_draining_spends(monkeypatch, kw, case):
    """A step-at-a-time consumer must not cost more than the one-shot path."""
    a = stub(monkeypatch, **case)
    L.run_ladder(**kw)
    b = stub(monkeypatch, **case)
    drain(L.ladder_steps(**kw))
    assert a == b


# -- the steps themselves ----------------------------------------------------

def test_every_step_is_json_ready_and_described(monkeypatch, kw):
    stub(monkeypatch)
    import json

    steps, _ = drain(L.ladder_steps(**kw))
    assert steps
    for s in steps:
        d = s.as_dict()
        json.dumps(d)                       # the API serialises these verbatim
        assert d["title"] and d["explains"], f"{s.kind} has no description"
        assert d["kind"] in L.STEP_HELP


def test_exactly_one_terminal_step_and_it_is_last(monkeypatch, kw):
    stub(monkeypatch)
    steps, _ = drain(L.ladder_steps(**kw))
    assert [i for i, s in enumerate(steps) if s.terminal] == [len(steps) - 1]


def test_a_deterministic_negative_stops_before_qualifying_a_reader(monkeypatch, kw):
    """The whole economics of a wide scan: the negative needs no reader, so no
    reader is paid for."""
    calls = stub(monkeypatch, gate=GateVerdict.WRONG_SCRIPT)
    steps, result = drain(L.ladder_steps(**kw))
    kinds = [s.kind for s in steps]
    assert "qualification" not in kinds
    assert kinds[-1] == "deterministic-negative"
    assert calls["judge"] == 0
    assert result.calls["judge"] == 0


def test_an_unqualified_reader_stops_before_any_judge_call(monkeypatch, kw):
    calls = stub(monkeypatch, trustworthy=False)
    steps, _ = drain(L.ladder_steps(**kw))
    assert [s.kind for s in steps][-1] == "unverified"
    assert calls["judge"] == 0


def test_steps_announce_what_comes_next_until_the_end(monkeypatch, kw):
    """Interactive mode shows the next step's description *before* spending the
    call that performs it, so the reader can decide whether to."""
    stub(monkeypatch)
    steps, _ = drain(L.ladder_steps(**kw))
    for s in steps[:-1]:
        assert s.as_dict()["next"], f"{s.kind} does not say what follows"
    assert steps[-1].as_dict()["next"] is None


def test_stopping_early_spends_nothing_further(monkeypatch, kw):
    """Every yield sits after the work it reports, so abandoning the generator
    cannot leave a call half-paid-for."""
    calls = stub(monkeypatch)
    gen = L.ladder_steps(**kw)
    next(gen)
    after_one = dict(calls)
    gen.close()
    assert calls == after_one


# -- how the session layer consumes it ---------------------------------------

def test_a_terminal_step_leaves_only_the_return_value(monkeypatch, kw):
    """The demo collects the verdict in the same request as the terminal step.
    That is only sound if nothing but the return remains after it -- otherwise
    the session would skip a step to get there."""
    stub(monkeypatch)
    gen = L.ladder_steps(**kw)
    seen = []
    while True:
        step = next(gen)
        seen.append(step)
        if step.terminal:
            break
    with pytest.raises(StopIteration) as stop:
        next(gen)
    assert stop.value.value is not None, "the return value must follow the terminal step"


# -- how a step reads at a glance --------------------------------------------

def test_every_step_carries_a_tone(monkeypatch, kw):
    stub(monkeypatch)
    steps, _ = drain(L.ladder_steps(**kw))
    assert all(s.tone in ("ok", "warn", "bad") for s in steps), \
        [(s.kind, s.tone) for s in steps if s.tone not in ("ok", "warn", "bad")]


def test_a_void_gate_verdict_is_not_coloured_like_a_failure():
    """Memorised text, too-short output and a weak language-ID call are neither
    a pass nor evidence against the model -- the arithmetic drops them from the
    denominator, and the colour has to say the same thing (protocol 018)."""
    for verdict in L.VOID:
        assert L.gate_tone(verdict) == "warn", verdict
    assert L.gate_tone(GateVerdict.PASS) == "ok"
    for verdict in (GateVerdict.WRONG_SCRIPT, GateVerdict.WRONG_LANGUAGE,
                    GateVerdict.REFUSED, GateVerdict.COPY):
        assert L.gate_tone(verdict) == "bad", verdict


def test_an_unverifiable_stop_is_not_red(monkeypatch, kw):
    """No reader could be qualified. That is a statement about the instrument,
    and colouring it like a model failure is the error protocol 005 exists to
    prevent -- in a colour instead of a word."""
    stub(monkeypatch, trustworthy=False)
    steps, _ = drain(L.ladder_steps(**kw))
    stop = steps[-1]
    assert stop.kind == "unverified" and stop.tone == "warn"


def test_a_deterministic_negative_is_red(monkeypatch, kw):
    stub(monkeypatch, gate=GateVerdict.WRONG_SCRIPT)
    steps, _ = drain(L.ladder_steps(**kw))
    assert steps[-1].kind == "deterministic-negative" and steps[-1].tone == "bad"


@pytest.mark.parametrize("recall,expected", [(1.0, "ok"), (0.5, "warn")])
def test_the_verdict_colour_follows_the_tier(monkeypatch, kw, recall, expected):
    stub(monkeypatch, recall=recall)
    steps, result = drain(L.ladder_steps(**kw))
    scored = [s for s in steps if s.kind == "scored"][-1]
    assert scored.tone == expected
    assert (result.score.tier.value == "Proficient") == (expected == "ok")
