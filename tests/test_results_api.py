"""Paging, availability, and the resolution view.

Seeded against an isolated database rather than whatever is on disk: these assert
counts, and a test whose expected number depends on how many scans the developer
happens to have run is not a test.
"""
import pytest
from fastapi.testclient import TestClient

from llmlc.api import results as store
from llmlc.api.main import app
from llmlc.db import reset_for_tests, session
from llmlc.db.repo import upsert_result

client = TestClient(app)


def row(tag, engine="m1", **kw):
    base = dict(engine=engine, tag=tag, cls=f"{tag}|Latn", tier="Proficient",
                evidence="fact-recall", s_lang=1.0, s_content=0.98, ci_low=0.95,
                ci_high=1.0, borderline=False, reliability=1.0, refusals=0,
                designator=tag, backtranslator="bt:a", judge="j",
                method_version="2.0.0")
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def seeded(tmp_path):
    reset_for_tests(f"sqlite+pysqlite:///{tmp_path/'t.db'}")
    store._scheme.cache_clear()
    with session() as s:
        for i in range(12):
            upsert_result(s, row(f"x{i:02d}"))
        upsert_result(s, row("de", tier="Assisted", s_content=0.8))
        upsert_result(s, row("de", engine="m2", tier="Assisted", s_content=0.6))
        upsert_result(s, row("ug", tier="Proficient", reliability=0.333, refusals=2,
                             items=[{"spec": "a", "gate": "pass"}]))
        upsert_result(s, row("fr", tier="Assisted", s_content=0.7,
                             reliability=0.66, refusals=1))
        upsert_result(s, row("nn", tier="Unusable", s_lang=0.0, s_content=0.0,
                             reliability=0.0, refusals=3,
                             evidence="deterministic-negative"))
        upsert_result(s, row("sw", resolves_to={"swh_Latn": 3}))
        upsert_result(s, row("kk", resolves_to={"kaz_Cyrl": 2, "kaz_Latn": 1}))
    yield


# -- paging ------------------------------------------------------------------

def test_a_page_is_a_page_but_the_summary_counts_everything():
    """A facet count that changed as you paged would be worse than no facets."""
    d = client.get("/results", params={"limit": 5}).json()
    assert len(d["items"]) == 5
    assert d["total"] == 19
    assert d["summary"]["total"] == 19
    assert sum(d["summary"]["tiers"].values()) == 19


def test_offset_walks_the_whole_set_without_repeats():
    seen = []
    for offset in range(0, 20, 5):
        seen += [(r["engine"], r["tag"])
                 for r in client.get("/results", params={"limit": 5, "offset": offset})
                 .json()["items"]]
    assert len(seen) == 19
    assert len(set(seen)) == 19


def test_filters_narrow_the_total_and_the_summary_together():
    d = client.get("/results", params={"engine": "m2"}).json()
    assert d["total"] == 1
    assert d["summary"]["engines"] == {"m2": 1}
    assert all(r["engine"] == "m2" for r in d["items"])


def test_search_matches_language_names_not_only_tags():
    """The name lives in the scheme, not the results table; searching must still find it."""
    d = client.get("/results", params={"q": "german"}).json()
    assert [r["tag"] for r in d["items"]] == ["de", "de"]


def test_search_with_no_match_returns_nothing_rather_than_everything():
    assert client.get("/results", params={"q": "zzzznotalanguage"}).json()["total"] == 0


def test_rows_carry_the_language_name_from_the_scheme():
    d = client.get("/results", params={"q": "de", "limit": 50}).json()
    de = next(r for r in d["items"] if r["tag"] == "de")
    assert de["language"]["name"], "the UI's language column reads this"


# -- availability ------------------------------------------------------------

def test_availability_bands_come_out_of_reliability():
    by_tag = {r["tag"]: r for r in client.get("/results", params={"limit": 50}).json()["items"]}
    assert by_tag["x00"]["availability"] == "reliable"
    assert by_tag["fr"]["availability"] == "intermittent"
    assert by_tag["ug"]["availability"] == "unreliable"
    assert by_tag["nn"]["availability"] == "refused"


def test_availability_filters_in_sql_so_total_and_summary_agree():
    d = client.get("/results", params={"availability": "unreliable"}).json()
    assert d["total"] == 1
    assert d["summary"]["total"] == 1
    assert d["items"][0]["tag"] == "ug"


def test_the_ug_case_no_longer_reads_as_plain_light_review():
    """The finding that prompted this: a top-tier result at reliability 0.33 said
    "light review" and nothing about refusing two requests in three."""
    r = client.get("/results/m1/ug").json()
    assert r["tier"] == "Proficient", "capability is unchanged; it wrote the language"
    assert "fallback" in r["workflow"] and "2 refusal(s) of 3" in r["workflow"]


def test_tier_is_not_capped_by_availability():
    """Capping would restate a refusal as an inability, which is a different claim."""
    assert client.get("/results/m1/ug").json()["tier"] == "Proficient"


# -- resolution --------------------------------------------------------------

def test_resolution_reports_a_macrolanguage_resolving_to_a_member():
    d = client.get("/resolution").json()
    sw = next(i for i in d["items"] if i["tag"] == "sw")
    assert sw["expected"] == "swa_Latn"
    assert sw["engines"]["m1"]["dominant"] == "swh_Latn"
    assert sw["engines"]["m1"]["verdict"] == "member"
    assert "swh" in sw["members"]


def test_resolution_reports_the_dominant_label_not_the_first_one():
    d = client.get("/resolution").json()
    kk = next(i for i in d["items"] if i["tag"] == "kk")
    assert kk["engines"]["m1"]["dominant"] == "kaz_Cyrl"
    assert kk["engines"]["m1"]["verdict"] == "as-expected"


def test_resolution_can_be_limited_to_macrolanguages():
    d = client.get("/resolution", params={"macro_only": True}).json()
    assert [i["tag"] for i in d["items"]] == ["sw"]


def test_resolution_counts_divergence():
    assert client.get("/resolution").json()["divergent"] == 1


def test_rows_without_resolution_data_are_absent_rather_than_guessed():
    assert all(i["tag"] in ("sw", "kk") for i in client.get("/resolution").json()["items"])


# -- artifacts and export ----------------------------------------------------

def test_csv_export_covers_the_filtered_set_not_the_page():
    body = client.get("/export.csv", params={"engine": "m1"}).text
    lines = [l for l in body.splitlines() if l.strip()]
    assert len(lines) == 19, "header plus every m1 row"
    assert lines[0].startswith("tag,language,engine,tier,workflow")


def test_artifact_download_refuses_anything_but_the_two_artifacts():
    assert client.get("/artifacts/.env").status_code == 404
    assert client.get("/artifacts/support.does-not-exist.json").status_code == 404


def test_engines_endpoint_reports_what_has_been_measured():
    assert client.get("/engines").json()["measured"] == ["m1", "m2"]
