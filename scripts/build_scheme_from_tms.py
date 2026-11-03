#!/usr/bin/env python3
"""Turn a TMS locale list into a scheme the core can read.

The core speaks canonical BCP-47 (`ace-Arab`, `ar-EG`); this particular TMS
writes `ace-id-arab` -- lowercase, region before script. That mismatch is what
`scheme.loader.SchemeAdapter` exists for, and this is the concrete adapter for
it: a build step rather than a runtime translation, so the mapping is a file
somebody can read and correct rather than a function nobody can see the output
of.

Two things the generated scheme does on purpose:

**It is keyed by the TMS tag, not the canonical one.** Results come back keyed
to the tags the operator actually uses -- the promise in the README -- and all
602 locales appear as 602 rows rather than collapsing onto the ~200 canonical
tags behind them. `ar-eg` and `ar-dz` are different rows in the locale list and
different rows in the support table, even when one measurement serves both.

**`cls` comes from the canonical language.** The equivalence class is what the
ladder collapses on, so `ar-eg`, `ar-dz` and `ar-il` are probed once and the
rest inherit -- which is exactly the `supported-via-dialect` status. Getting
this wrong would either re-probe one language eleven times or report eleven
untested rows as measured.

Every entry records the canonical tag it resolved to in `aliases`, which is how
the support table finds measurements taken before this scheme existed (the
602-locale scan ran against the default catalogue, keyed canonically).

    python scripts/build_scheme_from_tms.py languages/languages.json --name catmint
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from llmlc.scheme import load_scheme  # noqa: E402
from llmlc.scheme.model import Language, Scheme, SchemeMeta  # noqa: E402


def canonical_candidates(key: str, entry: dict) -> list[str]:
    """Spellings to try against the reference catalogue, most specific first.

    Most specific first because `ace-Arab` and `ace` are both real and mean
    different things: resolving the Arabic-script row onto plain `ace` would
    attach it to a measurement of the Latin-script language.
    """
    lang = (entry.get("ll") or entry.get("lll") or key.split("-")[0]).strip()
    script = (entry.get("script") or entry.get("script_ref") or "").strip().title()
    region = (entry.get("cc") or "").strip().upper()
    out = [key, (entry.get("tag") or "").strip()]
    if lang and script and region:
        out.append(f"{lang}-{script}-{region}")
    if lang and script:
        out.append(f"{lang}-{script}")
    if lang and region:
        out.append(f"{lang}-{region}")
    if lang:
        out.append(lang)
    # The ISO 639-3 code is the last resort: it is the identity the reference
    # catalogue is built on, and some TMS tags use a 639-1 code the catalogue
    # files under its 639-3 equivalent.
    if entry.get("lll"):
        out.append(entry["lll"])
    return [x for x in dict.fromkeys(out) if x]


def build(src: pathlib.Path, name: str, reference: str = "default") -> tuple[Scheme, dict]:
    raw = json.loads(src.read_text(encoding="utf-8"))
    ref = load_scheme(reference)

    by_iso3: dict[tuple[str, str], str] = {}
    #: Last resort: the ISO 639-3 **macrolanguage mapping**, which the catalogue
    #: already carries. A TMS that names `zsm` (Standard Malay) or `khk` (Halh
    #: Mongolian) is naming a member of a macrolanguage the catalogue files
    #: under `ms` and `mn`, and that relationship is data rather than a guess.
    #:
    #: Two earlier attempts matched on the ISO code alone and are why this uses
    #: the mapping instead: picking the shortest tag resolved `cmn-cn` to
    #: Chinese *Braille* and `arb-latn` to Arabic in *Hebrew* script, and
    #: restricting it to codes with a single spelling still resolved `zsm-my` to
    #: Malay Braille -- because the only `zsm` tag in the catalogue is the
    #: Braille one. Each would have attached a locale to the wrong equivalence
    #: class and inherited a measurement from it: a wrong answer wearing the
    #: clothes of a right one, invisible in the output. An unresolved locale is
    #: still scannable; a misresolved one is a false claim.
    macro_base: dict[str, str] = {}
    for tag, lang in ref.languages.items():
        for member in lang.members:
            # Only the unqualified spelling. `ms` is Malay; `ms-Arab` is a
            # script variant of it and is not what `zsm` means.
            if "-" not in tag:
                macro_base.setdefault(member, tag)

    languages: dict[str, Language] = {}
    stats = {"total": len(raw), "resolved": 0, "unresolved": [], "by_candidate": 0,
             "by_iso3": 0, "by_macro": []}

    for key, entry in raw.items():
        match = None
        for cand in canonical_candidates(key, entry):
            if (found := ref.get(cand)) is not None:
                match, stats["by_candidate"] = found, stats["by_candidate"] + 1
                break
        if match is None:
            iso3 = (entry.get("lll") or "").strip()
            script = (entry.get("script") or entry.get("script_ref") or "").strip().title()
            tag = by_iso3.get((iso3, script)) or by_iso3.get((iso3, ""))
            if tag:
                match, stats["by_iso3"] = ref.get(tag), stats["by_iso3"] + 1
            elif (base := macro_base.get(iso3)):
                # A member code naming a macrolanguage the catalogue knows. Try
                # the entry's own script and region against the macro's spelling
                # before falling back to the bare tag, so `quz-bo` reaches
                # `qu-BO` rather than stopping at `qu`.
                for cand in canonical_candidates(base, {**entry, "ll": base, "lll": base}):
                    if (found := ref.get(cand)) is not None:
                        match = found
                        stats["by_macro"].append((key, found.tag))
                        break

        iso3 = (entry.get("lll") or (match.iso639_3 if match else None) or "").strip() or None
        script = ((entry.get("script") or entry.get("script_ref") or "").strip().title()
                  or (match.script if match else None) or None)
        if match is None:
            stats["unresolved"].append(key)
        else:
            stats["resolved"] += 1

        languages[key] = Language(
            tag=key,
            full=(entry.get("tag") or key),
            lang=(entry.get("ll") or iso3 or key.split("-")[0]),
            iso639_3=iso3,
            iso639_1=(entry.get("ll") or None),
            script=script,
            region=((entry.get("cc") or "").strip().upper() or None),
            # The TMS names its own countries; fall back to the catalogue's.
            region_name=((entry.get("country") or "").strip()
                         or (match.region_name if match else None) or None),
            name=(entry.get("name") or entry.get("title") or key),
            local_name=(match.local_name if match else None),
            scope=("macrolanguage" if entry.get("inclusive")
                   else (match.scope if match else "individual")),
            type=(match.type if match else None),
            macro=(match.macro if match else None),
            members=(match.members if match else []),
            # The ladder collapses on this, so it must come from the canonical
            # language: eleven Arabic locales are one experiment, not eleven.
            cls=(match.cls if match else f"{iso3 or key}|{script or ''}"),
            aliases=([match.tag] if match and match.tag != key else []),
        )

    meta = SchemeMeta(
        name=name,
        description=f"TMS locale list from {src.name}, mapped onto canonical BCP-47",
        canonical_tag_format="tms",
        generated_at=datetime.now(timezone.utc).isoformat(),
        generator="scripts/build_scheme_from_tms.py",
        sources={"locale_list": str(src), "reference_catalogue": reference},
        counts={"languages": len(languages), "resolved": stats["resolved"],
                "unresolved": len(stats["unresolved"]),
                "classes": len({l.cls for l in languages.values()})},
    )
    return Scheme(meta=meta, languages=languages), stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="the TMS locale list (JSON)")
    ap.add_argument("--name", default="tms", help="scheme name; writes schemes/<name>.json")
    ap.add_argument("--reference", default="default", help="catalogue to resolve against")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    src = pathlib.Path(a.source)
    if not src.exists():
        print(f"No such file: {src}", file=sys.stderr)
        return 2

    scheme, stats = build(src, a.name, a.reference)
    print(f"{stats['total']} locale(s)  "
          f"resolved {stats['resolved']} "
          f"({stats['by_candidate']} by tag, {stats['by_iso3']} by ISO 639-3, "
          f"{len(stats['by_macro'])} by macrolanguage)  "
          f"unresolved {len(stats['unresolved'])}")
    print(f"{scheme.meta.counts['classes']} equivalence class(es) — what a scan actually probes")
    if stats["by_macro"]:
        print(f"\nresolved through the ISO 639-3 macrolanguage mapping "
              f"({len(stats['by_macro'])}) — a member code filed under its macrolanguage:")
        for key, tag in stats["by_macro"]:
            print(f"  {key:12} -> {tag}")
    if stats["unresolved"]:
        # Named, not counted. An unresolved locale still appears in the scheme and
        # is still scannable; it just has no canonical twin, so it cannot inherit
        # a measurement taken under the reference catalogue's spelling.
        print("\nunresolved (kept, but cannot inherit an existing measurement):")
        for k in stats["unresolved"]:
            print(f"  {k}")
    if a.dry_run:
        return 0

    out = pathlib.Path("schemes") / f"{a.name}.json"
    out.write_text(json.dumps(scheme.model_dump(mode="json"), ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"\nwrote {out}  —  use it with SCHEME={a.name} or ?scheme={a.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
