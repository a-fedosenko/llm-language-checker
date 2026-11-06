"""The five dialect probes.

The cases that matter are the ones where a plausible implementation would score
the *most ignorant* answer highest: a model that changed nothing twice is
perfectly consistent, and a model that guesses on a forced two-way choice is
right half the time. Both are tested here, because both would turn the null
control into a false positive.
"""
import pytest

from llmlc.probe.attest import (GENERIC, INDISTINGUISHABLE, UNSUPPORTED, Blind,
                                Identification, Separation)
from llmlc.probe.dialect import (PARAPHRASED_AT, BlindRead, ContrastRead,
                                 Conversion, blind_for, consistency, diff,
                                 family_of, grounding)


class NullCorpus:
    def write(self, record):
        return record


SR = Blind(language="Serbian", options=("Serbia", "Montenegro"))


def conv(edits, rate, **kw):
    return Conversion(designator="x", before="b", after="a", edits=edits, rate=rate, **kw)


# -- the diff, which is P3's whole measurement -------------------------------

def test_the_diff_names_the_words_that_changed():
    """The artifact a reviewer audits: this is the model saying, in its own
    output, what it thinks the variety *is*."""
    edits, rate = diff("Дете је нашло пса поред реке.",
                       "Дијете је нашло пса поред ријеке.")
    assert edits == [("дете", "дијете"), ("реке", "ријеке")]
    assert 0 < rate < PARAPHRASED_AT


def test_an_unchanged_text_is_a_zero_diff():
    assert diff("Same text here.", "Same text here.") == ([], 0.0)


def test_punctuation_alone_is_not_a_dialect_edit():
    """Otherwise a model that re-punctuated would read as having converted."""
    assert diff("Same text here.", "Same text here!") == ([], 0.0)


def test_case_alone_is_not_a_dialect_edit():
    assert diff("The boot was open.", "the boot was open.") == ([], 0.0)


def test_an_empty_original_cannot_be_scored():
    assert diff("", "anything") == ([], 0.0)


def test_one_substitution_in_a_long_text_is_still_a_conversion():
    """There is no floor, and this is why. A dialect conversion is supposed to
    be a small edit, so any floor expressed as a share of the text convicts
    exactly the models that did the job correctly -- one correct substitution in
    a long paragraph is 2% of it and is still a conversion."""
    long_text = " ".join(["word"] * 50 + ["дете"])
    edits, rate = diff(long_text, long_text.replace("дете", "дијете"))
    assert rate < 0.02, "the premise: this is far below any plausible floor"
    assert conv(edits, rate).converted is True


# -- P3: did it change anything at all ---------------------------------------

def test_a_conversion_that_moved_nothing_is_a_negative():
    assert conv([], 0.0).converted is False
    assert conv([], 0.0).paraphrased is False


def test_a_conversion_that_moved_something_is_not():
    assert conv([("a", "b")], 0.2).converted is True


def test_rewriting_everything_is_a_paraphrase_rather_than_a_conversion():
    """The failure a floor would have missed entirely. A model that rewrote the
    whole passage has produced something that is no longer the same text, and
    its diff is sentence rewrites rather than the variety's own alternations --
    unreadable as evidence, and the opposite failure from changing nothing."""
    c = conv([("a b c", "x y z")], 0.9)
    assert c.paraphrased and not c.converted


def test_the_two_failures_are_distinguishable():
    """A reader has to be able to tell which happened; they call for opposite
    conclusions about the model."""
    assert conv([], 0.0).as_dict()["paraphrased"] is False
    assert conv([("a", "b")], 0.9).as_dict()["converted"] is False


def test_a_gated_out_conversion_is_an_error_not_a_zero():
    """A rewrite that answered in the wrong language is a different failure, and
    the diff would report it as an enormous and meaningless one."""
    c = Conversion(designator="x", before="b", after=None, error="wrong_language")
    assert not c.ok and not c.converted


# -- P4: the probe that must not reward doing nothing ------------------------

def test_two_runs_that_changed_nothing_are_not_consistent():
    """The case that decides whether this probe is worth having. Two empty
    signatures agree perfectly and mean nothing -- scoring them 1.0 would make
    the most ignorant possible answer the highest-scoring one, and `systematic`
    would then be true for every model that cannot do the task at all."""
    out = consistency([conv([], 0.0), conv([], 0.0)])
    assert out.agreement is None and out.systematic is False


def test_identical_real_conversions_are_fully_consistent():
    runs = [conv([("дете", "дијете")], 0.3), conv([("дете", "дијете")], 0.3)]
    assert consistency(runs).agreement == 1.0


def test_disagreeing_conversions_score_low():
    """Improvisation: the same request, different substitutions each time."""
    out = consistency([conv([("a", "b")], 0.3), conv([("c", "d")], 0.3)])
    assert out.agreement == 0.0 and out.systematic is False


def test_extra_edits_count_against_agreement_too():
    """Jaccard, not containment: adding edits is as much a sign of improvisation
    as omitting them, so a superset must not score as perfect agreement."""
    a = conv([("x", "y")], 0.3)
    b = conv([("x", "y"), ("p", "q"), ("r", "s")], 0.5)
    assert consistency([a, b]).agreement == pytest.approx(1 / 3)


def test_order_and_repetition_do_not_affect_the_signature():
    a = conv([("x", "y"), ("p", "q")], 0.3)
    b = conv([("p", "q"), ("x", "y"), ("x", "y")], 0.3)
    assert consistency([a, b]).agreement == 1.0


def test_one_usable_run_cannot_establish_consistency():
    out = consistency([conv([("x", "y")], 0.3), conv([], 0.0)])
    assert out.agreement is None and out.systematic is False


# -- P1: scoring a blind read ------------------------------------------------

def test_a_correct_blind_read_is_scored_against_an_expectation_held_here():
    """`expected` lives on the result, never on the call. That is what makes the
    blinding checkable by reading one signature."""
    r = BlindRead("att", "Montenegro", Identification("Montenegro"))
    assert r.correct and not r.wrong


def test_naming_the_wrong_variety_is_wrong_rather_than_undecided():
    r = BlindRead("att", "Montenegro", Identification("Serbia"))
    assert r.wrong and not r.correct


def test_generic_is_neither_correct_nor_wrong():
    """It is a statement about the text, and must not be counted as a failure of
    the model or of the attestor."""
    r = BlindRead("att", "Montenegro", Identification(GENERIC))
    assert not r.correct and not r.wrong


def test_declining_is_neither_correct_nor_wrong():
    r = BlindRead("att", "Montenegro", Identification(UNSUPPORTED))
    assert not r.correct and not r.wrong


# -- P2: the pair, and the order it was shown in -----------------------------

def sep(a, b, swapped=False):
    return Separation(a, b, swapped=swapped)


def test_a_correct_pair_assignment_scores():
    r = ContrastRead("att", "Serbia", "Montenegro", sep("Serbia", "Montenegro"))
    assert r.correct


def test_a_swapped_presentation_is_unscrambled_before_scoring():
    """The pair is shown in an order salted by the texts, so an attestor that
    answers the options in the order they were listed cannot score 100% by
    habit. The caller knows the order; the attestor never does."""
    r = ContrastRead("att", "Serbia", "Montenegro",
                     sep("Montenegro", "Serbia", swapped=True))
    assert r.correct


def test_a_swapped_presentation_can_still_be_wrong():
    r = ContrastRead("att", "Serbia", "Montenegro",
                     sep("Serbia", "Montenegro", swapped=True))
    assert not r.correct


def test_calling_the_pair_indistinguishable_is_a_real_answer_not_an_error():
    """The answer the Russian null control must be able to produce. Without this
    escape a forced two-way choice floors at 0.5 by guessing and the null could
    never come back clean."""
    r = ContrastRead("att", "Russia", "Belarus",
                     sep(INDISTINGUISHABLE, INDISTINGUISHABLE))
    assert r.merged and not r.correct


def test_naming_one_variety_for_both_texts_is_not_a_split():
    s = sep("Serbia", "Serbia")
    assert not s.split
    assert not ContrastRead("att", "Serbia", "Montenegro", s).correct


# -- P5: grounding, tallied over whatever ran --------------------------------

def test_grounding_counts_citations_and_fabrications_across_probe_kinds():
    reads = [
        BlindRead("a", "X", Identification("X", markers=[{"text": "m1", "why": ""}],
                                           fabricated=[])),
        ContrastRead("b", "X", "Y", Separation("X", "Y",
                                               markers=[{"text": "m2", "why": ""},
                                                        {"text": "m3", "why": ""}],
                                               fabricated=["m3"])),
    ]
    g = grounding(reads)
    assert g.cited == 3 and g.fabricated == 1
    assert g.rate == pytest.approx(2 / 3) and g.unreliable


def test_citing_nothing_is_not_a_grounding_failure():
    """None, not zero. An attestor that cited no markers has not fabricated
    any, and reading that as 0.0 would convict it of the opposite."""
    g = grounding([BlindRead("a", "X", Identification("X"))])
    assert g.rate is None and not g.unreliable


def test_one_invented_quotation_is_enough_to_call_an_attestor_unreliable():
    """A model that fabricates a marker to support a verdict has told us the
    verdict was not read off the text, which is the whole claim it was making."""
    reads = [BlindRead("a", "X", Identification(
        "X", markers=[{"text": f"m{i}", "why": ""} for i in range(10)],
        fabricated=["m0"]))]
    assert grounding(reads).unreliable


# -- building the option list from the scheme --------------------------------

@pytest.fixture
def scheme():
    from llmlc.scheme import load_scheme
    try:
        return load_scheme("catmint")
    except FileNotFoundError:
        pytest.skip("no TMS-derived scheme on disk")


def test_the_options_are_region_names_not_tags(scheme):
    """A tag hands the answer to anything that can read one, and the region name
    is also what the designator uses -- so attestor and producer are speaking
    about the same thing."""
    b = blind_for(scheme, family_of(scheme, scheme.get("pt")), salt="x")
    assert "Brazil" in b.options and "Portugal" in b.options
    # No tag spelling: a region name may well contain a hyphen (Guinea-Bissau,
    # Timor-Leste), so the test is that no option is a tag, not that none has
    # punctuation in it.
    tags = {l.tag for l in family_of(scheme, scheme.get("pt"))}
    assert not (set(b.options) & tags)


def test_the_umbrella_tag_contributes_no_option(scheme):
    """It is the neutral arm. Offering it as an answer would be offering "none
    of these" twice, since `generic` already means that."""
    fam = family_of(scheme, scheme.get("sr"))
    assert any(l.inclusive for l in fam), "the premise has changed"
    b = blind_for(scheme, fam, salt="x")
    assert GENERIC in b.answerable and UNSUPPORTED in b.answerable


def test_one_variety_written_in_two_scripts_is_one_option(scheme):
    """`sr-me-cyrl` and `sr-me-latn` are Montenegro written twice, not two
    varieties. Listing both would make the option set unanswerable."""
    b = blind_for(scheme, family_of(scheme, scheme.get("sr")), salt="x")
    assert b.options.count("Montenegro") == 1


def test_a_family_spans_regions_rather_than_an_equivalence_class(scheme):
    """Grouped by language, not by `iso639_3|script` -- the class cannot span
    regions, which is the whole thing a family is for."""
    fam = {l.tag for l in family_of(scheme, scheme.get("sr"))}
    assert {"sr", "sr-rs-cyrl", "sr-me-cyrl", "sr-me-latn"} <= fam


def test_the_caller_chooses_the_field(scheme):
    """Spanish carries 22 regional tags, and a 22-way blind choice is a harder
    task than the one being measured -- chance falls to 4.5%, and an attestor
    that knows Mexican from Peninsular Spanish can still miss by picking
    Uruguay. Passing a subset must work and must not smuggle the rest back."""
    fam = family_of(scheme, scheme.get("es"))
    assert len(fam) > 20, "the premise has changed"
    chosen = [l for l in fam if l.tag in {"es", "es-es", "es-mx"}]
    b = blind_for(scheme, chosen, salt="x")
    assert set(b.options) == {"Spain", "Mexico"}


def test_the_russian_family_still_offers_every_region(scheme):
    """The null control needs real options: the probe has to be *able* to find a
    distinction here and report that it did not, rather than never asking."""
    b = blind_for(scheme, family_of(scheme, scheme.get("ru")), salt="x")
    assert {"Belarus", "Kazakhstan", "Ukraine"} <= set(b.options)


# -- the probe layer holds the expectation and still does not leak it --------

class Recorder:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def complete(self, model, prompt, *, max_tokens=400, temperature=0.0, system=None):
        from llmlc.client.openai_compat import Completion
        self.calls.append({"user": prompt, "system": system})
        return Completion(self.reply, None)

    @property
    def sent(self):
        c = self.calls[-1]
        return f"{c['system']}\n{c['user']}"


def test_blind_read_knows_the_answer_and_the_attestor_does_not():
    """The seam the whole design turns on. `blind_read` is given `expected` so it
    can score the reply; `attest.identify` has no parameter for it, so the same
    call with a different expectation must produce a byte-identical prompt."""
    from llmlc.probe.dialect import blind_read

    text = "Дијете је нашло изгубљеног пса поред ријеке."
    a, b = Recorder('{"answer": "Montenegro"}'), Recorder('{"answer": "Montenegro"}')
    blind_read(a, "att", text=text, blind=SR, expected="Montenegro",
               tag="sr-me-cyrl", corpus=NullCorpus())
    blind_read(b, "att", text=text, blind=SR, expected="Serbia",
               tag="sr-rs-cyrl", corpus=NullCorpus())
    assert a.sent == b.sent


def test_contrast_read_likewise_keeps_the_assignment_to_itself():
    from llmlc.probe.dialect import contrast_read

    first, second = "Дете је нашло пса поред реке.", "Дијете је нашло пса поред ријеке."
    a, b = Recorder('{"a": "Serbia", "b": "Montenegro"}'), Recorder('{"a": "Serbia", "b": "Montenegro"}')
    contrast_read(a, "att", first=first, second=second, blind=SR,
                  expected_first="Serbia", expected_second="Montenegro",
                  tag="sr", corpus=NullCorpus())
    contrast_read(b, "att", first=first, second=second, blind=SR,
                  expected_first="Montenegro", expected_second="Serbia",
                  tag="sr", corpus=NullCorpus())
    assert a.sent == b.sent


def test_the_corpus_records_the_expectation_even_though_the_prompt_did_not():
    """Convention 6: a verdict you can only check by trusting the code is a
    verdict most people take on trust. The expectation has to be *recorded* --
    it just must not be *sent*."""
    from llmlc.probe.dialect import blind_read

    written = []

    class Spy:
        def write(self, record):
            written.append(record)
            return record

    c = Recorder('{"answer": "Montenegro"}')
    blind_read(c, "att", text="Дијете је нашло пса.", blind=SR,
               expected="Montenegro", tag="sr-me-cyrl", corpus=Spy())
    assert written[0].meta["expected"] == "Montenegro"
    assert "Montenegro" not in (written[0].prompt or "").replace(
        ", ".join(SR.options), "")
