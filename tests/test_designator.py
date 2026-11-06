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


def test_the_alphabet_is_stated_on_its_own_line():
    """The designator already names the script and that was not always enough:
    a model asked for "Serbian (Montenegro, Cyrillic script)" returned fluent,
    correctly ijekavian Montenegrin in Latin. Naming a region pulls toward that
    region's script the way protocol 010 found it pulls toward its dominant
    language, and the gate convicts the whole item on script before anything
    else about it is looked at."""
    from llmlc.probe.designator import script_name_for

    system, _ = generation_prompt("Serbian (Montenegro, Cyrillic script)", "x",
                                  script_name=script_name_for("Cyrl"))
    assert "Write every word in the Cyrillic alphabet." in system
    assert "not even for names or single words" in system


def test_no_alphabet_rule_where_the_script_has_no_name():
    """An instruction naming no alphabet is worse than none, and the ISO code
    is not a name -- "write in the Tfng alphabet" instructs a model in a string
    it has no reason to read as a writing system."""
    from llmlc.probe.designator import script_name_for

    assert script_name_for("Zzzz") is None
    assert script_name_for(None) is None
    system, _ = generation_prompt("Some language", "x", script_name=script_name_for("Zzzz"))
    assert "alphabet" not in system


def test_the_script_rule_does_not_leak_into_the_user_half():
    from llmlc.probe.designator import script_name_for

    _, user = generation_prompt("Serbian (Cyrillic script)", "a woman misses her bus",
                                script_name=script_name_for("Cyrl"))
    assert user == "a woman misses her bus"


# -- the unqualified tag must not be asked as a dialect -----------------------

def test_an_unqualified_tag_is_not_given_a_region_it_does_not_carry():
    """`pt` has no region subtag but inherits the region *name* "Brazil" from the
    catalogue's likely-subtag resolution. Naming it made `pt` and `pt-br` the
    same request -- "Portuguese (Brazil)" -- so the neutral arm a dialect is
    contrasted against was itself asked to be that dialect, and the comparison
    was null by construction.

    Protocol 020's trigger in mirror image: there two tags shared one prompt
    because the region was never passed; here because it was passed where the
    tag had none.
    """
    import pytest

    from llmlc.probe.ladder import candidates_for
    from llmlc.scheme import load_scheme

    try:
        s = load_scheme("catmint")
    except FileNotFoundError:
        pytest.skip("no TMS-derived scheme on disk")

    for base, variety in [("pt", "pt-br"), ("en", "en-us"), ("es", "es-es"),
                          ("ru", "ru-ru"), ("sr", "sr-rs-cyrl")]:
        b = candidates_for(s, s.get(base))[0].value
        v = candidates_for(s, s.get(variety))[0].value
        assert b != v, f"{base} and {variety} ask for the same thing: {b!r}"
        # Checked against the parenthesised qualifier list, not the whole
        # string: "Serbia" is a substring of "Serbian", and a naive `in` test
        # would convict a correct designator.
        def qualifiers(d):
            return d[d.index("(") + 1:d.rindex(")")].split(", ") if "(" in d else []

        assert s.get(base).region_name not in qualifiers(b), (
            f"{base} named a region its tag does not carry: {b!r}")
        # The variety still names its own region -- this must not be fixed by
        # dropping the region everywhere, which is method 3.0.0 undone.
        assert s.get(variety).region_name in qualifiers(v)
