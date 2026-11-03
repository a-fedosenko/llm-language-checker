"""One model, every locale in a scheme, one row each.

Two things make this more than a SELECT.

**A scheme is the left side of the join.** The table answers "what does this
model do with *my* locale list", so every tag in the active scheme appears,
including the ones nothing has ever been measured for. Those are `unchecked`,
which is a real answer and the one that tells you what is left to do.

**One row per language means choosing a reader.** `gpt-4o` holds 500 result rows
across five back-translators, because re-running an engine through a new reader
adds rows rather than replacing them (convention 4, and deliberate). A table
promising one row per language has to pick, and `_pick` says how -- then reports
what it collapsed, because silently showing one of five is how a reader comes to
believe there was only ever one.
"""
from __future__ import annotations

from llmlc import runner
from llmlc.support import ORDER, Status, row_for

#: Readers in the order they are preferred, best first. The panel order is a
#: measured property -- gemini-3-6-flash is the stronger reader at the hard end
#: (S8) -- so preferring it is preferring the better instrument, not an arbitrary
#: tiebreak.
PANEL_ORDER = [m.strip() for m in runner.DEFAULT_PANEL.split(",") if m.strip()]


def _reader_rank(backtranslator: str | None) -> int:
    """Lower is better. Panel members in panel order, then the no-instrument
    rows, then anything else.

    `NO_INSTRUMENT` ranks after real readers rather than first: it marks a
    deterministic negative, which is comparable against every back-translator
    (convention 14), so it is never *wrong* to show -- but where the same tag
    has also been read by a qualified panel member, the reading is the more
    informative row.
    """
    from llmlc.db.models import NO_INSTRUMENT

    bt = backtranslator or ""
    if bt == NO_INSTRUMENT:
        return len(PANEL_ORDER)
    for i, member in enumerate(PANEL_ORDER):
        # Stored ids carry a transport prefix and may carry a pivot suffix
        # (`remote:model@de`), so match on the model name inside them.
        if member in bt:
            return i
    return len(PANEL_ORDER) + 1


def _pick(rows: list):
    """The canonical row for one tag: best reader, then most recently measured."""
    return min(rows, key=lambda r: (_reader_rank(r.backtranslator),
                                    -(r.id or 0)))


def _results_for_engine(engine: str) -> dict[str, list]:
    from sqlalchemy import select

    from llmlc.db import session
    from llmlc.db.models import Result

    by_tag: dict[str, list] = {}
    with session() as s:
        for r in s.scalars(select(Result).where(Result.engine == engine)):
            by_tag.setdefault(r.tag, []).append(r)
    return by_tag


def build(engine: str, scheme_name: str | None = None) -> dict:
    """The whole table for one engine, plus per-status counts."""
    from llmlc.config import settings
    from llmlc.scheme import load_scheme

    scheme = load_scheme(scheme_name or settings.scheme)
    try:
        by_tag = _results_for_engine(engine)
    except Exception:  # noqa: BLE001 -- no database is an empty table, not a 500
        by_tag = {}

    rows, collapsed = [], 0
    for tag, lang in scheme.languages.items():
        # Aliases carry the canonical spelling a user's own scheme was mapped
        # from, so a locale list measured before that scheme existed still finds
        # its results. The 602-locale scan ran against the default catalogue and
        # is keyed canonically; `ar-eg` has to reach a row stored as `ar`.
        own = by_tag.get(tag) or []
        borrowed: dict[int, str] = {}
        candidates = list(own)
        for alias in lang.aliases:
            if alias == tag:
                continue
            for r in by_tag.get(alias) or []:
                borrowed[id(r)] = alias
                candidates.append(r)
        chosen = _pick(candidates) if candidates else None
        collapsed += max(0, len(candidates) - 1)
        rows.append(row_for(tag, chosen, lang,
                            borrowed_from=borrowed.get(id(chosen))).as_dict())

    rows.sort(key=lambda r: (r["name"] or r["tag"]).lower())
    counts = {s.value: 0 for s in ORDER}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {
        "engine": engine,
        "scheme": scheme.meta.name,
        "total": len(rows),
        "counts": counts,
        # Named rather than hidden: a non-zero value means this engine has been
        # measured through more than one reader, and the table is showing the
        # best one per language.
        "rows_collapsed": collapsed,
        "readers_preferred": PANEL_ORDER,
        "rows": rows,
    }
