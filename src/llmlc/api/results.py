"""Read-only access to results.

Reads the database when one is reachable, and falls back to the evidence files
on disk otherwise -- so the UI still works for someone who has only ever run the
CLI, and a browser session never becomes a reason to stand up a database server.

**Filtering and paging happen in SQL, not in Python.** The previous version
loaded every row and sliced the list, which was 59 ms at a few thousand rows and
would have been the first thing to break on a full catalogue across several
models. The file fallback still filters in memory; it is bounded by what one
person's CLI has written.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import and_, func, select

RESULTS_DIR = pathlib.Path("data/results")

#: Summary facets: result column -> key in the summary object. One group-by each,
#: rather than one pass over every row in Python.
FACETS = {"tier": "tiers", "evidence": "evidence", "engine": "engines",
          "variant_evidence": "variants"}


@dataclass
class Query:
    engine: str | None = None
    tier: str | None = None
    evidence: str | None = None
    availability: str | None = None
    variant: str | None = None
    q: str | None = None
    limit: int = 200
    offset: int = 0


@lru_cache(maxsize=4)
def _scheme():
    from llmlc.config import settings
    from llmlc.scheme import load_scheme
    return load_scheme(settings.scheme)


def _language(tag: str) -> dict:
    """Scheme metadata for a tag. The `result` table stores the tag, not the name:
    the name belongs to the scheme and would go stale in a copy of it."""
    try:
        lang = _scheme().get(tag)
    except Exception:  # noqa: BLE001 -- no scheme is a display problem, not an error
        return {"name": None}
    if lang is None:
        return {"name": None}
    return {"name": lang.name, "local_name": lang.local_name, "scope": lang.scope,
            "iso639_3": lang.iso639_3, "script": lang.script, "type": lang.type}


def _matching_tags(q: str) -> list[str]:
    """Tags whose tag or name matches `q`.

    Resolved against the in-memory scheme and handed to SQL as an `IN`, because
    the name a user searches for is not a column -- and putting it in one would
    mean a second copy of the catalogue that could disagree with the first.
    """
    ql = q.lower()
    try:
        langs = _scheme().languages.values()
    except Exception:  # noqa: BLE001
        return []
    return [x.tag for x in langs
            if ql in x.tag.lower()
            or (x.name and ql in x.name.lower())
            or (x.local_name and ql in x.local_name.lower())]


# -- database path -----------------------------------------------------------

def _availability(reliability: float | None) -> str:
    from llmlc.probe.score import availability_for
    return availability_for(reliability if reliability is not None else 1.0,
                            attempts=1).value


def _availability_clause(col, band: str):
    """Availability as a WHERE clause.

    It is derived from reliability rather than stored, but the bands are pure
    thresholds on that one column, so the derivation is expressible in SQL --
    which keeps the filter, the total and the summary counting the same rows.
    Thresholds come from `AVAILABILITY` so there is still one definition.
    """
    from llmlc.probe.score import AVAILABILITY, Availability
    if band == Availability.REFUSED.value:
        return col <= 0
    upper = None
    for b, minimum in AVAILABILITY:
        if b.value == band:
            lower = minimum
            break
        upper = minimum
    else:
        return None
    clause = col > 0 if lower <= 0 else col >= lower
    return clause if upper is None else and_(clause, col < upper)


def _filters(query: Query):
    from llmlc.db.models import Result
    clauses = []
    if query.engine:
        clauses.append(Result.engine == query.engine)
    if query.tier:
        clauses.append(Result.tier == query.tier)
    if query.evidence:
        clauses.append(Result.evidence == query.evidence)
    if query.availability:
        clause = _availability_clause(Result.reliability, query.availability)
        clauses.append(clause if clause is not None else Result.id < 0)
    if query.variant:
        clauses.append(Result.variant_evidence == query.variant)
    if query.q:
        tags = _matching_tags(query.q)
        clauses.append(Result.tag.in_(tags) if tags else Result.id < 0)
    return clauses


def _from_db(query: Query) -> dict | None:
    try:
        from llmlc.db import create_all, session
        from llmlc.db.models import Result
    except ImportError:
        return None
    try:
        create_all()
        with session() as s:
            clauses = _filters(query)
            stmt = select(Result)
            for c in clauses:
                stmt = stmt.where(c)

            total = s.scalar(select(func.count()).select_from(
                stmt.order_by(None).subquery())) or 0
            rows = list(s.scalars(stmt.order_by(Result.engine, Result.tag)
                                  .limit(query.limit).offset(query.offset)))
            return {"total": total, "summary": _db_summary(s, clauses),
                    "items": [_serialise(r) for r in rows], "source": "db"}
    except Exception:  # noqa: BLE001 -- fall back to the files
        return None


def _db_summary(s, clauses) -> dict:
    from llmlc.db.models import Result
    out: dict = {"total": 0}
    for column, key in FACETS.items():
        col = getattr(Result, column)
        stmt = select(col, func.count()).group_by(col)
        for c in clauses:
            stmt = stmt.where(c)
        out[key] = {k or "?": n for k, n in s.execute(stmt).all()}
    out["total"] = sum((out.get("tiers") or {}).values())
    return out


def _is_stale(method_version: str | None) -> bool:
    from llmlc.db.repo import _version_key
    from llmlc.export.artifacts import METHOD_VERSION
    if not method_version:
        return True
    return _version_key(method_version) < _version_key(METHOD_VERSION)


def _serialise(r) -> dict:
    return {
        "tag": r.tag, "engine": r.engine, "tier": r.tier, "evidence": r.evidence,
        "s_lang": r.s_lang, "s_content": r.s_content, "ci": [r.ci_low, r.ci_high],
        "borderline": r.borderline, "reliability": r.reliability,
        "availability": _availability(r.reliability), "refusals": r.refusals,
        "workflow": workflow_for(r.tier, r.reliability, r.refusals,
                                 len(r.items or []) + (r.refusals or 0)),
        # Stated rather than left for the reader to infer from a version string.
        # A row measured under an older method carries a tier that no longer
        # names anything -- it renders with no colour and no workflow sentence,
        # and silence there reads as "we have nothing to say about this
        # language" rather than "this was measured on a different scale".
        "stale": _is_stale(r.method_version),
        "designator": {"winner": r.designator, **(r.designator_detail or {})},
        "provenance": r.provenance, "variant_evidence": r.variant_evidence,
        "inherited_from": r.inherited_from, "resolves_to": r.resolves_to,
        "s_variant": r.s_variant, "variant_detail": r.variant_detail,
        "backtranslator": r.backtranslator,
        "backtranslator_qualification": r.backtranslator_qualification,
        "judge": r.judge, "pivot": r.pivot, "hardware_profile": r.hardware_profile,
        "method_version": r.method_version, "rungs_run": r.rungs_run,
        "calls": r.calls, "items": r.items, "notes": r.notes,
        "language": _language(r.tag),
        "job_id": r.job_id,
        "tested_at": r.tested_at.isoformat() if r.tested_at else None,
        "source": "db",
    }


def workflow_for(tier: str | None, reliability: float | None, refusals: int | None,
                 n_items: int | None) -> str:
    """Rebuild the workflow sentence from a stored row's parts.

    Recomputed rather than read back, on both the database and the file path. The
    wording has changed once already -- when availability was added -- and a
    stored sentence would leave every row written before that change still saying
    "light review" for a model that refused two attempts in three.
    """
    from llmlc.probe.score import AVAILABILITY_CAVEAT, WORKFLOW, Tier, availability_for
    try:
        t = Tier(tier)
    except ValueError:
        # A tier string from method 1.x -- "Strong", "Token" -- no longer names a
        # value on this scale. Saying nothing is right: the row is stale, and
        # `llmlc status` is where a reader is told so.
        return ""
    base = WORKFLOW[t]
    attempts = n_items or 0
    caveat = AVAILABILITY_CAVEAT[availability_for(
        reliability if reliability is not None else 1.0, attempts=attempts)]
    if not caveat or t is Tier.UNUSABLE:
        return base
    return f"{base} -- {caveat} ({refusals or 0} refusal(s) of {attempts})"


# -- file path ---------------------------------------------------------------

def _from_files(root: pathlib.Path | None = None) -> list[dict]:
    """Latest row per (engine, tag, method_version) from the append-only files."""
    latest: dict[tuple[str, str, str], dict] = {}
    for path in sorted((root or RESULTS_DIR).glob("evidence.*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                row["source"] = "file"
                row["availability"] = _availability(row.get("reliability"))
                row["workflow"] = workflow_for(row.get("tier"), row.get("reliability"),
                                               row.get("refusals"), row.get("n_items"))
                row["stale"] = _is_stale(row.get("method_version"))
                latest[(row.get("engine", ""), row.get("tag", ""),
                        row.get("method_version", ""))] = row
    return list(latest.values())


def _filter_rows(rows: list[dict], query: Query) -> list[dict]:
    if query.engine:
        rows = [r for r in rows if r.get("engine") == query.engine]
    if query.tier:
        rows = [r for r in rows if r.get("tier") == query.tier]
    if query.evidence:
        rows = [r for r in rows if r.get("evidence") == query.evidence]
    if query.availability:
        rows = [r for r in rows if r.get("availability") == query.availability]
    if query.variant:
        rows = [r for r in rows if r.get("variant_evidence") == query.variant]
    if query.q:
        ql = query.q.lower()
        rows = [r for r in rows
                if ql in r.get("tag", "").lower()
                or ql in ((r.get("language") or {}).get("name") or "").lower()]
    return rows


def summarise(rows: list[dict]) -> dict:
    """Facet counts for the file path, matching what SQL produces for the database."""
    out: dict[str, dict[str, int]] = {v: {} for v in FACETS.values()}
    keys = {"tiers": "tier", "evidence": "evidence", "engines": "engine",
            "variants": "variant_evidence"}
    for r in rows:
        for facet, field in keys.items():
            value = r.get(field) or "?"
            out[facet][value] = out[facet].get(value, 0) + 1
    return {"total": len(rows), **out}


# -- public surface ----------------------------------------------------------

def page(query: Query, root: pathlib.Path | None = None) -> dict:
    """One page of results plus a summary over the *whole* filtered set.

    The summary deliberately counts every match, not the page: a facet count that
    changed as you scrolled would be worse than none.
    """
    if root is None:
        got = _from_db(query)
        # An empty database is not the same as no results: someone who has only
        # ever run `llmlc check` has evidence files and an untouched schema. Fall
        # through to the files rather than showing them an empty page.
        if got is not None and got["total"]:
            return {**got, "limit": query.limit, "offset": query.offset}
    rows = sorted(_filter_rows(_from_files(root), query),
                  key=lambda r: (r.get("engine", ""), r.get("tag", "")))
    for r in rows:
        if not (r.get("language") or {}).get("name"):
            r["language"] = {**(r.get("language") or {}), **_language(r.get("tag", ""))}
    return {"total": len(rows), "summary": summarise(rows),
            "items": rows[query.offset: query.offset + query.limit],
            "limit": query.limit, "offset": query.offset, "source": "file"}


def load_results(root: pathlib.Path | None = None) -> list[dict]:
    """Every result, unpaged. Used where the caller genuinely needs all of them."""
    return page(Query(limit=1_000_000), root)["items"]


def detail(engine: str, tag: str) -> dict | None:
    """One result. A targeted query rather than a filtered full load -- this is
    called on every row expansion in the UI."""
    try:
        from llmlc.db import create_all, session
        from llmlc.db.models import Result
        create_all()
        with session() as s:
            row = s.scalars(select(Result)
                            .where(Result.engine == engine, Result.tag == tag)
                            .order_by(Result.tested_at)).all()
            if row:
                return _serialise(row[-1])
    except Exception:  # noqa: BLE001 -- fall back to the files
        pass
    hits = [r for r in _filter_rows(_from_files(), Query(engine=engine))
            if r.get("tag") == tag]
    if not hits:
        return None
    hit = hits[-1]
    if not (hit.get("language") or {}).get("name"):
        hit["language"] = {**(hit.get("language") or {}), **_language(tag)}
    return hit


# -- macrolanguage resolution ------------------------------------------------

def _verdict(lang, expected: str | None, dominant: str | None) -> str:
    """How the produced language relates to the one that was asked for."""
    if dominant is None:
        return "unknown"
    if expected and dominant == expected:
        return "as-expected"
    got_lang, _, got_script = dominant.partition("_")
    if lang is None:
        return "other"
    if lang.is_macro and got_lang in set(lang.members):
        return "member"
    if lang.iso639_3 and got_lang == lang.iso639_3:
        return "other-script"
    return "other-language"


def resolution(engine: str | None = None, *, only_macro: bool = False,
               root: pathlib.Path | None = None) -> dict:
    """What each model actually produced when asked for a language, against what
    the standard says that language resolves to.

    `resolves_to` has been persisted since S3 and never surfaced. It is the one
    genuinely novel thing that falls out of the scan for free: whether `ar` gets
    you Modern Standard Arabic or Egyptian, whether `zh` gets you Mandarin, and
    whether `kk` comes back in the script the catalogue expects.
    """
    rows = [r for r in page(Query(engine=engine, limit=1_000_000), root)["items"]
            if r.get("resolves_to")]
    by_tag: dict[str, dict] = {}
    for r in rows:
        tag = r["tag"]
        try:
            lang = _scheme().get(tag)
        except Exception:  # noqa: BLE001
            lang = None
        if only_macro and not (lang and lang.is_macro):
            continue
        expected = (f"{lang.iso639_3}_{lang.script}"
                    if lang and lang.iso639_3 and lang.script else None)
        counts: dict[str, int] = r["resolves_to"]
        dominant = max(counts, key=counts.get) if counts else None
        entry = by_tag.setdefault(tag, {
            "tag": tag, "language": _language(tag), "expected": expected,
            "scope": lang.scope if lang else None,
            "members": sorted(lang.members) if lang and lang.is_macro else [],
            "engines": {},
        })
        entry["engines"][r["engine"]] = {
            "dominant": dominant, "counts": counts,
            "verdict": _verdict(lang, expected, dominant),
            "inherited_from": r.get("inherited_from"),
        }
    items = sorted(by_tag.values(), key=lambda e: (e["scope"] != "macrolanguage", e["tag"]))
    return {
        "total": len(items),
        "engines": sorted({e for i in items for e in i["engines"]}),
        "divergent": sum(1 for i in items
                         if any(v["verdict"] not in ("as-expected", "unknown")
                                for v in i["engines"].values())),
        "items": items,
    }


# -- variant coverage --------------------------------------------------------

def variants(engine: str | None = None, *, root: pathlib.Path | None = None) -> dict:
    """What has been established about each variant tag, and what is still a gap.

    Combines the catalogue's unfilled work (tags with no marker set authored)
    with what measurement has actually shown. The two are different questions:
    a tag can have markers and still be untested on a given model, and a tag with
    no markers can never be anything but untested.
    """
    from llmlc.probe.markers import coverage as marker_coverage

    rows = [r for r in page(Query(engine=engine, limit=1_000_000), root)["items"]
            if r.get("variant_evidence") and r.get("variant_evidence") != "untested"]
    by_tag: dict[str, dict] = {}
    for r in rows:
        entry = by_tag.setdefault(r["tag"], {
            "tag": r["tag"], "language": r.get("language") or {},
            "inherited_from": r.get("inherited_from"), "engines": {}})
        entry["engines"][r["engine"]] = {
            "evidence": r["variant_evidence"],
            "s_variant": r.get("s_variant"),
            "tier": r.get("tier"),
            "detail": r.get("variant_detail") or {},
        }
    try:
        cov = marker_coverage(_scheme())
    except Exception:  # noqa: BLE001 -- coverage is context, not the answer
        cov = {}
    return {"coverage": cov, "total": len(by_tag),
            "items": sorted(by_tag.values(), key=lambda e: e["tag"])}
