"""Attestor controls, the panel guard, and how votes are counted.

The controls are the part that decides whether any of this is evidence. Each
test here names the failure it catches, because a control that passes everything
is worse than no control: it launders an unreliable attestor into a confident
verdict.
"""
import pytest

from llmlc.client.openai_compat import Completion
from llmlc.probe.attest import INDISTINGUISHABLE, UNSUPPORTED, Blind
from llmlc.probe.panel import (Competence, Consensus, ControlKind, ControlResult,
                               Panel, Role, Vote, eligible, identity_control,
                               order_by_record, order_control, qualify_attestor)

SR = Blind(language="Serbian", options=("Serbia", "Montenegro"))

RS = "Дете је нашло изгубљеног пса поред реке данас."
ME = "Дијете је нашло изгубљеног пса поред ријеке данас."


class NullCorpus:
    def write(self, record):
        return record


class Scripted:
    """Replies in order, so a two-call control can be given two answers."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def complete(self, model, prompt, *, max_tokens=400, temperature=0.0, system=None):
        self.calls.append({"user": prompt, "system": system})
        r = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        return Completion(r, None) if isinstance(r, str) else Completion(None, r[1])


def ctl(**kw):
    return dict(blind=SR, tag="sr", corpus=NullCorpus(), **kw)


# -- the identity control ----------------------------------------------------

def test_splitting_a_text_from_itself_fails_the_identity_control():
    """The failure it exists for: an attestor manufacturing a difference where
    there cannot be one. Its answer about a real pair is then worthless, and
    nothing in that answer would have said so."""
    c = Scripted('{"a": "Serbia", "b": "Montenegro"}')
    r = identity_control(c, "att", text=ME, **ctl())
    assert not r.passed and "two copies of one text" in r.detail


def test_calling_two_copies_indistinguishable_passes():
    c = Scripted(f'{{"a": "{INDISTINGUISHABLE}", "b": "{INDISTINGUISHABLE}"}}')
    assert identity_control(c, "att", text=ME, **ctl()).passed


def test_naming_one_variety_for_both_copies_also_passes():
    """It did not split. Whether the variety it named is right is a different
    question, and not one two copies of a text can answer."""
    c = Scripted('{"a": "Montenegro", "b": "Montenegro"}')
    assert identity_control(c, "att", text=ME, **ctl()).passed


def test_an_attestor_that_cannot_answer_does_not_pass_by_default():
    """A control that treats "no usable answer" as a pass admits exactly the
    attestors it was built to exclude."""
    c = Scripted("not json at all")
    r = identity_control(c, "att", text=ME, **ctl())
    assert not r.passed and "no usable answer" in r.detail


def test_the_identity_control_looks_like_an_ordinary_pair():
    """Nothing about the construction may be visible, or an attestor could pass
    it by recognising it rather than by being reliable."""
    c = Scripted(f'{{"a": "{INDISTINGUISHABLE}", "b": "{INDISTINGUISHABLE}"}}')
    identity_control(c, "att", text=ME, **ctl())
    sent = f"{c.calls[0]['system']}\n{c.calls[0]['user']}"
    for leak in ("identity", "control", "the same text", "twice"):
        assert leak not in sent.lower()


# -- the order control -------------------------------------------------------

def test_answering_by_position_fails_the_order_control():
    """The failure that would read as dialect knowledge. An attestor naming the
    options in the order they were listed scores every real pair correct by
    habit, and no single answer reveals it."""
    c = Scripted('{"a": "Serbia", "b": "Montenegro"}',
                 '{"a": "Serbia", "b": "Montenegro"}')
    r = order_control(c, "att", first=RS, second=ME, **ctl())
    assert not r.passed and "followed the position" in r.detail


def _perfect(seen):
    """An attestor that names the variety of whichever text it was shown."""
    import llmlc.probe.attest as A

    label = {RS: "Serbia", ME: "Montenegro"}

    def fake(client, model, *, first, second, blind, present=None, max_tokens=600):
        swap = A._coin(first + second) if present is None else present
        a, b = (second, first) if swap else (first, second)
        seen.append((a, b))
        return A.Separation(label[a], label[b], swapped=swap)

    return fake


def test_an_answer_that_follows_the_text_passes(monkeypatch):
    import llmlc.probe.attest as A

    seen = []
    monkeypatch.setattr(A, "separate", _perfect(seen))
    r = order_control(None, "att", first=RS, second=ME, **ctl())
    assert r.passed
    assert seen[0] != seen[1], "the two calls must see opposite presentations"


def test_the_two_presentations_are_forced_rather_than_salted(monkeypatch):
    """The flaw this control shipped with for about an hour. Obtaining the two
    orders by swapping the arguments re-salts the presentation coin, and when
    the two coins agree the attestor sees the same order twice -- measured at
    1,014 of 2,000 pairs. The control then degenerates into a repeat test and
    passes a position-answering attestor for exactly the half of cases it
    exists to catch. So it must hold for *every* pair, not for lucky ones."""
    import llmlc.probe.attest as A

    for i in range(60):
        first, second = f"alpha {i} " + "x" * 30, f"beta {i} " + "y" * 30
        seen = []

        def fake(client, model, *, first, second, blind, present=None, max_tokens=600):
            swap = A._coin(first + second) if present is None else present
            seen.append((second, first) if swap else (first, second))
            return A.Separation("Serbia", "Montenegro", swapped=swap)

        monkeypatch.setattr(A, "separate", fake)
        order_control(None, "att", first=first, second=second, **ctl())
        assert seen[0] != seen[1], f"pair {i} was shown in one order twice"


def test_a_position_answerer_fails_for_every_pair(monkeypatch):
    """The other half of the same point: the control must catch it regardless of
    how the texts happen to salt."""
    import llmlc.probe.attest as A

    def fake(client, model, *, first, second, blind, present=None, max_tokens=600):
        swap = A._coin(first + second) if present is None else present
        # Answers the slots, never the text.
        return A.Separation("Serbia", "Montenegro", swapped=swap)

    monkeypatch.setattr(A, "separate", fake)
    for i in range(60):
        r = order_control(None, "att", first=f"a{i}" + "x" * 30,
                          second=f"b{i}" + "y" * 30, **ctl())
        assert not r.passed, f"pair {i} let a position-answerer through"


def test_merging_both_times_is_consistent_and_passes():
    """This control tests consistency, not confidence. An attestor that sees no
    difference both times is reliable about what it sees; whether a difference
    exists is the probe's question, not the control's."""
    c = Scripted(f'{{"a": "{INDISTINGUISHABLE}", "b": "{INDISTINGUISHABLE}"}}',
                 f'{{"a": "{INDISTINGUISHABLE}", "b": "{INDISTINGUISHABLE}"}}')
    assert order_control(c, "att", first=RS, second=ME, **ctl()).passed


def test_declining_both_times_is_consistent_and_passes():
    c = Scripted(f'{{"a": "{UNSUPPORTED}", "b": "{UNSUPPORTED}"}}',
                 f'{{"a": "{UNSUPPORTED}", "b": "{UNSUPPORTED}"}}')
    assert order_control(c, "att", first=RS, second=ME, **ctl()).passed


# -- qualification as a whole ------------------------------------------------

def test_every_control_must_pass_not_a_majority():
    """Each tests a different way of being wrong, so failing either is
    disqualifying on its own. A majority rule over two controls is one control."""
    c = Competence("att", "Serbian", controls=[
        ControlResult(ControlKind.IDENTITY, True),
        ControlResult(ControlKind.ORDER, False)])
    assert not c.qualified and c.failed == ["order"]


def test_an_attestor_with_no_controls_run_is_not_qualified():
    """Absence of evidence is not qualification. An empty control list would
    otherwise satisfy `all()` and admit everyone."""
    assert not Competence("att", "Serbian").qualified


def test_qualifying_an_attestor_runs_both_controls():
    c = Scripted(f'{{"a": "{INDISTINGUISHABLE}", "b": "{INDISTINGUISHABLE}"}}')
    out = qualify_attestor(c, "att", family="Serbian", blind=SR, neutral=ME,
                           first=RS, second=ME, tag="sr", corpus=NullCorpus())
    assert {r.kind for r in out.controls} == {ControlKind.IDENTITY, ControlKind.ORDER}
    assert out.qualified


# -- the family guard --------------------------------------------------------

def test_a_producer_is_never_shown_its_own_output():
    assert eligible(["a-one", "b-two"], producer="a-one") == ["b-two"]


def test_the_guard_cuts_at_the_family_not_the_id():
    """Two ids from one vendor are near enough to the same reader that grading
    one with the other measures self-consistency (protocol 005, S8)."""
    assert eligible(["gemini-x", "gemini-y", "deepseek-z"],
                    producer="gemini-x") == ["deepseek-z"]


def test_a_panel_emptied_by_the_guard_is_empty_rather_than_relaxed():
    assert eligible(["gemini-x", "gemini-y"], producer="gemini-z") == []


# -- routing by the record ---------------------------------------------------

def test_known_qualified_attestors_are_asked_first():
    out = order_by_record(["a", "b", "c"], known={"c": True})
    assert out[0] == "c"


def test_an_attestor_recorded_as_failing_is_still_tried():
    """The record is a cache of a past measurement and models change under a
    fixed id. Dropping it would freeze an error permanently."""
    out = order_by_record(["a", "b"], known={"a": False})
    assert set(out) == {"a", "b"} and out[-1] == "a"


def test_an_empty_record_changes_nothing():
    """Early in a scan there are no priors, which is why the first engine
    scanned is the expensive one."""
    assert order_by_record(["a", "b", "c"]) == ["a", "b", "c"]


def test_routing_never_removes_an_attestor():
    """It reorders and nothing else -- every attestor returned still faces the
    controls. A record that could exclude would be vouching, not routing."""
    attestors = ["a", "b", "c"]
    out = order_by_record(attestors, known={"a": False, "b": True, "c": False})
    assert sorted(out) == sorted(attestors)


# -- what a panel concluded --------------------------------------------------

def q(name, ok=True):
    return Competence(name, "Serbian", controls=[ControlResult(ControlKind.IDENTITY, ok)])


def test_a_panel_with_no_qualified_member_is_empty_not_negative():
    """`indeterminate` is a result. "Nobody could check" is not "the model
    cannot do it", and reporting it as the second is protocol 005's error."""
    p = Panel([q("a", ok=False)])
    assert p.empty and p.qualified == [] and p.disqualified == ["a"]


def test_a_single_qualified_member_is_flagged_as_such():
    """Usable, but stamped lower-confidence rather than silently promoted to a
    panel result."""
    p = Panel([q("a"), q("b", ok=False)])
    assert p.single and not p.empty


def test_disagreement_is_reported_as_disagreement_not_averaged():
    """A mean over three judges splitting two-to-one reports 0.67 and hides that
    one of them read the text completely differently -- which is the finding."""
    c = Consensus([Vote("a", True), Vote("b", True), Vote("c", False)])
    assert c.agreed is None and c.split


def test_unanimous_agreement_in_either_direction_is_settled():
    assert Consensus([Vote("a", True), Vote("b", True)]).agreed is True
    assert Consensus([Vote("a", False), Vote("b", False)]).agreed is False


def test_an_abstention_is_not_a_wrong_answer():
    """An attestor saying "generic" has answered honestly about the text.
    Counting it as wrong convicts the model for the attestor's candour."""
    c = Consensus([Vote("a", True), Vote("b", False, abstained=True)])
    assert c.agreed is True and len(c.counted) == 1


def test_a_panel_that_only_abstained_has_concluded_nothing():
    c = Consensus([Vote("a", False, abstained=True)])
    assert c.agreed is None and not c.split


def test_one_vote_cannot_be_split():
    assert not Consensus([Vote("a", True)]).split


# -- the three roles ---------------------------------------------------------

def test_the_three_roles_are_distinct_values():
    """They dissociate: a model can spot ijekavian and still mistranslate it.
    One score over all three would hide which."""
    assert len({Role.GENERATION, Role.DISCRIMINATION, Role.COMPREHENSION}) == 3


# -- the capability record: a cache, never an authority ----------------------

from llmlc.probe.panel import (Capability, CapabilityKey, CapabilityRecord,
                               capabilities_from)


def cap(model, tag, qualified, role=Role.DISCRIMINATION):
    return Capability(CapabilityKey(model, tag, role), qualified)


def test_the_record_offers_no_way_to_skip_a_control():
    """The invariant the whole design rests on, made structural. The moment a
    method returned "this attestor is trustworthy, skip its controls", someone
    would call it, and a wrongly-recorded attestor would become permanently
    self-confirming -- the record would have become the stale stored claim it
    replaced."""
    api = {n for n in dir(CapabilityRecord) if not n.startswith("_")}
    assert api == {"put", "get", "known", "rows"}
    for banned in ("trustworthy", "qualified", "vouch", "skip", "is_ok"):
        assert banned not in api


def test_the_record_is_consulted_for_order_and_nothing_else():
    """End to end: a stored negative changes the order and not the membership."""
    r = CapabilityRecord([cap("b", "sr-me-cyrl", True), cap("a", "sr-me-cyrl", False)])
    known = r.known(["a", "b", "c"], tag="sr-me-cyrl", role=Role.DISCRIMINATION)
    out = order_by_record(["a", "b", "c"], known=known)
    assert out[0] == "b" and sorted(out) == ["a", "b", "c"]


def test_never_measured_outranks_measured_and_failed():
    """Different states, ordered differently. An untried attestor is worth more
    of a chance than one that failed, and both are still tried."""
    r = CapabilityRecord([cap("a", "sr", False)])
    out = order_by_record(["a", "b"], known=r.known(["a", "b"], tag="sr",
                                                    role=Role.DISCRIMINATION))
    assert out == ["b", "a"]


def test_a_claim_is_about_one_role_only():
    """The three dissociate, so a record qualified for discrimination says
    nothing about generation and must not be read across."""
    r = CapabilityRecord([cap("a", "sr", True, role=Role.DISCRIMINATION)])
    assert r.known(["a"], tag="sr", role=Role.DISCRIMINATION) == {"a": True}
    assert r.known(["a"], tag="sr", role=Role.GENERATION) == {}


def test_a_claim_is_about_one_tag_only():
    """Judge competence is per dialect, not per model: a strong engine can be a
    weak attestor for one variety."""
    r = CapabilityRecord([cap("a", "sr-me-cyrl", True)])
    assert r.known(["a"], tag="pt-br", role=Role.DISCRIMINATION) == {}


def test_the_key_carries_the_model_id_and_the_record_carries_the_date():
    """Vendor endpoints change silently under a fixed id, so the id is the whole
    identity and `measured_at` is what carries the age. The honest reading is
    "this was true of whatever answered to that id on that date"."""
    c = Capability(CapabilityKey("m", "sr", Role.GENERATION), True, measured_at=1.0)
    assert c.as_dict()["model"] == "m" and c.as_dict()["measured_at"] == 1.0


def test_negatives_are_recorded_as_well_as_positives():
    """Recording only successes makes the record look like a list of models that
    work, while silently dropping the evidence that the others do not."""
    panel = Panel([q("a"), q("b", ok=False)])
    rows = capabilities_from(panel, tag="sr-me-cyrl", role=Role.DISCRIMINATION)
    assert {r.key.model: r.qualified for r in rows} == {"a": True, "b": False}
    assert "failed: identity" in next(r for r in rows if r.key.model == "b").detail


def test_scanning_one_engine_measures_the_others_as_a_byproduct():
    """Why a five-family battery is affordable: the first engine scanned is the
    expensive one, and each later scan starts with priors."""
    panel = Panel([q("gemini-x"), q("gpt-y"), q("groq-z", ok=False)])
    rec = CapabilityRecord(capabilities_from(panel, tag="pt-br", role=Role.DISCRIMINATION))
    known = rec.known(["gemini-x", "gpt-y", "groq-z"], tag="pt-br",
                      role=Role.DISCRIMINATION)
    assert known == {"gemini-x": True, "gpt-y": True, "groq-z": False}
