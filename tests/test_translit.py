"""Deriving a Latin control for Serbian from the Cyrillic one.

The point is narrow and the limits matter more than the mapping: this is the
one case where a control may cross scripts, because the crossing is a defined
character mapping rather than a judgement about two writing systems.
"""
import pytest

from llmlc.bt.translit import (DERIVABLE, SR_CYRL_TO_LATN, Untransliterable,
                               derive_controls, to_latin)


def test_the_digraphs_are_single_letters_in_cyrillic():
    """љ њ џ are one character each and become two. Getting this wrong is the
    whole risk of a naive table."""
    assert to_latin("љут њива џак") == "ljut njiva džak"


def test_capitals_are_title_cased_not_shouted():
    """Њихов is a capitalised word, not an acronym: Njihov, never NJihov."""
    assert to_latin("Њихов Џак Љут") == "Njihov Džak Ljut"


def test_the_accented_letters_are_the_orthography_s_own():
    assert to_latin("ђ ж ћ ч ш") == "đ ž ć č š"


def test_digits_punctuation_and_latin_pass_through():
    """FLORES text is full of them, and a control that mangled "JAS 39C Gripen"
    would not be Serbian any more."""
    assert to_latin("JAS 39C Gripen се срушио (02:30 UTC).") \
        == "JAS 39C Gripen se srušio (02:30 UTC)."


def test_an_unmapped_cyrillic_letter_is_refused_not_passed_through():
    """Half-converted text would certify a reader against something nobody
    writes, and nothing downstream would show it."""
    with pytest.raises(Untransliterable, match="refusing"):
        to_latin("ово је ы")          # ы is Russian, not in the Serbian alphabet


def test_every_letter_of_the_serbian_alphabet_is_covered():
    """30 letters. A missing one does not corrupt the output — it refuses — but
    it would silently drop the whole control."""
    assert len(SR_CYRL_TO_LATN) == 30
    for ch in "абвгдђежзијклљмнњопрстћуфхцчџш":
        assert ch in SR_CYRL_TO_LATN, ch


# -- what it does to the control set -----------------------------------------

def test_a_latin_control_is_derived_and_says_where_it_came_from():
    controls = {"sr": {"kind": "reference",
                       "items": [{"text": "Дијете је нашло пса.",
                                  "reference": "A child found a dog."}]}}
    out = derive_controls(dict(controls))
    assert out["sr-Latn"]["items"][0]["text"] == "Dijete je našlo psa."
    assert out["sr-Latn"]["derived_from"] == "sr"
    assert out["sr-Latn"]["transliterated"] is True


def test_the_english_side_is_untouched():
    """The derivation adds no information. If it changed the reference it would
    be making something up."""
    controls = {"sr": {"kind": "reference",
                       "items": [{"text": "Дијете", "reference": "A child"}]}}
    out = derive_controls(dict(controls))
    assert out["sr-Latn"]["items"][0]["reference"] == "A child"


def test_a_real_control_always_beats_a_derived_one():
    controls = {"sr": {"kind": "reference", "items": [{"text": "Дијете"}]},
                "sr-Latn": {"kind": "facts", "items": [{"text": "written by hand"}]}}
    out = derive_controls(dict(controls))
    assert out["sr-Latn"]["items"][0]["text"] == "written by hand"
    assert "derived_from" not in out["sr-Latn"]


def test_nothing_is_derived_without_a_source():
    assert derive_controls({}) == {}


def test_only_serbian_is_derivable():
    """Kazakh, Uzbek and Azerbaijani are digraphic too, and their mappings are
    contested, reformed, or both. Adding one is a decision about that language,
    not a loop over a table."""
    assert list(DERIVABLE) == ["sr-Latn"]


def test_the_shipped_controls_now_cover_serbian_latin():
    from llmlc.bt.qualify import load_controls

    controls = load_controls()
    if "sr" not in controls:
        pytest.skip("FLORES controls not built; run llmlc bootstrap")
    assert controls["sr-Latn"]["derived_from"] == "sr"
    assert all("ћ" not in i["text"] and "Њ" not in i["text"]
               for i in controls["sr-Latn"]["items"])


# -- the tag the control is found under --------------------------------------

def test_a_users_own_tag_finds_the_derived_control():
    """The failure that prompted this. `sr-rs-latn` is a TMS spelling, the
    control is keyed `sr-Latn`, and resolving both against the public catalogue
    meant the user's tag resolved to nothing and the fallback never ran — a
    usable control sat in the set and the result still said `no-control`."""
    from llmlc.bt.qualify import _script_sibling, load_controls
    from llmlc.scheme import load_scheme

    controls = load_controls()
    if "sr" not in controls:
        pytest.skip("FLORES controls not built; run llmlc bootstrap")
    try:
        scheme = load_scheme("catmint")
    except (FileNotFoundError, ValueError):
        pytest.skip("no TMS scheme on this machine")

    entry = _script_sibling(controls, "sr-rs-latn", scheme)
    assert entry and entry["derived_from"] == "sr-Latn"
    assert _script_sibling(controls, "sr-rs-cyrl", scheme)["derived_from"] == "sr"


def test_the_scheme_is_passed_in_not_read_from_settings():
    """A bench session and an HTTP scan each carry their own scheme per request.
    Reading the process-wide setting fixed the CLI and left the container doing
    exactly what it had been doing — the bug looked fixed from one entry point
    and was not."""
    import inspect

    from llmlc.bt.qualify import _script_sibling, qualify, route

    for fn in (_script_sibling, qualify, route):
        assert "scheme" in inspect.signature(fn).parameters, fn.__name__


def test_a_genuinely_missing_script_is_still_missing():
    """The rule that produced the original refusal is right and stays: Cyrillic
    Uzbek is not derivable from Latin Uzbek, and claiming otherwise would
    certify a reader for a job it has not been tested on."""
    from llmlc.bt.qualify import _script_sibling, load_controls

    controls = load_controls()
    if "uz" not in controls:
        pytest.skip("FLORES controls not built")
    assert _script_sibling(controls, "uz-Cyrl") is None
