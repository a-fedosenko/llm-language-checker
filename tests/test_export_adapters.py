"""Export adapters and the merge rule that must never corrupt a master file."""
from llmlc.export.adapters import (CanonicalAdapter, MappedAdapter, build_support,
                                   merge_support, removals)

ROWS = [
    {"tag": "cv", "engine": "openai-gpt-4o", "tier": "Strong", "designator": "Chuvash"},
    {"tag": "de", "engine": "openai-gpt-4o", "tier": "Basic", "designator": "German"},
    {"tag": "ee", "engine": "openai-gpt-4o", "tier": "None", "designator": "Éwé"},
    {"tag": "ti", "engine": "openai-gpt-4o", "tier": "Token", "designator": "ትግርኛ"},
]


def test_only_basic_and_above_earn_a_designator():
    out = build_support(ROWS)
    assert out["cv"] and out["de"]
    assert out["ee"] == {} and out["ti"] == {}, "measured-but-unsupported is an empty mapping"


def test_engine_key_gets_the_mt_prefix():
    """mt.* covers both MT engines and LLMs: an LLM can be used as an MT engine."""
    assert "mt.openai-gpt-4o" in build_support(ROWS)["cv"]
    assert CanonicalAdapter().engine_key("mt.google") == "mt.google"


def test_mapped_adapter_renames_tags_and_omits_unmapped():
    ad = MappedAdapter("tms", {"cv": "cv", "de": "de-DE"})
    out = build_support(ROWS, ad)
    assert "de-DE" in out and "ti" not in out


def test_merge_preserves_other_engines_and_other_keys():
    existing = {"cv": {"mt.google": "cv"}, "ru": {"mt.google": "ru"}}
    merged = merge_support(existing, {"cv": {"mt.openai-gpt-4o": "Chuvash"}})
    assert merged["cv"] == {"mt.google": "cv", "mt.openai-gpt-4o": "Chuvash"}
    assert merged["ru"] == {"mt.google": "ru"}


def test_absent_key_never_means_delete():
    existing = {"cv": {"mt.google": "cv"}}
    assert "cv" in merge_support(existing, {"de": {"mt.x": "German"}})


def test_merge_does_not_mutate_its_input():
    existing = {"cv": {"mt.google": "cv"}}
    merge_support(existing, {"cv": {"mt.new": "x"}})
    assert existing == {"cv": {"mt.google": "cv"}}


def test_removals_are_reported_not_applied():
    """Dropping a support claim must be a deliberate act, never a side effect."""
    existing = {"cv": {"mt.x": "Chuvash", "mt.google": "cv"}}
    new = {"cv": {}}
    drop = removals(existing, new, "mt.x")
    assert drop == {"cv": "Chuvash"}
    assert merge_support(existing, new)["cv"]["mt.x"] == "Chuvash", "not applied by merge"
