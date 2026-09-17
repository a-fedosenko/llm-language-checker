"""Class collapse, inheritance and budget."""
import pytest

from llmlc.probe.scan import ScanBudget, plan
from llmlc.scheme import load_scheme


@pytest.fixture(scope="module")
def scheme():
    return load_scheme("default")


def test_regional_variants_collapse_into_one_class(scheme):
    """de / de-AT / de-CH are one experiment: base capability is a class property."""
    groups, unknown = plan(scheme, ["de", "de-AT", "de-CH"])
    assert len(groups) == 1
    assert not unknown
    assert list(groups.values())[0] == ["de", "de-AT", "de-CH"]


def test_representative_is_the_base_tag(scheme):
    groups, _ = plan(scheme, ["de-AT", "de-CH", "de"])
    assert list(groups.values())[0][0] == "de", "the shortest tag is the least-qualified form"


def test_script_splits_a_class_but_region_does_not(scheme):
    groups, _ = plan(scheme, ["af", "af-NA"])
    assert len(groups) == 1
    kk_groups, _ = plan(scheme, ["kk", "kk-AF"])
    assert len(kk_groups) == 2, "Cyrillic and Arabic Kazakh are different experiments"


def test_unknown_tags_are_reported_not_silently_dropped(scheme):
    groups, unknown = plan(scheme, ["de", "zz-NOPE", "definitely-not-a-tag"])
    assert unknown == ["zz-NOPE", "definitely-not-a-tag"]
    assert len(groups) == 1


def test_duplicate_tags_are_collapsed(scheme):
    groups, _ = plan(scheme, ["de", "de", "de"])
    assert sum(len(m) for m in groups.values()) == 1


def test_budget_fails_closed():
    b = ScanBudget(max_calls=10)
    assert not b.exhausted
    b.spend(10)
    assert b.exhausted


def test_unbounded_budget_never_exhausts():
    b = ScanBudget()
    b.spend(10_000)
    assert not b.exhausted
