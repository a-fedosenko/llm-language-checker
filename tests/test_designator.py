from llmlc.probe.designator import candidates, generation_prompt
from llmlc.scheme import load_scheme

scheme = load_scheme("default")


def test_candidates_are_ordered_and_unique():
    c = candidates(scheme.get("cv"))
    assert c[0].kind == "A"
    assert len({x.value for x in c}) == len(c)


def test_script_is_named_in_english_not_as_a_code():
    a = candidates(scheme.get("cv"))[0].value
    assert "Cyrillic" in a and "Cyrl" not in a


def test_incumbent_is_carried_as_a_competitor():
    c = candidates(scheme.get("cv"), incumbent="Chuvash of Russia")
    assert any(x.is_("E") and x.value == "Chuvash of Russia" for x in c)


def test_colliding_incumbent_is_still_recorded_not_dropped():
    """The incumbent often equals another candidate; S2 must still know it was tested."""
    c = candidates(scheme.get("cv"), incumbent="chv (Cyrillic)")
    match = [x for x in c if x.value == "chv (Cyrillic)"]
    assert len(match) == 1, "the string must appear once"
    assert match[0].is_("E") and match[0].is_("D"), "both candidate kinds must be recorded"


def test_prompt_offers_an_escape_hatch():
    """docs/02: without one, models fabricate rather than decline."""
    p = generation_prompt("Chuvash", "a woman misses her bus")
    assert "CANNOT" in p
    assert "do not translate" in p.lower()
