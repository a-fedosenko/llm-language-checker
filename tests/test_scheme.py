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
