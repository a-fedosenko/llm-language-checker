"""Command line entry point."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from llmlc import runner
from llmlc.bt import QualificationCache, RemoteBackTranslator
from llmlc.client import OpenAICompatClient
from llmlc.config import settings
from llmlc.db import create_all, session
from llmlc.db.repo import results_for, stale
from llmlc.export import write as write_artifacts
from llmlc.export.adapters import CanonicalAdapter, MappedAdapter, build_support, merge_support
from llmlc.export.artifacts import METHOD_VERSION
from llmlc.probe.corpus import Corpus
from llmlc.probe.pipeline import check_language
from llmlc.probe.scan import plan
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
    req = runner.ScanRequest(
        engine=a.engine, tags=[], scheme=a.scheme, backtranslator=a.backtranslator,
        judge=a.judge, pivot=a.pivot, max_calls=a.max_calls, sweep_all=a.sweep_all,
        out=a.out)
    scheme = load_scheme(a.scheme or settings.scheme)
    req.tags = _resolve_tags(scheme, a)

    groups, unknown = plan(scheme, req.tags)
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

    try:
        job_id = runner.create(req)
    except runner.ScanRefused as e:
        print(str(e), file=sys.stderr)
        return 2
    print(f"{GREY}job {job_id}{RESET}")

    def progress(r):
        mark = f"{GREY}inherited{RESET}" if r.inherited_from else f"r{r.rungs_run}"
        print(f"  {r.tag:14}{r.score.tier.value:9}{r.score.evidence.value:24}{mark}")

    outcome = runner.execute(req, job_id, on_result=progress)
    result = outcome.result

    calls = result.calls
    total = sum(calls.values())
    if result.unknown:
        print(f"{GREY}skipped (not in scheme): {', '.join(result.unknown)}{RESET}")
    print(f"\n{BOLD}scan{RESET} {len(result.results)} tag(s) in {result.seconds:.0f}s"
          f"{f'  (stopped: {result.stop_reason})' if result.stopped_early else ''}")
    print(f"  classes probed {result.classes_probed}   inherited {result.tags_inherited}")
    print(f"  calls: {total}  ({calls['generation']} gen, {calls['backtranslation']} bt, "
          f"{calls['judge']} judge)   {total / max(1, len(result.results)):.1f} per tag")
    _summarise(result.results)

    sup, ev = outcome.artifacts or ("-", "-")
    print(f"\n{GREY}support {RESET}{sup}\n{GREY}evidence{RESET} {ev}"
          f"\n{GREY}corpus  {RESET}{outcome.corpus_path}   {GREY}job{RESET} {job_id}")
    return 0


def cmd_status(a: argparse.Namespace) -> int:
    """What has been measured, and what is out of date."""
    create_all()
    with session() as s:
        rows = results_for(s, engine=a.engine)
        behind = stale(s, METHOD_VERSION, engine=a.engine)
    if not rows:
        print("No results yet. Run `llmlc scan --engine <model> --tag de,fr`.")
        return 0

    by_engine: dict[str, list] = {}
    for r in rows:
        by_engine.setdefault(r.engine, []).append(r)

    print(f"{BOLD}method {METHOD_VERSION}{RESET}   {len(rows)} result(s)\n")
    for engine, rs in sorted(by_engine.items()):
        tiers: dict[str, int] = {}
        for r in rs:
            tiers[r.tier] = tiers.get(r.tier, 0) + 1
        unver = sum(1 for r in rs if r.evidence == "unverified")
        inh = sum(1 for r in rs if r.inherited_from)
        print(f"  {BOLD}{engine}{RESET}  {len(rs)} tag(s)")
        print(f"    {'  '.join(f'{k} {v}' for k, v in sorted(tiers.items()))}")
        print(f"    {GREY}unverified {unver} · inherited {inh}{RESET}")

    if behind:
        print(f"\n{BOLD}stale{RESET}  {len(behind)} result(s) measured under an older method")
        print(f"  re-run with: llmlc scan --engine <model> --tag "
              f"{','.join(sorted({r.tag for r in behind})[:8])}...")
    else:
        print(f"\n{GREY}nothing stale{RESET}")
    return 0


def cmd_export(a: argparse.Namespace) -> int:
    """Produce the mergeable artifact, optionally merged into an existing file."""
    create_all()
    with session() as s:
        rows = [{"tag": r.tag, "engine": r.engine, "tier": r.tier,
                 "designator": r.designator} for r in results_for(s, engine=a.engine)]
    if not rows:
        print("No results to export.", file=sys.stderr)
        return 1

    adapter = CanonicalAdapter()
    if a.map:
        mapping = json.loads(pathlib.Path(a.map).read_text(encoding="utf-8"))
        adapter = MappedAdapter(pathlib.Path(a.map).stem, mapping)

    support = build_support(rows, adapter)
    target = pathlib.Path(a.out)
    if a.merge_into:
        existing = json.loads(pathlib.Path(a.merge_into).read_text(encoding="utf-8"))
        before = len(existing)
        support = merge_support(existing, support)
        print(f"{GREY}merged into {a.merge_into}: {before} -> {len(support)} key(s); "
              f"nothing removed{RESET}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(support, ensure_ascii=False, indent=1), encoding="utf-8")
    claimed = sum(1 for v in support.values() if v)
    print(f"wrote {target}  {len(support)} key(s), {claimed} with at least one engine")
    return 0


def cmd_calibrate(a: argparse.Namespace) -> int:
    """The calibration study: fact recall against chrF++ on the same translation.

    The one command that measures the instrument rather than a language.
    """
    import json
    from llmlc.probe.calibrate import calibrate_language, correlate, load_specs

    if not settings.aggregator_base_url or not settings.aggregator_admin_api_key:
        print("No endpoint configured. Copy .env.example to .env and fill it in.",
              file=sys.stderr)
        return 2

    specs = load_specs()
    if not specs:
        print("No calibration specs. Build them first:\n"
              "  python scripts/build_calibration_specs.py --tags af,ru,cv",
              file=sys.stderr)
        return 2

    scheme = load_scheme(a.scheme or settings.scheme)
    tags = ([t.strip() for t in a.tag.split(",") if t.strip()] if a.tag
            else sorted(specs))
    tags = [t for t in tags if t in specs]
    if a.limit:
        tags = tags[: a.limit]
    if not tags:
        print("None of the requested tags have calibration specs.", file=sys.stderr)
        return 2

    panel = [m.strip() for m in a.backtranslator.split(",")
             if m.strip() and m.strip() != a.engine]
    if not panel:
        print("No back-translator left after excluding the model under test.", file=sys.stderr)
        return 2

    client = OpenAICompatClient(settings.aggregator_base_url, settings.aggregator_admin_api_key)
    bts = [RemoteBackTranslator(client, m, a.pivot) for m in panel]
    judge = a.judge or settings.judge_model

    est = sum(min(len(specs[t]["items"]), a.items or 99) for t in tags) * 3
    print(f"{BOLD}{len(tags)}{RESET} language(s)   "
          f"{GREY}~{est} calls (translate + back-translate + judge per item){RESET}")
    if a.dry_run:
        for t in tags:
            print(f"  {t:10} {len(specs[t]['items'])} item(s)")
        return 0

    results = []
    print(f"\n  {'tag':10}{'chrF++':>9}{'recall':>9}{'paired':>9}")
    with Corpus(to_db=True) as corpus:
        for tag in tags:
            r = calibrate_language(
                scheme=scheme, tag=tag, engine=a.engine, client=client,
                backtranslators=bts, judge_model=judge, spec=specs[tag],
                corpus=corpus, pivot=a.pivot, n_items=a.items)
            results.append(r)
            c = f"{r.mean_chrf:.1f}" if r.mean_chrf is not None else "—"
            rec = f"{r.mean_recall:.2f}" if r.mean_recall is not None else "—"
            print(f"  {tag:10}{c:>9}{rec:>9}{len(r.paired):>9}")
        corpus_path = corpus.path

    stats = correlate(results)
    print(f"\n{BOLD}correlation{RESET}  {stats['n_items']} paired item(s), "
          f"{stats['n_languages']} language(s)")
    print(f"  item-level Spearman     {stats['item_spearman']}")
    print(f"  language-level Spearman {stats['language_spearman']}")
    print(f"  mean offset (recall - chrF++/100) {stats['mean_offset_recall_minus_chrf']}")
    for band, d in stats["offset_by_band"].items():
        print(f"    {band:12} n={d['n']:3}  offset {d['mean']:+.3f}")

    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"engine": a.engine, "judge": judge, "pivot": a.pivot,
                               "correlation": stats,
                               "languages": [r.as_dict() for r in results]},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{GREY}study  {RESET}{out}\n{GREY}corpus {RESET}{corpus_path}")
    return 0


def cmd_markers(a: argparse.Namespace) -> int:
    """Variant coverage: what is decided, and what is still a gap."""
    from llmlc.probe.markers import coverage, load_markers

    scheme = load_scheme(a.scheme or settings.scheme)
    sets = load_markers()
    c = coverage(scheme)

    print(f"{BOLD}variant coverage{RESET}  scheme {scheme.meta.name!r}")
    print(f"  {c['variant_tags']} variant tag(s) in multi-tag classes")
    print(f"    {BOLD}{c['markers']}{RESET} with marker sets")
    print(f"    {BOLD}{c['not_distinguishable']}{RESET} declared not-distinguishable")
    print(f"    {BOLD}{c['untested']}{RESET} untested  {GREY}(a tracked gap, not a claim){RESET}")

    if not a.verbose:
        print(f"\n{GREY}marker sets on disk{RESET}")
    for tag, ms in sorted(sets.items()):
        review = "" if ms.reviewed else f"  {GREY}unreviewed{RESET}"
        if ms.status == "not-distinguishable":
            print(f"  {tag:10} not-distinguishable  {GREY}{(ms.note or '')[:52]}{RESET}{review}")
            continue
        axes = ", ".join(f"{ax.axis} {len(ax.variant)}v/{len(ax.sibling)}s" for ax in ms.markers)
        print(f"  {tag:10} markers  vs {ms.sibling or '?':8} "
              f"{len(ms.elicitation)} context(s)  {GREY}{axes}{RESET}{review}")
        if a.verbose:
            for ax in ms.markers:
                print(f"      {ax.axis:12} {', '.join(ax.variant[:8])}")
                print(f"      {'':12} {GREY}vs {', '.join(ax.sibling[:8])}{RESET}")
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

    st = sub.add_parser("status", help="what has been measured, and what is stale")
    st.add_argument("--engine", default=None)
    st.set_defaults(func=cmd_status)

    ex = sub.add_parser("export", help="write the mergeable support artifact")
    ex.add_argument("--engine", default=None)
    ex.add_argument("--map", default=None,
                    help="JSON map canonical->external tag, for another system's scheme")
    ex.add_argument("--merge-into", default=None, help="existing master file to merge into")
    ex.add_argument("--out", default="data/results/support.json")
    ex.set_defaults(func=cmd_export)

    cal = sub.add_parser("calibrate",
                         help="calibration study: fact recall vs chrF++ on the same translation")
    cal.add_argument("--engine", required=True, help="model under test")
    cal.add_argument("--tag", default=None, help="comma-separated tags; omit for every spec")
    cal.add_argument("--items", type=int, default=None, help="items per language")
    cal.add_argument("--limit", type=int, default=None, help="cap the number of languages")
    cal.add_argument("--backtranslator",
                     default="gemini-gemini-3-8-flash,deepseek-deepseek-v4-pro")
    cal.add_argument("--judge", default=None)
    cal.add_argument("--pivot", default="en")
    cal.add_argument("--scheme", default=None)
    cal.add_argument("--dry-run", action="store_true", help="print the plan and an estimate")
    cal.add_argument("--out", default="data/calibration/study.json")
    cal.set_defaults(func=cmd_calibrate)

    mk = sub.add_parser("markers", help="variant marker coverage and the remaining gap")
    mk.add_argument("--scheme", default=None)
    mk.add_argument("-v", "--verbose", action="store_true", help="print the marker lists")
    mk.set_defaults(func=cmd_markers)

    l = sub.add_parser("languages", help="search the loaded scheme")
    l.add_argument("query", nargs="?", default=None)
    l.add_argument("--scheme", default=None)
    l.add_argument("--limit", type=int, default=25)
    l.set_defaults(func=cmd_languages)

    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
