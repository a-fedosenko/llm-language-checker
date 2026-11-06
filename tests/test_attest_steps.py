"""The battery has one traversal, and two ways to consume it.

`run_attestation` drains the generator; the bench advances it a step at a time.
The property that matters is that those cannot disagree — a second walk would
drift, and convention 9 records what that costs: an analysis harness
re-implemented a production call, got it subtly wrong, and 68 bad verdicts
reached a protocol's conclusions.

Modelled on `test_ladder_steps.py`, which pins the same property for the ladder.
"""
import pytest

from llmlc.probe import dialect as D
from llmlc.probe.attest import INDISTINGUISHABLE, Identification, Separation
from llmlc.probe.panel import CapabilityRecord, Role
from llmlc.probe.variant import DialectVerdict as V
from llmlc.scheme import load_scheme

RS = "Дете је нашло изгубљеног пса поред реке данас."
ME = "Дијете је нашло изгубљеног пса поред ријеке данас."


class NullCorpus:
    def write(self, record):
        return record


def stub(monkeypatch, *, produce=True, converts=True, consistent=True,
         controls_pass=True, identifies=True, separates=True):
    """Replace every paid primitive with a deterministic one.

    The control flow is what the stepping refactor has to preserve, so that is
    what is pinned here; the primitives have their own tests.
    """
    calls = {"produce": 0, "convert": 0, "identify": 0, "separate": 0}

    def fake_produce(*, client, engine, lang, designator, scenario, corpus,
                     relatives, accept, abstain=None):
        calls["produce"] += 1
        if not produce:
            return D.Produced(None, "wrong_language", "wrong_language")
        return D.Produced(ME if lang.region == "ME" else RS, "pass")

    def fake_convert(*, client, engine, lang, text, designator, corpus, relatives,
                     accept, abstain=None, max_tokens=600):
        calls["convert"] += 1
        if not converts:
            return D.Conversion(designator, text, text, edits=[], rate=0.0)
        edits = ([("дете", "дијете")] if consistent or calls["convert"] == 1
                 else [("реке", "ријеке")])
        return D.Conversion(designator, text, ME, edits=edits, rate=0.3)

    def fake_separate(client, model, *, first, second, blind, present=None,
                      max_tokens=600):
        calls["separate"] += 1
        if not controls_pass:
            # Splits a text from itself: fails the identity control.
            return Separation("Serbia", "Montenegro", swapped=False)
        if first == second:                      # the identity control
            return Separation(INDISTINGUISHABLE, INDISTINGUISHABLE)
        swap = bool(present)
        label = {RS: "Serbia", ME: "Montenegro"}
        a, b = (second, first) if swap else (first, second)
        if not separates:
            return Separation(INDISTINGUISHABLE, INDISTINGUISHABLE, swapped=swap)
        return Separation(label.get(a, "Serbia"), label.get(b, "Montenegro"),
                          swapped=swap)

    def fake_identify(client, model, *, text, blind, max_tokens=500):
        calls["identify"] += 1
        if not identifies:
            return Identification("Serbia")
        return Identification("Montenegro" if text == ME else "Serbia")

    monkeypatch.setattr(D, "_produce", fake_produce)
    monkeypatch.setattr(D, "convert", fake_convert)
    monkeypatch.setattr(D.attest, "separate", fake_separate)
    monkeypatch.setattr(D.attest, "identify", fake_identify)
    return calls


@pytest.fixture
def kw():
    scheme = load_scheme("catmint")
    # Two *named* varieties: the umbrella `sr` is the conversion source and is
    # passed separately, because it is not a variety anyone could be asked to
    # tell apart from a variety.
    varieties = [scheme.get("sr-rs-cyrl"), scheme.get("sr-me-cyrl")]
    return dict(scheme=scheme, tag="sr-me-cyrl", engine="alpha-pro",
                client=object(), attestors=["beta-one", "gamma-two"],
                varieties=varieties, neutral_tag="sr",
                scenario="A woman missed the morning bus.", corpus=NullCorpus())


def drain(gen):
    steps = []
    while True:
        try:
            steps.append(next(gen))
        except StopIteration as done:
            return steps, done.value


# -- the invariant -----------------------------------------------------------

@pytest.mark.parametrize("case", [
    {},                                        # everything works
    {"converts": False},                       # conversion is a no-op
    {"consistent": False},                     # improvised conversions
    {"controls_pass": False},                  # no attestor qualifies
    {"identifies": False},                     # named the wrong variety
    {"separates": False},                      # attestors merge the pair
    {"produce": False},                        # nothing usable was written
])
def test_draining_and_stepping_reach_the_same_result(monkeypatch, kw, case):
    stub(monkeypatch, **case)
    drained = D.run_attestation(**kw)
    stub(monkeypatch, **case)
    _, stepped = drain(D.attest_steps(**kw))

    assert drained.as_dict() == stepped.as_dict()


@pytest.mark.parametrize("case", [{}, {"controls_pass": False}, {"produce": False}])
def test_stepping_spends_exactly_what_draining_spends(monkeypatch, kw, case):
    a = stub(monkeypatch, **case)
    D.run_attestation(**kw)
    b = stub(monkeypatch, **case)
    drain(D.attest_steps(**kw))
    assert a == b


def test_stopping_early_spends_nothing_further(monkeypatch, kw):
    """Every yield sits after the work it reports, so abandoning the generator
    cannot leave a call half-paid-for."""
    calls = stub(monkeypatch)
    gen = D.attest_steps(**kw)
    next(gen)
    after_one = dict(calls)
    gen.close()
    assert calls == after_one


# -- the steps themselves ----------------------------------------------------

def test_every_step_is_json_ready_and_described(monkeypatch, kw):
    import json

    stub(monkeypatch)
    steps, _ = drain(D.attest_steps(**kw))
    assert steps
    for s in steps:
        d = s.as_dict()
        json.dumps(d)
        assert d["title"] and d["explains"], f"{s.kind} has no description"
        assert d["kind"] in D.ATTEST_HELP


def test_exactly_one_terminal_step_and_it_is_last(monkeypatch, kw):
    stub(monkeypatch)
    steps, _ = drain(D.attest_steps(**kw))
    assert [i for i, s in enumerate(steps) if s.terminal] == [len(steps) - 1]


def test_the_plan_comes_before_anything_is_spent(monkeypatch, kw):
    """A reader must be able to see what will be asked, and of whom, while the
    cost is still zero."""
    calls = stub(monkeypatch)
    gen = D.attest_steps(**kw)
    first = next(gen)
    assert first.kind == "plan"
    assert calls == {"produce": 0, "convert": 0, "identify": 0, "separate": 0}
    gen.close()


def test_the_free_half_runs_before_any_attestor_is_paid(monkeypatch, kw):
    """P3 and P4 need no panel, so they come first: a conversion that moved
    nothing is a negative settled locally, and the ordering is what makes the
    cheap evidence cheap."""
    stub(monkeypatch)
    kinds = [s.kind for s in drain(D.attest_steps(**kw))[0]]
    assert kinds.index("consistency") < kinds.index("controls")


def test_no_qualified_attestor_stops_before_any_attestation_call(monkeypatch, kw):
    """The economics, and the honesty: nothing is attested, so nothing is paid
    for, and the verdict says the instrument failed rather than the model."""
    calls = stub(monkeypatch, controls_pass=False)
    steps, result = drain(D.attest_steps(**kw))
    kinds = [s.kind for s in steps]
    assert "identified" not in kinds and "separated" not in kinds
    assert calls["identify"] == 0
    assert result.verdict is V.INDETERMINATE


def test_a_failed_production_half_does_not_convict_discrimination(monkeypatch, kw):
    """No usable pair means no attestor could be qualified. That is a gap in
    production, and the note has to say so rather than leaving a bare
    `indeterminate` to be read as a dialect failure."""
    stub(monkeypatch, produce=False)
    steps, result = drain(D.attest_steps(**kw))
    assert result.verdict is V.INDETERMINATE
    assert "gap in the production half" in " ".join(result.notes)
    assert steps[-1].terminal


def test_steps_announce_what_comes_next_until_the_end(monkeypatch, kw):
    stub(monkeypatch)
    steps, _ = drain(D.attest_steps(**kw))
    for s in steps[:-1]:
        assert s.as_dict()["next"], f"{s.kind} does not say what follows"
    assert steps[-1].as_dict()["next"] is None


# -- routing, which the bench must be able to see and override ---------------

def test_the_plan_shows_who_was_dropped_by_the_family_guard(monkeypatch, kw):
    """Invisible machinery is the thing auditability was supposed to buy us."""
    stub(monkeypatch)
    kw = {**kw, "attestors": ["alpha-other", "beta-one"]}
    first = next(D.attest_steps(**kw))
    assert first.detail["dropped_by_family_guard"] == ["alpha-other"]
    assert first.detail["attestors"] == ["beta-one"]


def test_the_plan_says_why_the_attestors_are_in_that_order(monkeypatch, kw):
    stub(monkeypatch)
    rec = CapabilityRecord()
    first = next(D.attest_steps(**{**kw, "record": rec}))
    assert "no priors" in first.detail["routing"]


def test_a_prior_record_reorders_and_says_so(monkeypatch, kw):
    from llmlc.probe.panel import Capability, CapabilityKey

    stub(monkeypatch)
    scheme = kw["scheme"]
    rec = CapabilityRecord([Capability(
        CapabilityKey("gamma-two", "sr-me-cyrl", Role.DISCRIMINATION,
                      scheme.get("sr-me-cyrl").script), True)])
    first = next(D.attest_steps(**{**kw, "record": rec}))
    assert first.detail["attestors"][0] == "gamma-two"
    assert "prior record" in first.detail["routing"]


def test_a_human_can_force_the_panel(monkeypatch, kw):
    """The bench override. A reader who distrusts the routing has to be able to
    re-derive a verdict by hand, or the record is machinery nobody can audit."""
    stub(monkeypatch)
    first = next(D.attest_steps(**{**kw, "forced_attestors": ["gamma-two"]}))
    assert first.detail["attestors"] == ["gamma-two"]
    assert first.detail["routing"] == "forced by hand"


def test_forcing_the_panel_does_not_buy_past_the_family_guard(monkeypatch, kw):
    """Naming the panel by hand is a preference. Not grading your own output is
    a rule (protocol 005), and a rule is not a setting."""
    stub(monkeypatch)
    first = next(D.attest_steps(**{**kw, "forced_attestors": ["alpha-sibling",
                                                              "gamma-two"]}))
    assert first.detail["attestors"] == ["gamma-two"]


def test_a_run_writes_its_findings_into_the_record(monkeypatch, kw):
    """Scanning one engine measures the panel as a byproduct, which is what
    makes later scans cheaper."""
    stub(monkeypatch)
    rec = CapabilityRecord()
    drain(D.attest_steps(**{**kw, "record": rec}))
    known = rec.known(["beta-one", "gamma-two"], tag="sr-me-cyrl",
                      role=Role.DISCRIMINATION,
                      script=kw["scheme"].get("sr-me-cyrl").script)
    assert known == {"beta-one": True, "gamma-two": True}


def test_the_designator_comes_from_the_ladder_not_a_second_opinion(kw):
    """Convention 9: two call sites deriving one prompt independently is how an
    analysis path comes to describe a run that is not the one that happened."""
    from llmlc.probe.ladder import candidates_for

    scheme = kw["scheme"]
    lang = scheme.get("sr-me-cyrl")
    assert D._designator_for(scheme, lang) == candidates_for(scheme, lang)[0].value


def test_the_umbrella_tag_is_not_a_contrast_arm(kw):
    """Its job is to be the conversion *source*. Pairing it against a variety
    leaves one answerable option, which is not a question -- and it is the wrong
    question anyway: "Serbian" and "Serbian (Montenegro)" are not two varieties
    a speaker could be asked to tell apart.

    Caught by a ValueError from `Blind` on the first run of the battery, which
    is the right place for it: an option set with one entry is not a thing to
    degrade gracefully about.
    """
    scheme = kw["scheme"]
    bad = {**kw, "varieties": [scheme.get("sr"), scheme.get("sr-me-cyrl")]}
    with pytest.raises(ValueError, match="two named varieties"):
        next(D.attest_steps(**bad))


def test_the_contrast_pair_is_two_named_varieties(monkeypatch, kw):
    """Not neutral-against-variety. The sibling is the other arm."""
    stub(monkeypatch)
    steps, result = drain(D.attest_steps(**kw))
    sep = next(s for s in steps if s.kind == "separated")
    assert sep.detail["expected"] == ["Serbia", "Montenegro"]
    assert result.contrasts and result.contrasts[0].correct
