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


# -- macrolanguage members and weak LID calls --------------------------------

def test_macrolanguage_member_is_the_answer_not_a_substitution():
    """Asking for Swahili (swa) and getting Coastal Swahili (swh) is the
    macrolanguage resolving to a member. Live run scored this None before the fix."""
    r = check("Mwanamke alikosa basi la asubuhi. Alitembea kwenda kazini mvuani.",
              prompt=PROMPT, expect_lang="swa", expect_script="Latn",
              accept_lang={"swc", "swh"}, relatives={"kon"},
              lid_result=lid("swh_Latn", "swh", "Latn", 0.95))
    assert r.passed


def test_member_is_not_treated_as_a_neighbour_even_if_also_listed():
    r = check("Mwanamke alikosa basi la asubuhi na alitembea kwenda kazini.",
              prompt=PROMPT, expect_lang="swa", expect_script="Latn",
              accept_lang={"swh"}, relatives={"swh"},
              lid_result=lid("swh_Latn", "swh", "Latn", 0.99))
    assert r.passed, "accept_lang must win over relatives"


def test_weak_lid_disagreement_voids_the_item_rather_than_convicting():
    """Hindi was scored Token off a 0.53-confidence call of Angika."""
    r = check("एक महिला सुबह की बस चूक गई और बारिश में काम पर चली गई।",
              prompt=PROMPT, expect_lang="hin", expect_script="Deva",
              lid_result=LidResult("anp_Deva", "anp", "Deva", 0.53, "test", []))
    assert r.verdict is GateVerdict.LOW_CONFIDENCE
    assert not r.is_negative, "a weak LID call is not evidence against the model"


def test_confident_wrong_language_still_convicts():
    r = check("Я говорю по-русски и сегодня очень хорошая погода в городе.",
              prompt=PROMPT, expect_lang="chv", expect_script="Cyrl",
              lid_result=LidResult("rus_Cyrl", "rus", "Cyrl", 0.99, "test", []))
    assert r.verdict is GateVerdict.WRONG_LANGUAGE
    assert r.is_negative


def test_target_ranked_second_above_threshold_passes():
    r = check("एक महिला सुबह की बस चूक गई और बारिश में काम पर चली गई।",
              prompt=PROMPT, expect_lang="hin", expect_script="Deva",
              lid_result=LidResult("anp_Deva", "anp", "Deva", 0.45, "test",
                                   [("hin_Deva", 0.40), ("bho_Deva", 0.05)]))
    assert r.passed
    assert "ranked below" in r.detail


def test_target_ranked_second_but_negligible_does_not_rescue():
    r = check("Я говорю по-русски и сегодня очень хорошая погода в городе тут.",
              prompt=PROMPT, expect_lang="chv", expect_script="Cyrl",
              lid_result=LidResult("rus_Cyrl", "rus", "Cyrl", 0.97, "test",
                                   [("chv_Cyrl", 0.01)]))
    assert r.verdict is GateVerdict.WRONG_LANGUAGE


# -- protocol 019: the script check can name what the catalogue asks about ----

def test_simplified_and_traditional_are_distinguished():
    """GlotLID labels every Chinese variety `_Hani`, so the distinction has to
    come from which characters appear. Asked for Cantonese, gpt-4o answered in
    simplified Mandarin -- a real failure the gate could not previously see."""
    from llmlc.probe.lid import detect_script
    simplified = "当地媒体报道，一辆机场消防车在出动时翻车。"
    traditional = "當地媒體報導，一輛機場消防車在出勤時翻車。"
    assert detect_script(simplified, "Hans") == "Hans"
    assert detect_script(traditional, "Hant") == "Hant"
    assert detect_script(simplified, "Hant") == "Hans", "the text decides, not the request"


def test_a_composite_script_tolerates_embedded_latin():
    """Real output carries proper nouns and units in Latin. An early version of
    this required a composite's parts to be the *only* scripts present and
    convicted a Japanese sentence about the 'JAS 39C Gripen'."""
    from llmlc.probe.lid import detect_script
    assert detect_script("JAS 39C Gripenは午前9時30分頃、滑走路に墜落した。", "Jpan") == "Jpan"
    assert detect_script("안녕하세요, JAS 39C 세계입니다.", "Kore") == "Kore"


def test_a_mostly_latin_text_is_not_rescued_by_a_composite():
    from llmlc.probe.lid import detect_script
    assert detect_script("This is English with one か character.", "Jpan") == "Latn"


def test_an_unverifiable_script_abstains_rather_than_convicting():
    """Tengwar and Klingon are not encoded; Zyyy asserts no script at all. The
    gate cannot check these by any means available, and before protocol 019 it
    returned `wrong_script` for them unconditionally."""
    from llmlc.probe.lid import script_is_verifiable
    assert not script_is_verifiable("Teng") and not script_is_verifiable("Piqd")
    assert not script_is_verifiable("Zyyy") and not script_is_verifiable("Brai")
    assert script_is_verifiable("Hans") and script_is_verifiable("Olck")
    assert script_is_verifiable("Laoo") and script_is_verifiable("Hang")

    g = check("ᏣᎳᎩ ᎦᏬᏂᎯᏍᏗ ᎠᏂᏴᏫᏯ ᎤᏂᏬᏂᎯᏍᏗ ᎠᎴ ᎾᏍᎩ ᎠᏂᏴᏫᏯ", prompt="p",
              expect_lang=None, expect_script="Teng")
    assert g.verdict is not GateVerdict.WRONG_SCRIPT


def test_the_length_floor_follows_the_script():
    """A correct Chinese sentence is 20 characters. The 25-character floor voided
    five of nineteen adequate Chinese items in the calibration study."""
    short_chinese = "当地媒体报道，一辆机场消防车在出动时翻车。"
    assert len(short_chinese) < 25
    g = check(short_chinese, prompt="p", expect_lang=None, expect_script="Hans")
    assert g.verdict is not GateVerdict.TOO_SHORT
    assert check("短", prompt="p", expect_lang=None,
                 expect_script="Hans").verdict is GateVerdict.TOO_SHORT


def test_ambiguous_han_voids_rather_than_convicts():
    """Characters shared by both forms carry no signal. Unsure is `low_confidence`,
    which leaves the eligibility denominator; it is not evidence against a model."""
    g = check("中文" * 12, prompt="p", expect_lang=None, expect_script="Hant")
    assert g.verdict in (GateVerdict.LOW_CONFIDENCE, GateVerdict.DEGENERATE)
    assert g.verdict is not GateVerdict.WRONG_SCRIPT
