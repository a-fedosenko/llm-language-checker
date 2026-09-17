"""Command line entry point."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from llmlc.bt import QualificationCache, RemoteBackTranslator
from llmlc.client import OpenAICompatClient
from llmlc.config import settings
from llmlc.export import write as write_artifacts
from llmlc.probe.corpus import Corpus
from llmlc.probe.pipeline import check_language
from llmlc.probe.scan import ScanBudget, plan, scan
from llmlc.probe.specs import load_specs
from llmlc.scheme import load_scheme

GREY, BOLD, RESET = "\033[90m", "\033[1m", "\033[0m"


def _summarise(results) -> None:
    from llmlc.probe.score import Evidence
    print(f"\n{BOLD}summary{RESET}  {len(results)} language(s)")
    print(f"  {'tag':10}{'tier':10}{'evidence':24}{'content':>9}{'reliab':>9}  designator")
    for r in results:
        rel = f"{r.score.reliability:.2f}" if r.score.reliability < 1.0 else "-"
        print(f"  {r.tag:10}{r.score.tier.value:10}{r.score.evidence.value:24}"
              f"{r.score.s_content:>9.2f}{rel:>9}  {getattr(r, 'designator', '')[:32]}")
    unverified = sum(r.score.evidence is Evidence.UNVERIFIED for r in results)
    real = len(results) - unverified
    print(f"\n  real evidence: {real}/{len(results)}   unverified: {unverified}")


def cmd_check(a: argparse.Namespace) -> int:
    if not settings.aggregator_base_url or not settings.aggregator_admin_api_key:
        print("No endpoint configured. Copy .env.example to .env and fill it in.", file=sys.stderr)
        return 2
    panel = [m.strip() for m in a.backtranslator.split(",") if m.strip()]
    rejected = [m for m in panel if m == a.engine]
    panel = [m for m in panel if m != a.engine]
    if rejected:
        print(f"{GREY}skipping {', '.join(rejected)} as back-translator: same as the model "
              f"under test, which would measure self-consistency{RESET}", file=sys.stderr)
    if not panel:
        print("No back-translator left after excluding the model under test.", file=sys.stderr)
        return 2

    scheme = load_scheme(a.scheme or settings.scheme)
    specs = load_specs()[: a.items]
    client = OpenAICompatClient(settings.aggregator_base_url, settings.aggregator_admin_api_key)
    bts = [RemoteBackTranslator(client, m, a.pivot) for m in panel]
    cache = QualificationCache()

    tags = [t.strip() for t in a.tag.split(",") if t.strip()]
    results = []
    with Corpus() as corpus:
        for tag in tags:
            try:
                results.append(check_language(
                    scheme=scheme, tag=tag, engine=a.engine, client=client,
                    backtranslators=bts, judge_model=a.judge or settings.judge_model,
                    specs=specs, corpus=corpus, pivot=a.pivot, cache=cache,
                ))
            except KeyError as e:
                print(f"  {tag}: {e}", file=sys.stderr)
        corpus_path = corpus.path

    for result in results:
        _report(result, a)
    if len(results) > 1:
        _summarise(results)
    for result in results:
        sup, ev = write_artifacts(result, pathlib.Path(a.out))
    if results:
        print(f"\n{GREY}support {RESET}{sup}\n{GREY}evidence{RESET} {ev}"
              f"\n{GREY}corpus  {RESET}{corpus_path}")
    return 0


def _report(result, a) -> None:
    s = result.score
    lang = result.language
    print(f"\n{BOLD}{lang.name or a.tag}{RESET}  [{a.tag}]  via {result.engine}")
    q = result.qualification
    print(f"{GREY}designator{RESET} {result.designator!r}   "
          f"{GREY}pivot{RESET} {result.pivot}   {GREY}bt{RESET} {result.backtranslator} "
          f"[{q.status.value}"
          f"{f' {q.kind} {q.score:.0f}' if q.status.value != 'no-control' else ''}]")
    print(f"\n  {BOLD}{s.tier.value}{RESET}"
          f"{'  (borderline)' if s.borderline else ''}   — {s.workflow}")
    print(f"  s_lang {s.s_lang:.2f}   s_content {s.s_content:.2f}   "
          f"90% CI [{s.ci[0]:.2f}, {s.ci[1]:.2f}]   evidence: {s.evidence.value}")
    if s.reliability < 1.0:
        print(f"  reliability {s.reliability:.2f}  ({s.refusals} refusal(s) of {s.n_items})")
    if result.resolves_to:
        print(f"  resolves_to: {result.resolves_to}")
    for note in s.notes:
        print(f"  note: {note}")

    print(f"\n{GREY}items{RESET}")
    for i in result.items:
        content = f"{i.content:.2f}" if i.content is not None else "  — "
        detail = f"  {GREY}{i.gate.detail[:52]}{RESET}" if i.gate.detail else ""
        print(f"  {i.spec_id:22} gate={i.gate.verdict.value:22} content={content}{detail}")
        if a.verbose and i.generation:
            print(f"      {GREY}out:{RESET} {i.generation[:100].replace(chr(10),' ')}")
            if i.back_translation:
                print(f"      {GREY}bt :{RESET} {i.back_translation[:100].replace(chr(10),' ')}")


def cmd_scan(a: argparse.Namespace) -> int:
    if not settings.aggregator_base_url or not settings.aggregator_admin_api_key:
        print("No endpoint configured. Copy .env.example to .env and fill it in.", file=sys.stderr)
        return 2

    scheme = load_scheme(a.scheme or settings.scheme)
    tags = _resolve_tags(scheme, a)
    if not tags:
        print("No languages selected.", file=sys.stderr)
        return 2

    groups, unknown = plan(scheme, tags)
    known = sum(len(m) for m in groups.values())
    print(f"{BOLD}{known}{RESET} tag(s) -> {BOLD}{len(groups)}{RESET} class(es) "
          f"({known - len(groups)} inherit without further calls)")
    if unknown:
        print(f"{GREY}not in scheme {scheme.meta.name!r}, skipped: "
              f"{', '.join(unknown)}{RESET}", file=sys.stderr)
    if a.dry_run:
        for cls, members in list(groups.items())[: a.limit or len(groups)]:
            print(f"  {cls:22} probe {members[0]:12} inherit: {', '.join(members[1:]) or '-'}")
        est = len(groups) * (3 + 3 + 3)
        print(f"\n{GREY}rough upper bound if nothing prunes: ~{est} calls{RESET}")
        return 0

    panel = [m.strip() for m in a.backtranslator.split(",") if m.strip() and m.strip() != a.engine]
    client = OpenAICompatClient(settings.aggregator_base_url, settings.aggregator_admin_api_key)
    bts = [RemoteBackTranslator(client, m, a.pivot) for m in panel]
    cache = QualificationCache()
    budget = ScanBudget(max_calls=a.max_calls)

    def progress(r):
        mark = f"{GREY}inherited{RESET}" if r.inherited_from else f"r{r.rungs_run}"
        print(f"  {r.tag:14}{r.score.tier.value:9}{r.score.evidence.value:24}{mark}")

    with Corpus() as corpus:
        result = scan(scheme=scheme, tags=tags, engine=a.engine, client=client,
                      backtranslators=bts, judge_model=a.judge or settings.judge_model,
                      specs=load_specs(), corpus=corpus, pivot=a.pivot,
                      sweep_all=a.sweep_all, cache=cache, budget=budget,
                      on_result=progress)
        corpus_path = corpus.path

    calls = result.calls
    total = sum(calls.values())
    if result.unknown:
        print(f"{GREY}skipped (not in scheme): {', '.join(result.unknown)}{RESET}")
    print(f"\n{BOLD}scan{RESET} {len(result.results)} tag(s) in {result.seconds:.0f}s"
          f"{'  (stopped: budget)' if result.stopped_early else ''}")
    print(f"  classes probed {result.classes_probed}   inherited {result.tags_inherited}")
    print(f"  calls: {total}  ({calls['generation']} gen, {calls['backtranslation']} bt, "
          f"{calls['judge']} judge)   {total / max(1, len(result.results)):.1f} per tag")
    _summarise(result.results)

    for r in result.results:
        sup, ev = write_artifacts(r, pathlib.Path(a.out))
    print(f"\n{GREY}support {RESET}{sup}\n{GREY}evidence{RESET} {ev}"
          f"\n{GREY}corpus  {RESET}{corpus_path}")
    return 0


def _resolve_tags(scheme, a) -> list[str]:
    if a.tag:
        return [t.strip() for t in a.tag.split(",") if t.strip()]
    items = list(scheme.languages.values())
    if a.living_only:
        items = [x for x in items if x.type == "L"]
    if a.with_controls:
        from llmlc.bt import load_controls
        have = set(load_controls())
        items = [x for x in items if x.tag in have]
    tags = [x.tag for x in items]
    return tags[: a.limit] if a.limit else tags


def cmd_languages(a: argparse.Namespace) -> int:
    scheme = load_scheme(a.scheme or settings.scheme)
    q = (a.query or "").lower()
    hits = [x for x in scheme.languages.values()
            if not q or q in x.tag.lower() or (x.name and q in x.name.lower())]
    for x in hits[: a.limit]:
        print(f"  {x.tag:14} {x.iso639_3 or '   '}  {x.script or '    '}  "
              f"{(x.name or '')[:38]:40} {x.scope}")
    print(f"{GREY}{len(hits)} match(es){RESET}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="llmlc",
                                description="Empirical checks of which languages a model can produce.")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="measure one language end to end")
    c.add_argument("--tag", required=True,
                   help="canonical BCP-47 tag, or a comma-separated list")
    c.add_argument("--engine", required=True, help="model under test")
    c.add_argument("--backtranslator",
                   default="gemini-gemini-3-8-flash,deepseek-deepseek-v4-pro",
                   help="ordered panel, comma separated; the first that qualifies for the "
                        "language is used. The model under test is excluded automatically.")
    c.add_argument("--judge", default=None)
    c.add_argument("--pivot", default="en")
    c.add_argument("--items", type=int, default=3, help="number of content specs to run")
    c.add_argument("--scheme", default=None)
    c.add_argument("--out", default="data/results")
    c.add_argument("-v", "--verbose", action="store_true")
    c.set_defaults(func=cmd_check)

    sc = sub.add_parser("scan", help="measure many languages with the adaptive ladder")
    sc.add_argument("--engine", required=True, help="model under test")
    sc.add_argument("--tag", default=None, help="comma-separated tags; omit to use filters")
    sc.add_argument("--with-controls", action="store_true",
                    help="only languages that have a back-translator control")
    sc.add_argument("--living-only", action="store_true")
    sc.add_argument("--limit", type=int, default=None)
    sc.add_argument("--backtranslator",
                    default="gemini-gemini-3-8-flash,deepseek-deepseek-v4-pro")
    sc.add_argument("--judge", default=None)
    sc.add_argument("--pivot", default="en")
    sc.add_argument("--sweep-all", action="store_true",
                    help="try every designator candidate even when the first succeeds")
    sc.add_argument("--max-calls", type=int, default=None, help="budget; the scan fails closed")
    sc.add_argument("--dry-run", action="store_true", help="print the plan and an estimate")
    sc.add_argument("--scheme", default=None)
    sc.add_argument("--out", default="data/results")
    sc.set_defaults(func=cmd_scan)

    l = sub.add_parser("languages", help="search the loaded scheme")
    l.add_argument("query", nargs="?", default=None)
    l.add_argument("--scheme", default=None)
    l.add_argument("--limit", type=int, default=25)
    l.set_defaults(func=cmd_languages)

    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
