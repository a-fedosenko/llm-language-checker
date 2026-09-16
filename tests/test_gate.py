"""The deterministic gate. Each case is a failure mode observed in docs/02, not an imagined one."""
import pytest

from llmlc.probe.gate import GateVerdict, check
from llmlc.probe.lid import LidResult, detect_script

PROMPT = "Write 3 sentences in Chuvash describing this situation: a woman misses her bus."


def lid(label, lang, script, conf=0.99):
    return LidResult(label, lang, script, conf, "test", [])


def test_explicit_refusal():
    r = check("CANNOT", prompt=PROMPT, expect_lang="chv", expect_script="Cyrl")
    assert r.verdict is GateVerdict.REFUSED
    assert r.is_negative


@pytest.mark.parametrize("text", ["I'm sorry, I can't assist with that.", "I don't speak that language."])
def test_polite_refusals(text):
    assert check(text, prompt=PROMPT, expect_lang="chv", expect_script="Cyrl").verdict is GateVerdict.REFUSED


def test_empty_is_refusal_not_a_score():
    assert check("", prompt=PROMPT, expect_lang="chv", expect_script="Cyrl").verdict is GateVerdict.REFUSED


def test_copying_the_prompt():
    r = check(PROMPT, prompt=PROMPT, expect_lang="chv", expect_script="Cyrl")
    assert r.verdict is GateVerdict.COPY


def test_degeneration_that_lid_still_scores_fluent():
    """gpt-4o's real Chuvash output: GlotLID scores it chv_Cyrl at 1.000 anyway."""
    text = "Куҫар ҫӗршывӗҫ ҫӗршывӗҫсем ҫӗршывӗ " * 6
    r = check(text, prompt=PROMPT, expect_lang="chv", expect_script="Cyrl",
              lid_result=lid("chv_Cyrl", "chv", "Cyrl", 1.0))
    assert r.verdict is GateVerdict.DEGENERATE


def test_wrong_script_answered_in_english():
    """Gemini answered an 'Acehnese in Arabic script' prompt in English."""
    r = check("Acehnese written in the Arabic script is used in Aceh province.",
              prompt=PROMPT, expect_lang="ace", expect_script="Arab",
              lid_result=lid("eng_Latn", "eng", "Latn"))
    assert r.verdict is GateVerdict.WRONG_SCRIPT


def test_nearest_relative_substitution_is_distinguished():
    """Gemini's 'Acehnese' identified as Minangkabau -- a neighbour, not a random miss."""
    r = check("لون ݢالق تهت مروينوء باسا اچيه نڠݢروي اچيه ديميكين",
              prompt=PROMPT, expect_lang="ace", expect_script="Arab",
              relatives={"min", "msa", "ind"},
              lid_result=lid("min_Arab", "min", "Arab", 0.80))
    assert r.verdict is GateVerdict.RELATIVE_SUBSTITUTION
    assert "neighbour" in r.detail


def test_unrelated_wrong_language_is_not_substitution():
    r = check("Я говорю по-русски и сегодня очень хорошая погода в городе.",
              prompt=PROMPT, expect_lang="chv", expect_script="Cyrl",
              relatives={"tat"}, lid_result=lid("rus_Cyrl", "rus", "Cyrl"))
    assert r.verdict is GateVerdict.WRONG_LANGUAGE


def test_memorised_boilerplate_is_voided_not_counted():
    r = check("All human beings are born free and equal in dignity and rights and endowed.",
              prompt=PROMPT, expect_lang="eng", expect_script="Latn",
              lid_result=lid("eng_Latn", "eng", "Latn"))
    assert r.verdict is GateVerdict.MEMORISED
    assert not r.is_negative, "memorised text voids the item; it is not evidence against the model"


def test_too_short_is_void_not_negative():
    r = check("Ей.", prompt=PROMPT, expect_lang="chv", expect_script="Cyrl")
    assert r.verdict is GateVerdict.TOO_SHORT
    assert not r.is_negative


def test_good_output_passes():
    r = check("Пӗр хӗрарӑм ирхи автобуса ӗлкӗреймерӗ. Вӑл ҫумӑр айӗнче ӗҫе ҫуран кайрӗ.",
              prompt=PROMPT, expect_lang="chv", expect_script="Cyrl",
              lid_result=lid("chv_Cyrl", "chv", "Cyrl", 1.0))
    assert r.passed


@pytest.mark.parametrize("text,script", [
    ("Эпĕ чăвашла пĕлетĕп", "Cyrl"),
    ("I missed the bus", "Latn"),
    ("لون ݢالق تَهت", "Arab"),
    ("ወልድ እት መድረሰት", "Ethi"),
])
def test_script_detection(text, script):
    assert detect_script(text) == script
