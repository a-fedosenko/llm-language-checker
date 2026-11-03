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
    system, user = generation_prompt("Chuvash", "a woman misses her bus")
    assert "CANNOT" in system
    assert "do not translate" in system.lower()


def test_the_task_and_the_material_are_separate_messages():
    """The instruction goes in the system half and the scenario in the user
    half (method 3.0.0). A single blob invites a model to continue the text
    rather than carry out the task, and the stable half is what a provider can
    cache -- it is identical for every item in a language's run."""
    system, user = generation_prompt("Chuvash", "a woman misses her bus")
    assert user == "a woman misses her bus"
    assert "a woman misses her bus" not in system
    other, _ = generation_prompt("Chuvash", "an old man buys fish")
    assert other == system, "the system half must not vary between items"


def test_the_system_half_casts_the_model_as_a_speaker_of_the_variety():
    system, _ = generation_prompt("Serbian (Cyrillic script, Serbia)", "x")
    assert system.startswith("You are a native speaker of "
                             "Serbian (Cyrillic script, Serbia).")
    assert "this specific variety" in system
