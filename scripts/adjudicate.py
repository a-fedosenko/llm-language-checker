#!/usr/bin/env python3
"""Protocol 016: a blind third opinion on items where the two metrics disagree.

Protocol 014 treated chrF++ as ground truth. That was never justified: chrF++ is
character overlap with a single reference, so a correct translation that chooses
other words scores low. This asks an independent, language-qualified model
whether the translation is actually adequate, and lets the answer decide which
metric was wrong.

Three guards on who may adjudicate, each for a documented reason:
  qualified      an unqualified reader fabricates rather than refusing (005)
  not the model under test    self-preference bias
  not that item's back-translator   or the two measurements share a failure

Usage:  python scripts/adjudicate.py [--per-stratum 40]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from llmlc.bt import RemoteBackTranslator, load_controls, qualify  # noqa: E402
from llmlc.client import OpenAICompatClient  # noqa: E402
from llmlc.config import settings  # noqa: E402
from llmlc.db import create_all  # noqa: E402
from llmlc.db.qualcache import DbQualificationCache  # noqa: E402
from llmlc.scheme import load_scheme  # noqa: E402

PANEL = ["gemini-gemini-3-8-flash", "deepseek-deepseek-v4-pro"]

PROMPT = """You are checking a translation.

ORIGINAL (English):
{source}

TRANSLATION, which should be in {language}:
{translation}

Answer two questions about the TRANSLATION:

1. adequacy — does it convey what the original says?
     "adequate"    the meaning arrived; wording may differ freely from any
                   particular phrasing, and that is not a fault
     "partial"     some of the meaning arrived, some is lost or altered
     "inadequate"  the meaning did not arrive

2. language — is the text written in {language}?
     "yes"          it is {language}
     "other"        it is a different language
     "wrong-script" it is {language} but not in the expected writing system

Judge only what is in front of you. Reply with JSON only:
{{"adequacy": "...", "language": "...", "why": "<eight words or fewer>"}}"""


def ask(client, model, source, translation, language):
    c = client.complete(model, PROMPT.format(source=source, translation=translation,
                                             language=language), max_tokens=200)
    if not c.ok:
        return {"error": c.error}
    raw = (c.text or "").strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return {"error": "unparseable", "raw": raw[:120]}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"error": "bad json", "raw": raw[:120]}


def strata(study, per):
    """Disagreement cases plus agreement controls at both ends."""
    items = [(L, i) for L in study["languages"] for i in L["items"]
             if i.get("chrf") is not None and i.get("recall") is not None
             and i.get("translation")]
    def pick(pred):
        return [x for x in items if pred(x[1])][:per]
    return {
        "disagree-mid": pick(lambda i: 40 <= i["chrf"] < 60 and i["recall"] >= 0.99),
        "disagree-low": pick(lambda i: i["chrf"] < 20 and i["recall"] >= 0.99),
        "control-good": pick(lambda i: i["chrf"] >= 60 and i["recall"] >= 0.99),
        "control-bad": pick(lambda i: i["chrf"] < 40 and i["recall"] <= 0.34),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study", default="data/calibration/study.json")
    p.add_argument("--per-stratum", type=int, default=40)
    p.add_argument("--out", default="data/calibration/adjudication.json")
    a = p.parse_args(argv)

    if not settings.aggregator_base_url or not settings.aggregator_admin_api_key:
        print("No endpoint configured.", file=sys.stderr)
        return 2

    study = json.loads(pathlib.Path(a.study).read_text(encoding="utf-8"))
    scheme = load_scheme(settings.scheme)
    client = OpenAICompatClient(settings.aggregator_base_url, settings.aggregator_admin_api_key)
    controls = load_controls()
    create_all()
    cache = DbQualificationCache()

    buckets = strata(study, a.per_stratum)
    print({k: len(v) for k, v in buckets.items()}, flush=True)

    rows, skipped = [], 0
    for stratum, entries in buckets.items():
        for L, item in entries:
            tag = L["tag"]
            lang = scheme.get(tag)
            used_bt = (L.get("backtranslator") or "").replace("remote:", "").split("@")[0]
            candidates = [m for m in PANEL if m != used_bt and m != L.get("engine")]
            chosen = None
            for model in candidates:
                bt = RemoteBackTranslator(client, model, L.get("pivot", "en"))
                q = qualify(bt, client, settings.judge_model, tag, controls, cache)
                if q.trustworthy:
                    chosen = model
                    break
            if chosen is None:
                skipped += 1
                continue
            verdict = ask(client, chosen, item["source"], item["translation"],
                          lang.name if lang else tag)
            rows.append({"stratum": stratum, "tag": tag, "id": item["id"],
                         "chrf": item["chrf"], "recall": item["recall"],
                         "gate": item.get("gate"), "adjudicator": chosen, **verdict})
            print(f"  {stratum:14} {tag:10} chrf={item['chrf']:6} recall={item['recall']} "
                  f"-> {verdict.get('adequacy') or verdict.get('error')}", flush=True)

    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"panel": PANEL, "skipped_no_qualified_adjudicator": skipped,
                               "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nadjudicated {len(rows)}, skipped {skipped} (no qualified adjudicator)")
    for stratum in buckets:
        sel = [r for r in rows if r["stratum"] == stratum]
        if not sel:
            continue
        adq = sum(1 for r in sel if r.get("adequacy") == "adequate")
        part = sum(1 for r in sel if r.get("adequacy") == "partial")
        lang_ok = sum(1 for r in sel if r.get("language") == "yes")
        print(f"  {stratum:14} n={len(sel):3}  adequate {adq:3} ({adq/len(sel):.0%})  "
              f"partial {part:3}  in-language {lang_ok:3}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
