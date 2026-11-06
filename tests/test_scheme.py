"""Scheme loading, class collapse, family resolution and tag parsing."""
import pytest

from llmlc.scheme import load_scheme, subtags
from llmlc.scheme.loader import IdentityAdapter


@pytest.fixture(scope="module")
def scheme():
    return load_scheme("default")


def test_scheme_loads_and_is_substantial(scheme):
    assert scheme.meta.name == "default"
    assert len(scheme.languages) > 5000
    assert scheme.meta.attribution, "shipped catalogue must carry source attribution"


def test_known_languages_present(scheme):
    for tag in ("en", "kk", "cv", "ace", "gsw"):
        assert scheme.get(tag) is not None, tag


def test_lookup_is_case_insensitive(scheme):
    assert scheme.get("EN") is scheme.get("en") or scheme.get("EN").tag == "en"


def test_iso_codes_resolved(scheme):
    cv = scheme.get("cv")
    assert cv.iso639_3 == "chv"
    assert cv.script == "Cyrl"
    assert cv.name


def test_class_key_ignores_region_but_not_script(scheme):
    """Base-language capability is probed per class; region never splits a class."""
    kk = scheme.get("kk")
    assert kk.cls == f"{kk.iso639_3}|{kk.script}"
    assert kk.region is None or kk.region not in kk.cls


def test_classes_partition_every_tag(scheme):
    classes = scheme.classes()
    assert sum(len(v) for v in classes.values()) == len(scheme.languages)


def test_macrolanguages_have_members(scheme):
    macros = [x for x in scheme.languages.values() if x.is_macro]
    assert macros, "ISO 639-3 macrolanguage mapping must be loaded"
    assert any(x.members for x in macros)


def test_arabic_is_a_macrolanguage_with_members(scheme):
    ar = scheme.get("ar")
    assert ar.is_macro
    assert "arb" in ar.members


def test_unknown_tag_returns_none(scheme):
    assert scheme.get("zz-nonexistent") is None


@pytest.mark.parametrize(
    "tag,expected",
    [
        ("kk", ("kk", None, None)),
        ("kk-Latn", ("kk", "Latn", None)),
        ("sr-Cyrl-RS", ("sr", "Cyrl", "RS")),
        ("pt-BR", ("pt", None, "BR")),
        ("es-419", ("es", None, "419")),
        # Order-independent: tolerates conventions that put script last.
        ("ace-ID-Arab", ("ace", "Arab", "ID")),
    ],
)
def test_subtags_parses_both_orders(tag, expected):
    assert subtags(tag) == expected


def test_identity_adapter_roundtrips():
    a = IdentityAdapter()
    assert a.from_canonical(a.to_canonical("sr-Cyrl-RS")) == "sr-Cyrl-RS"


def test_missing_scheme_names_the_fix():
    with pytest.raises(FileNotFoundError, match="build_default_scheme"):
        load_scheme("no-such-scheme")


# -- ISO scope against a locale list's umbrella flag -------------------------

def test_iso_scope_and_the_lists_umbrella_flag_are_two_fields():
    """`kk` is the unqualified spelling standing over `kk-kz`, and ISO still
    calls it an individual language. Storing the second claim in `scope` made it
    a macrolanguage with no members, and `/resolution?macro_only=true` -- which
    asks which *member language* a macrolanguage resolved to -- returned it
    beside Swahili, where that question has no answer.
    """
    pytest.importorskip("llmlc.scheme")
    try:
        s = load_scheme("catmint")
    except FileNotFoundError:
        pytest.skip("no TMS-derived scheme on disk; built from a list we do not ship")

    kk, sw = s.get("kk"), s.get("sw")
    assert kk.inclusive is True and kk.scope == "individual" and kk.members == []
    # Swahili is both, and that is the point of keeping two fields: one tag can
    # be an umbrella in the list *and* a macrolanguage in ISO's sense.
    assert sw.inclusive is True and sw.is_macro and "swh" in sw.members


def test_the_unqualified_tag_is_the_arm_a_dialect_is_contrasted_against():
    """What the dialect probes read. `pt` is the neutral arm and `pt-br` is a
    variety beside it -- unlike the public catalogue, where `pt` resolves to
    `pt-Latn-BR` and is itself the Brazilian variety, leaving nothing neutral.
    """
    try:
        s = load_scheme("catmint")
    except FileNotFoundError:
        pytest.skip("no TMS-derived scheme on disk")

    for base, variety in [("pt", "pt-br"), ("en", "en-gb"), ("ru", "ru-kz"),
                          ("sr", "sr-me-cyrl")]:
        assert s.get(base).inclusive is True, base
        assert s.get(variety).inclusive is False, variety


def test_a_derived_scheme_carries_its_references_attribution():
    """Every resolved locale takes its ISO code, script, scope and endonym from
    SIL's data, so the licence travels with the derived list."""
    try:
        s = load_scheme("catmint")
    except FileNotFoundError:
        pytest.skip("no TMS-derived scheme on disk")

    assert any("SIL" in a for a in s.meta.attribution)
