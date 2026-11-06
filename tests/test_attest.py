"""Attestation primitives: blinding, grounding, and the two escapes.

The tests that matter most here are the ones about what an attestor is *not*
shown. A leak would not look like a failure -- it would look like an excellent
result, which is the shape of defect this project keeps finding (012's contexts
naming their own markers, 018's harness re-implementing a production call).
"""
import pytest

from llmlc.probe.attest import (GENERIC, UNSUPPORTED, Blind, Identification,
                                ground, identify, shuffled)


class FakeClient:
    """Records exactly what was sent, so a test can assert on the prompt."""

    def __init__(self, reply: str = '{"answer": "Serbia", "markers": []}'):
        self.reply, self.calls = reply, []

    def complete(self, model, prompt, *, max_tokens=400, temperature=0.0, system=None):
        from llmlc.client.openai_compat import Completion
        self.calls.append({"model": model, "user": prompt, "system": system})
        return Completion(self.reply, None)

    @property
    def sent(self) -> str:
        """Everything the model was shown, both halves."""
        c = self.calls[-1]
        return f"{c['system']}\n{c['user']}"


SR = Blind(language="Serbian", options=("Serbia", "Montenegro"),
           script_name="Cyrillic")


# -- blinding ----------------------------------------------------------------

def test_the_expected_answer_is_not_a_parameter_of_identify():
    """The blinding mechanism, stated as a test. If a later change adds an
    `expect` argument, this fails and someone has to justify it in review --
    which is the point, because a prompt leak is invisible in the output.
    """
    import inspect

    params = set(inspect.signature(identify).parameters)
    for forbidden in ("expect", "expected", "tag", "lang", "answer", "truth"):
        assert forbidden not in params


def test_blind_carries_no_tag_region_or_full_form():
    """`Blind` exists instead of passing a `Language` because a `Language` holds
    three fields that each name the answer."""
    assert not hasattr(SR, "tag")
    assert not hasattr(SR, "region_name")
    assert not hasattr(SR, "full")


def test_the_prompt_depends_only_on_the_text_and_the_blind():
    """The invariant behind the blinding, tested as an invariant rather than by
    sniffing for suspicious strings.

    Two texts that are genuinely different varieties, asked under the same
    `Blind`, differ in the prompt *only* where the text itself appears. If
    anything about the expected answer ever reached the prompt, these two would
    differ somewhere else as well.
    """
    me, rs = "Дијете је нашло пса.", "Дете је нашло пса."
    a, b = FakeClient(), FakeClient()
    identify(a, "attestor", text=me, blind=SR)
    identify(b, "attestor", text=rs, blind=SR)

    assert a.calls[-1]["system"] == b.calls[-1]["system"]
    assert a.calls[-1]["user"].replace(me, "") == b.calls[-1]["user"].replace(rs, "")


def test_the_prompt_offers_both_options_and_marks_neither():
    client = FakeClient()
    identify(client, "attestor", text="Дијете је нашло пса.", blind=SR)
    sent = client.sent
    assert "Serbia" in sent and "Montenegro" in sent
    # No tag spelling, which is the form the answer would most plausibly leak in.
    for leak in ("sr-me", "sr-rs", "sr-cyrl"):
        assert leak not in sent.lower()


def test_an_option_list_with_one_entry_is_not_a_question():
    with pytest.raises(ValueError, match="not a question"):
        Blind(language="Serbian", options=("Montenegro",))


def test_duplicate_options_are_refused():
    with pytest.raises(ValueError, match="duplicate"):
        Blind(language="Spanish", options=("Mexico", "Mexico"))


# -- shuffling ---------------------------------------------------------------

def test_shuffling_is_stable_for_the_same_text():
    """A run has to be reproducible, and the bench must show what the batch run
    showed."""
    a = shuffled(["Serbia", "Montenegro", "Bosnia"], salt="some text")
    b = shuffled(["Serbia", "Montenegro", "Bosnia"], salt="some text")
    assert a == b


def test_shuffling_moves_the_options_between_texts():
    """Salted by the text so the answer does not sit in one position across a
    family's items: a model with a position bias would otherwise beat chance on
    ordering alone and read as dialect knowledge."""
    options = ["Serbia", "Montenegro", "Bosnia", "Kosovo"]
    orders = {shuffled(options, salt=f"text {i}") for i in range(25)}
    assert len(orders) > 1


def test_shuffling_keeps_every_option():
    options = ["a", "b", "c", "d"]
    assert sorted(shuffled(options, salt="x")) == options


# -- grounding ---------------------------------------------------------------

def test_a_marker_that_is_not_in_the_text_is_recorded_as_fabricated():
    """The failure a yes/no answer cannot catch: a confident verdict propped up
    by invented quotations."""
    text = "Дијете је нашло изгубљеног пса поред ријеке."
    ident = Identification("Montenegro", markers=[{"text": "дијете", "why": "ijekavian"},
                                                  {"text": "млијеко", "why": "invented"}])
    ground(ident, text)
    assert ident.fabricated == ["млијеко"]


def test_grounding_ignores_case_and_whitespace_runs():
    """A quotation is evidence; re-wrapping is not falsification."""
    ident = Identification("GB", markers=[{"text": "The  Boot", "why": ""}])
    ground(ident, "She opened the boot of the car.")
    assert ident.fabricated == []


def test_a_fully_grounded_identification_reports_nothing_fabricated():
    ident = Identification("GB", markers=[{"text": "petrol", "why": ""}])
    ground(ident, "He paid for the petrol.")
    assert ident.fabricated == []


def test_identify_grounds_its_own_result():
    """Grounding is not something a caller can forget to do."""
    client = FakeClient('{"answer": "Montenegro", '
                        '"markers": [{"text": "nije-there", "why": "x"}]}')
    out = identify(client, "a", text="Дијете је нашло пса.", blind=SR)
    assert out.fabricated == ["nije-there"]


# -- the two escapes ---------------------------------------------------------

def test_generic_is_an_available_answer_and_is_not_a_decision():
    """Three sentences of neutral prose frequently *is* generic, and saying so
    is the true answer rather than a non-answer (protocol 012: 25% void)."""
    client = FakeClient(f'{{"answer": "{GENERIC}", "markers": []}}')
    out = identify(client, "a", text="Човјек је дошао кући.", blind=SR)
    assert out.ok and out.generic and not out.decided and not out.declined


def test_unsupported_is_about_the_attestor_not_the_text():
    client = FakeClient(f'{{"answer": "{UNSUPPORTED}", "markers": []}}')
    out = identify(client, "a", text="x" * 40, blind=SR)
    assert out.declined and not out.generic and not out.decided


def test_both_escapes_are_offered_in_the_prompt():
    client = FakeClient()
    identify(client, "a", text="x" * 40, blind=SR)
    assert GENERIC in client.sent and UNSUPPORTED in client.sent


def test_naming_a_variety_is_the_only_thing_that_counts_as_decided():
    client = FakeClient('{"answer": "Montenegro", "markers": []}')
    out = identify(client, "a", text="Дијете је нашло пса.", blind=SR)
    assert out.decided and out.answer == "Montenegro"


# -- parsing -----------------------------------------------------------------

def test_an_answer_outside_the_option_set_is_an_error_not_a_verdict():
    """A model answering "Croatia" where that was not offered has not answered
    the question asked, and scoring it would invent a result."""
    client = FakeClient('{"answer": "Croatia", "markers": []}')
    out = identify(client, "a", text="x" * 40, blind=SR)
    assert not out.ok and "not one of the options" in out.error


def test_case_differences_in_the_answer_are_not_a_parse_failure():
    client = FakeClient('{"answer": "montenegro", "markers": []}')
    out = identify(client, "a", text="x" * 40, blind=SR)
    assert out.answer == "Montenegro"


def test_prose_around_the_json_is_tolerated():
    client = FakeClient('Here is my analysis:\n{"answer": "Serbia", "markers": []}\nDone.')
    out = identify(client, "a", text="x" * 40, blind=SR)
    assert out.answer == "Serbia"


def test_unparseable_output_is_an_error_and_keeps_the_raw_text():
    """Convention 6: the raw evidence is what defects are found in."""
    client = FakeClient("I think it's probably Montenegrin, honestly.")
    out = identify(client, "a", text="x" * 40, blind=SR)
    assert not out.ok and out.raw and "no JSON" in out.error


def test_a_bare_string_marker_list_is_still_evidence():
    """Tolerant about shape, strict about content: discarding a marker over
    punctuation throws away the thing that makes a verdict checkable."""
    client = FakeClient('{"answer": "Montenegro", "markers": ["дијете"]}')
    out = identify(client, "a", text="Дијете је нашло пса.", blind=SR)
    assert out.markers[0]["text"] == "дијете" and out.fabricated == []


def test_a_transport_error_is_not_a_verdict():
    class Broken:
        def complete(self, *a, **kw):
            from llmlc.client.openai_compat import Completion
            return Completion(None, "HTTP 500")

    out = identify(Broken(), "a", text="x" * 40, blind=SR)
    assert not out.ok and out.error == "HTTP 500"
