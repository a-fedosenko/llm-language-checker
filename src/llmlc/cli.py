"""Command line entry point."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from llmlc.bt import RemoteBackTranslator
from llmlc.client import OpenAICompatClient
from llmlc.config import settings
from llmlc.export import write as write_artifacts
from llmlc.probe.corpus import Corpus
from llmlc.probe.pipeline import check_language
from llmlc.probe.specs import load_specs
from llmlc.scheme import load_scheme

GREY, BOLD, RESET = "\033[90m", "\033[1m", "\033[0m"


def cmd_check(a: argparse.Namespace) -> int:
    if not settings.aggregator_base_url or not settings.aggregator_admin_api_key:
        print("No endpoint configured. Copy .env.example to .env and fill it in.", file=sys.stderr)
        return 2
    if a.backtranslator == a.engine:
        print("Back-translator must differ from the model under test "
              "(otherwise the round trip measures self-consistency).", file=sys.stderr)
        return 2

    scheme = load_scheme(a.scheme or settings.scheme)
    specs = load_specs()[: a.items]
    client = OpenAICompatClient(settings.aggregator_base_url, settings.aggregator_admin_api_key)
    bt = RemoteBackTranslator(client, a.backtranslator, a.pivot)

    with Corpus() as corpus:
        result = check_language(
            scheme=scheme, tag=a.tag, engine=a.engine, client=client,
            backtranslator=bt, judge_model=a.judge or settings.judge_model,
            specs=specs, corpus=corpus, pivot=a.pivot,
        )
        corpus_path = corpus.path

    s = result.score
    lang = result.language
    print(f"\n{BOLD}{lang.name or a.tag}{RESET}  [{a.tag}]  via {result.engine}")
    q = result.qualification
    print(f"{GREY}designator{RESET} {result.designator!r}   "
          f"{GREY}pivot{RESET} {result.pivot}   {GREY}bt{RESET} {result.backtranslator} "
          f"[{q.status.value}{f' {q.recall:.0%}' if q.status.value == 'qualified' else ''}]")
    print(f"\n  {BOLD}{s.tier.value}{RESET}"
          f"{'  (borderline)' if s.borderline else ''}   — {s.workflow}")
    print(f"  s_lang {s.s_lang:.2f}   s_content {s.s_content:.2f}   "
          f"90% CI [{s.ci[0]:.2f}, {s.ci[1]:.2f}]   evidence: {s.evidence.value}")
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

    sup, ev = write_artifacts(result, pathlib.Path(a.out))
    print(f"\n{GREY}support {RESET}{sup}\n{GREY}evidence{RESET} {ev}\n{GREY}corpus  {RESET}{corpus_path}")
    return 0


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
    c.add_argument("--tag", required=True, help="canonical BCP-47 tag, e.g. cv")
    c.add_argument("--engine", required=True, help="model under test")
    c.add_argument("--backtranslator", default="gemini-gemini-3-8-flash",
                   help="must differ from --engine")
    c.add_argument("--judge", default=None)
    c.add_argument("--pivot", default="en")
    c.add_argument("--items", type=int, default=3, help="number of content specs to run")
    c.add_argument("--scheme", default=None)
    c.add_argument("--out", default="data/results")
    c.add_argument("-v", "--verbose", action="store_true")
    c.set_defaults(func=cmd_check)

    l = sub.add_parser("languages", help="search the loaded scheme")
    l.add_argument("query", nargs="?", default=None)
    l.add_argument("--scheme", default=None)
    l.add_argument("--limit", type=int, default=25)
    l.set_defaults(func=cmd_languages)

    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
