"""Read-only scheme and hardware endpoints (S0).

Jobs, results and export arrive in later stages; this is the skeleton those hang
off, and the surface used to confirm a scheme loads correctly.
"""
from __future__ import annotations

from functools import lru_cache

import pathlib

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from llmlc import __version__, hardware
from llmlc.config import settings
from llmlc.api import results as results_store
from llmlc.scheme import Language, Scheme, load_scheme

STATIC = pathlib.Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="llm-language-checker",
    version=__version__,
    description="Empirical, heuristic checks of which languages a model can actually produce. "
                "Run locally; results are evidence, not proof.",
)


@lru_cache(maxsize=4)
def get_scheme(name: str) -> Scheme:
    return load_scheme(name)


@app.get("/health")
def health() -> dict:
    try:
        s = get_scheme(settings.scheme)
        loaded, tags = True, len(s.languages)
    except FileNotFoundError:
        loaded, tags = False, 0
    return {"status": "ok", "version": __version__, "scheme_loaded": loaded, "tags": tags}


@app.get("/hardware")
def hardware_info() -> dict:
    return hardware.detect(settings.hardware_profile).as_dict()


@app.get("/scheme")
def scheme_meta() -> dict:
    return get_scheme(settings.scheme).meta.model_dump()


@app.get("/languages")
def languages(
    q: str | None = Query(None, description="Substring match on tag, name or endonym"),
    scope: str | None = Query(None, pattern="^(individual|macrolanguage)$"),
    type_: str | None = Query(None, alias="type", description="ISO 639-3 type: L, E, H, A, C"),
    limit: int = Query(100, ge=1, le=5000),
    offset: int = Query(0, ge=0),
) -> dict:
    items = list(get_scheme(settings.scheme).languages.values())
    if scope:
        items = [x for x in items if x.scope == scope]
    if type_:
        items = [x for x in items if x.type == type_]
    if q:
        ql = q.lower()
        items = [x for x in items
                 if ql in x.tag.lower()
                 or (x.name and ql in x.name.lower())
                 or (x.local_name and ql in x.local_name.lower())]
    return {"total": len(items), "offset": offset, "limit": limit,
            "items": items[offset: offset + limit]}


@app.get("/languages/{tag}")
def language(tag: str) -> dict:
    s = get_scheme(settings.scheme)
    lang = s.get(tag)
    if lang is None:
        raise HTTPException(404, f"Unknown tag {tag!r} in scheme {s.meta.name!r}")
    macro = s.macro_for(tag)
    return {
        "language": lang,
        "class_members": s.classes().get(lang.cls, []),
        "variants": s.variants_of(tag),
        "inherits_from": macro.tag if macro else None,
    }


# -- results -----------------------------------------------------------------

@app.get("/results")
def results(
    engine: str | None = Query(None),
    tier: str | None = Query(None),
    evidence: str | None = Query(None),
    q: str | None = Query(None, description="substring match on tag or language name"),
) -> dict:
    rows = results_store.load_results()
    if engine:
        rows = [r for r in rows if r.get("engine") == engine]
    if tier:
        rows = [r for r in rows if r.get("tier") == tier]
    if evidence:
        rows = [r for r in rows if r.get("evidence") == evidence]
    if q:
        ql = q.lower()
        rows = [r for r in rows
                if ql in r.get("tag", "").lower()
                or ql in (r.get("language", {}).get("name") or "").lower()]
    return {"summary": results_store.summarise(rows), "items": rows}


@app.get("/results/{engine}/{tag}")
def result_detail(engine: str, tag: str) -> dict:
    rows = [r for r in results_store.load_results()
            if r.get("engine") == engine and r.get("tag") == tag]
    if not rows:
        raise HTTPException(404, f"No result for {tag!r} on {engine!r}")
    return rows[-1]


@app.get("/", include_in_schema=False)
def index():
    page = STATIC / "index.html"
    if not page.exists():
        return {"message": "UI not installed", "docs": "/docs"}
    return FileResponse(page)
