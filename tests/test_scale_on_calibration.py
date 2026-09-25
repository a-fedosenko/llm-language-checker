"""The shipped scale, checked against the 100-language calibration study.

The unit tests in `test_scoring.py` pin the scale's *shape* — monotonic by
construction, every tier reachable. This one asks the question those cannot: on
98 real languages, does the scale actually order them?

It is the regression test for protocol 017's finding. The five-tier scale passed
every unit test it had while assigning `Usable` a mean chrF++ *below* `None`,
because nothing ever ran it over data. This does.

`data/calibration/` is not committed — the fact checklists are derived from
FLORES-200 and CC BY-SA share-alike attaches to them — so the test skips where
the study has not been run, the same way `test_pivot.py` skips without a
reference control.
"""
import json
import pathlib

import pytest

from llmlc.probe.score import ORDER, tier_for

STUDY = pathlib.Path("data/calibration/study.json")
REGATE = pathlib.Path("data/calibration/regate.json")

NEGATIVE = {"refused", "copy", "wrong_script", "wrong_language",
            "relative_substitution", "degenerate"}


def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(a, b):
    """Kept here rather than imported from scripts/: a test that depends on a
    loose script resolving as a package is a test that breaks for reasons that
    have nothing to do with the scale."""
    ra, rb = _ranks(a), _ranks(b)
    n = len(ra)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = sum((x - ma) ** 2 for x in ra) ** 0.5
    db = sum((y - mb) ** 2 for y in rb) ** 0.5
    return num / (da * db) if da and db else None


def _languages():
    study = json.loads(STUDY.read_text(encoding="utf-8"))
    regate = json.loads(REGATE.read_text(encoding="utf-8"))
    out = []
    for rec in study["languages"]:
        items = [i for i in rec["items"] if i.get("recall") is not None]
        if not items:
            continue
        fixed = regate.get(rec["tag"], {})
        verdicts = [fixed.get(i["id"], i["gate"]) for i in items]
        passes = sum(1 for v in verdicts if v == "pass")
        judgeable = passes + sum(1 for v in verdicts if v in NEGATIVE)
        s_lang = passes / judgeable if judgeable else 0.0
        graded = [i["recall"] for i, v in zip(items, verdicts) if v == "pass"]
        s_content = sum(graded) / len(graded) if graded else 0.0
        out.append((rec["tag"], s_lang, s_content, rec["mean_chrf"]))
    return out


calibrated = pytest.mark.skipif(
    not (STUDY.exists() and REGATE.exists()),
    reason="needs the S7 calibration study; run `llmlc calibrate` then scripts/regate.py")


@calibrated
def test_the_tiers_are_monotonic_on_real_languages():
    """Protocol 017's headline defect, as an assertion. The old scale put `Usable`
    at mean chrF++ 20.9, below `None` at 34.5 and `Token` at 32.0."""
    langs = _languages()
    assert len(langs) >= 90, "the study should cover ~98 languages"

    means = []
    for tier in ORDER:
        members = [c for _, sl, sc, c in langs if tier_for(sl, sc) is tier]
        assert members, f"{tier.value} is assigned to no language in the study"
        means.append(sum(members) / len(members))

    assert means == sorted(means), (
        f"tiers are not ordered by quality: "
        f"{dict(zip((t.value for t in ORDER), (round(m, 1) for m in means)))}")


@calibrated
def test_no_tier_is_a_rounding_error():
    """`Basic` was never assigned in 40 real results. A band that collects almost
    nothing is a distinction the measurement cannot support."""
    langs = _languages()
    for tier in ORDER:
        n = sum(1 for _, sl, sc, _ in langs if tier_for(sl, sc) is tier)
        assert n >= 5, f"{tier.value} holds only {n} of {len(langs)} languages"


@calibrated
def test_the_tier_keeps_most_of_the_ordering_of_the_number_it_derives_from():
    """Discretising is lossy and that is accepted; destroying a third of the
    signal is not. The old `tier_for` scored 0.436 against `s_content`'s 0.664."""
    langs = _languages()
    chrf = [c for _, _, _, c in langs]
    continuous = spearman([sc for _, _, sc, _ in langs], chrf)
    discrete = spearman([float(ORDER.index(tier_for(sl, sc)))
                         for _, sl, sc, _ in langs], chrf)
    assert continuous is not None and discrete is not None
    assert discrete <= continuous, "discretising cannot add information"
    assert discrete >= continuous - 0.10, (
        f"the tier loses too much: {discrete} against {continuous}")
