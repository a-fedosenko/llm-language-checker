"""Marker sets, comparative scoring, and the variant verdict.

All local: marker scoring is deterministic string matching by design, so none of
this needs a model. The false-positive cases are the point -- a marker that
matches the wrong word produces a plausible number with nothing to flag it.
"""
import json

import pytest

from llmlc.probe.markers import (MarkerSet, coverage, load_markers, score_text)
from llmlc.probe.variant import (PROVEN_AT, VariantEvidence, declared, default_script,
                                 from_script, is_script_variant, untested)
from llmlc.scheme import load_scheme


@pytest.fixture(scope="module")
def scheme():
    return load_scheme("default")


@pytest.fixture(scope="module")
def shipped():
    return load_markers()


def make(variant, sibling, axis="lexis") -> MarkerSet:
    return MarkerSet(status="markers", sibling="x", designator="X",
                     markers=[{"axis": axis, "variant": variant, "sibling": sibling}],
                     elicitation=["ctx"])


# -- scoring -----------------------------------------------------------------

def test_scoring_is_comparative_not_absolute():
    """Counting variant markers alone would reward verbosity."""
    m = make(["boot", "petrol"], ["trunk", "gas"])
    assert score_text("He put it in the boot and bought petrol.", m).rate == 1.0
    assert score_text("He put it in the trunk and bought gas.", m).rate == 0.0
    assert score_text("He put it in the boot and bought gas.", m).rate == 0.5


def test_an_item_with_neither_marker_is_void_not_zero():
    """The context failed to force the choice. That is our fault, not the model's."""
    out = score_text("The weather was fine and nothing happened.", make(["boot"], ["trunk"]))
    assert out.void
    assert out.rate is None, "a void item must not be scored as a miss"


def test_markers_match_on_word_boundaries():
    m = make(["boot"], ["trunk"])
    assert score_text("She rebooted the laptop.", m).void, "'boot' must not match 'rebooted'"
    assert not score_text("She opened the boot.", m).void


def test_multiword_markers_match():
    m = make(["in hospital"], ["in the hospital"])
    assert score_text("He spent a week in hospital.", m).rate == 1.0
    assert score_text("He spent a week in the hospital.", m).rate == 0.0


def test_suffix_markers_need_a_stem():
    """`-our` must not match the word 'our', or every text scores a free hit."""
    m = make(["-our"], ["-or"])
    assert score_text("This is our car.", m).void
    assert score_text("The colour was odd.", m).rate == 1.0


def test_case_is_ignored():
    assert score_text("BOOT", make(["boot"], ["trunk"])).rate == 1.0


def test_an_empty_generation_is_an_error_not_a_miss():
    out = score_text("", make(["boot"], ["trunk"]))
    assert out.error and out.rate is None


# -- authoring guards --------------------------------------------------------

def test_a_marker_on_both_sides_is_rejected_at_load_time():
    """Two real drafting mistakes: 'chips' (opposite meanings) and 'on the weekend'."""
    with pytest.raises(ValueError, match="both variant and sibling"):
        make(["chips", "boot"], ["chips", "trunk"])


def test_markers_status_requires_markers_and_contexts():
    with pytest.raises(ValueError, match="elicitation"):
        MarkerSet(status="markers", markers=[{"axis": "lexis", "variant": ["a"],
                                              "sibling": ["b"]}])


def test_not_distinguishable_must_say_why():
    """It is a linguistic claim; an unexplained one cannot be reviewed."""
    with pytest.raises(ValueError, match="note"):
        MarkerSet(status="not-distinguishable")


def test_a_tag_defined_twice_is_an_error(tmp_path):
    """Otherwise a marker list's meaning depends on filename order."""
    for name in ("a.json", "b.json"):
        (tmp_path / name).write_text(json.dumps(
            {"en-AU": {"status": "not-distinguishable", "note": "n"}}), encoding="utf-8")
    load_markers.cache_clear()
    with pytest.raises(ValueError, match="defined twice"):
        load_markers(str(tmp_path))
    load_markers.cache_clear()


# -- the shipped corpus ------------------------------------------------------

def test_shipped_markers_load_and_are_testable(shipped):
    assert shipped["en-AU"].testable and shipped["en-GB"].testable
    assert shipped["ru-BY"].status == "not-distinguishable"
    assert not shipped["ru-BY"].testable


def test_shipped_marker_sets_declare_whether_a_human_reviewed_them(shipped):
    """An unreviewed list must not pass for a reviewed one just by being in the repo."""
    assert all(hasattr(s, "reviewed") for s in shipped.values())
    assert all(s.source for s in shipped.values())


def test_shipped_english_markers_discriminate_real_sentences(shipped):
    au = shipped["en-AU"]
    british = "She put the bags in the boot, filled up with petrol, and realised the colour had faded."
    american = "She put the bags in the trunk, filled up with gas, and realized the color had faded."
    assert score_text(british, au).rate == 1.0
    assert score_text(american, au).rate == 0.0


def test_no_shipped_marker_fires_on_variant_neutral_prose(shipped):
    """The commonest silent failure: a marker matching text both variants share."""
    neutral = ("The meeting began at nine. Four of us were there, and our manager "
               "spoke for an hour about the budget before we returned to work.")
    for tag, ms in shipped.items():
        if ms.testable:
            out = score_text(neutral, ms)
            assert out.void, f"{tag} fired on neutral prose: {out.as_dict()}"


# -- variant verdicts --------------------------------------------------------

def test_a_marked_script_variant_is_told_apart_from_the_base_form(scheme):
    """`kk-Latn` is a variant claim; `kk` is a claim about the language."""
    assert is_script_variant(scheme, scheme.get("kk-Latn"))
    assert not is_script_variant(scheme, scheme.get("kk"))
    assert default_script(scheme, scheme.get("kk")) == "Cyrl"


def test_fringe_scripts_do_not_make_every_tag_a_script_variant(scheme):
    """German is in the catalogue with Fraktur, Braille, Duployan and Runic. That
    makes `de-Latf` a variant and leaves `de` and `de-AT` exactly what they were."""
    assert not is_script_variant(scheme, scheme.get("de"))
    assert not is_script_variant(scheme, scheme.get("de-AT"))
    assert is_script_variant(scheme, scheme.get("de-Latf"))


def test_country_variants_are_not_script_variants(scheme):
    """en-AU needs markers; no script check can answer it."""
    assert not is_script_variant(scheme, scheme.get("en-AU"))


class _Gate:
    def __init__(self, verdict, passed):
        from llmlc.probe.gate import GateVerdict
        self.verdict = GateVerdict(verdict)
        self.passed = passed


class _Item:
    def __init__(self, verdict, passed):
        self.gate = _Gate(verdict, passed)


class _Result:
    def __init__(self, tag, items):
        self.tag, self.items, self.designator = tag, items, "Kazakh (Latin script)"


def test_a_script_variant_is_proven_by_its_own_probe():
    """The gate already checked the script; the answer costs nothing extra."""
    v = from_script(_Result("kk-Latn", [_Item("pass", True)] * 3))
    assert v.evidence is VariantEvidence.PROVEN
    assert v.mechanism == "script" and v.s_variant == 1.0


def test_wrong_script_is_proven_failed_not_untested():
    """Asked for Latin Kazakh and given Cyrillic is the variant *not* being marked."""
    v = from_script(_Result("kk-Latn", [_Item("wrong_script", False)] * 3))
    assert v.evidence is VariantEvidence.PROVEN_FAILED
    assert v.s_variant == 0.0


def test_a_probe_that_never_reached_the_script_check_is_untested():
    v = from_script(_Result("kk-Latn", [_Item("too_short", False)] * 3))
    assert v.evidence is VariantEvidence.UNTESTED, "no evidence is not evidence of failure"


def test_declared_and_untested_are_different_states(shipped):
    a = declared("ru-BY", shipped["ru-BY"])
    b = untested("de-AT", "no markers yet")
    assert a.evidence is VariantEvidence.NOT_DISTINGUISHABLE
    assert b.evidence is VariantEvidence.UNTESTED
    assert a.note, "a finished decision must carry its reason"


def test_proven_threshold_is_a_clear_lean_not_a_bare_majority():
    assert PROVEN_AT > 0.5


# -- coverage ----------------------------------------------------------------

def test_coverage_counts_the_gap(scheme):
    c = coverage(scheme)
    assert c["variant_tags"] > 500
    assert c["markers"] >= 2 and c["not_distinguishable"] >= 1
    assert c["untested"] == c["variant_tags"] - c["markers"] - c["not_distinguishable"]


# -- the marker probe, with a scripted model ---------------------------------

class _FakeClient:
    """Scripted responses. Marker scoring must be testable without spending money."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def complete(self, model, prompt, **kw):
        from llmlc.client import Completion
        self.prompts.append(prompt)
        nxt = self.responses.pop(0) if self.responses else None
        return Completion(nxt, None if nxt is not None else "no response", model=model)


AU_TEXT = ("She loaded the bags into the boot and stopped for petrol on the way. "
           "The colour of the sky had changed and she realised it was getting late. "
           "The car park was three metres from the kerb.")
US_TEXT = ("She loaded the bags into the trunk and stopped for gas on the way. "
           "The color of the sky had changed and she realized it was getting late. "
           "The parking lot was three meters from the curb.")
NEUTRAL_TEXT = ("She loaded the bags into the vehicle and continued driving. "
                "The sky had changed and it was clearly getting late in the day. "
                "She parked and walked the short distance to the entrance.")


def _probe(scheme, shipped, responses, tag="en-AU", tmp_path=None):
    from llmlc.probe.corpus import Corpus
    from llmlc.probe.variant import from_markers
    client = _FakeClient(responses)
    with Corpus(tmp_path / "c.jsonl") as corpus:
        return from_markers(client=client, engine="m", lang=scheme.get(tag),
                            markers=shipped[tag], corpus=corpus, scheme=scheme), client


def test_a_variant_that_marks_itself_is_proven(scheme, shipped, tmp_path):
    v, _ = _probe(scheme, shipped, [AU_TEXT] * 3, tmp_path=tmp_path)
    assert v.evidence is VariantEvidence.PROVEN
    assert v.s_variant == 1.0
    assert v.calls == 3


def test_a_variant_that_writes_the_sibling_is_proven_failed(scheme, shipped, tmp_path):
    """Asked for Australian English, wrote American English. That is the finding."""
    v, _ = _probe(scheme, shipped, [US_TEXT] * 3, tmp_path=tmp_path)
    assert v.evidence is VariantEvidence.PROVEN_FAILED
    assert v.s_variant == 0.0


def test_all_void_items_mean_untested_not_failed(scheme, shipped, tmp_path):
    """Our contexts failed to force a choice. We learned nothing about the model,
    and reporting that as a failure would blame it for our bad prompts."""
    v, _ = _probe(scheme, shipped, [NEUTRAL_TEXT] * 3, tmp_path=tmp_path)
    assert v.evidence is VariantEvidence.UNTESTED
    assert v.s_variant is None
    assert v.voids == 3
    assert "contexts failed" in (v.note or "")


def test_void_items_are_excluded_rather_than_averaged_in(scheme, shipped, tmp_path):
    v, _ = _probe(scheme, shipped, [AU_TEXT, NEUTRAL_TEXT, AU_TEXT], tmp_path=tmp_path)
    assert v.s_variant == 1.0, "a void item must not drag the rate down"
    assert v.voids == 1


def test_the_markers_are_never_named_in_the_prompt(scheme, shipped, tmp_path):
    """Naming them would measure instruction-following, not competence (docs/01)."""
    _, client = _probe(scheme, shipped, [AU_TEXT] * 3, tmp_path=tmp_path)
    joined = " ".join(client.prompts).lower()
    for marker in ("boot", "petrol", "colour", "realise", "kerb"):
        assert marker not in joined, f"{marker!r} leaked into the prompt"


def test_the_designator_names_the_variant(scheme, shipped, tmp_path):
    _, client = _probe(scheme, shipped, [AU_TEXT] * 3, tmp_path=tmp_path)
    assert "Australian English" in client.prompts[0]


def test_a_refusal_is_not_scored_for_markers(scheme, shipped, tmp_path):
    """Wrong language entirely is a base-language failure, not a variant one."""
    v, _ = _probe(scheme, shipped, ["I cannot help with that."] * 3, tmp_path=tmp_path)
    assert v.evidence is VariantEvidence.UNTESTED
    assert all(i.error for i in v.items)


# -- defects found by running it (protocol 012) ------------------------------

def test_inflected_forms_match_their_base_marker():
    """`neighbour` must match "neighbours".

    Found live: a context that plainly elicited the choice scored void, because
    the model wrote the plural. Worse than a miss -- the sibling's singular
    happened to match "neighbor's", so the asymmetry moved the score rather than
    just lowering it.
    """
    m = make(["neighbour", "organise"], ["neighbor", "organize"], axis="orthography")
    assert score_text("She asked the neighbours about organising it.", m).rate == 1.0
    assert score_text("She asked the neighbors about organizing it.", m).rate == 0.0


def test_e_dropping_inflections_are_handled():
    """organise -> organising, queue -> queuing."""
    m = make(["organise", "queue"], ["organize", "line"])
    assert score_text("They were organising it.", m).rate == 1.0
    assert score_text("She was queuing outside.", m).rate == 1.0


def test_inflection_does_not_reach_across_a_word_boundary():
    m = make(["boot"], ["trunk"])
    assert score_text("She rebooted it.", m).void
    assert score_text("The bootloader failed.", m).void, "'boot'+3 letters is not 'bootloader'"


def test_an_elicitation_context_may_not_name_a_marker():
    """Found live: a context reading "...in autumn, walking to the underground
    station" named three en-GB markers, and the American arm scored by echoing it."""
    with pytest.raises(ValueError, match="names the markers"):
        MarkerSet(status="markers", designator="X",
                  markers=[{"axis": "lexis", "variant": ["autumn"], "sibling": ["fall"]}],
                  elicitation=["Describe a walk in autumn."])


def test_the_leak_check_also_catches_the_sibling_side():
    with pytest.raises(ValueError, match="names the markers"):
        MarkerSet(status="markers", designator="X",
                  markers=[{"axis": "lexis", "variant": ["autumn"], "sibling": ["fall"]}],
                  elicitation=["Describe the fall season."])


def test_shipped_contexts_are_clean_of_their_own_markers(shipped):
    """The guard above is only worth having if the shipped corpus passes it."""
    for tag, ms in shipped.items():
        if not ms.testable:
            continue
        every = [m for ax in ms.markers for m in (*ax.variant, *ax.sibling)]
        for ctx in ms.elicitation:
            assert not score_text(ctx, ms).axes or score_text(ctx, ms).void, \
                f"{tag}: context leaks a marker"
