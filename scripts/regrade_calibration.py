#!/usr/bin/env python3
"""Re-judge a finished calibration study against a different fact checklist.

No sentence is translated again: the stored back-translations are graded a second
time, so the checklist is the only variable and the comparison is paired at the
item level. This is the corpus doing the job docs/01 designed it for.

Usage:  python scripts/regrade_calibration.py --specs data/calibration/specs.hard.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from llmlc.client import OpenAICompatClient  # noqa: E402
from llmlc.config import settings  # noqa: E402
from llmlc.probe.calibrate import (CalibrationItem, CalibrationResult, compare,  # noqa: E402
                                   correlate, load_specs, regrade)
from llmlc.probe.corpus import Corpus  # noqa: E402


def rehydrate(study: dict) -> list[CalibrationResult]:
    """The original grading, as objects, so `compare` sees both sides alike."""
    out = []
    for lang in study.get("languages", []):
        r = CalibrationResult(tag=lang["tag"], engine=lang["engine"],
                              backtranslator=lang["backtranslator"],
                              judge_model=lang.get("judge", ""),
                              pivot=lang.get("pivot", "en"))
        for i in lang.get("items", []):
            r.items.append(CalibrationItem(
                item_id=i["id"], source=i.get("source", ""), reference="",
                chrf=i.get("chrf"), recall=i.get("recall"), gate=i.get("gate"),
                back_translation=i.get("back_translation")))
        out.append(r)
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study", default="data/calibration/study.json")
    p.add_argument("--specs", required=True, help="the new checklists")
    p.add_argument("--judge", default=None)
    p.add_argument("--out", default="data/calibration/study.hard.json")
    a = p.parse_args(argv)

    if not settings.aggregator_base_url or not settings.aggregator_admin_api_key:
        print("No endpoint configured.", file=sys.stderr)
        return 2

    study = json.loads(pathlib.Path(a.study).read_text(encoding="utf-8"))
    specs = load_specs(pathlib.Path(a.specs))
    if not specs:
        print(f"No specs at {a.specs}", file=sys.stderr)
        return 2

    client = OpenAICompatClient(settings.aggregator_base_url, settings.aggregator_admin_api_key)
    judge = a.judge or study.get("judge") or settings.judge_model
    print(f"re-grading {len(study['languages'])} language(s) against {len(specs)} "
          f"new checklist(s), judge {judge}", flush=True)

    with Corpus(to_db=True) as corpus:
        after = regrade(study, specs, client, judge, corpus=corpus)
    before = rehydrate(study)

    stats = correlate(after)
    paired = compare(before, after)

    print(f"\npaired items: {paired['n_paired']}")
    for side in ("before", "after"):
        d = paired[side]
        print(f"  {d['label']:6} mean recall {d['mean_recall']}  "
              f"saturated {d['saturated']}/{d['n']} ({d['saturated_share']})  "
              f"floored {d['floored']}  rho vs chrF++ {d['spearman_vs_chrf']}")
    print("\n  band          n   saturated before/after   rho before/after")
    for band, d in paired["by_band"].items():
        print(f"  {band:12} {d['n']:4}   {d['before_saturated']:4}/{d['after_saturated']:<4}"
              f"            {d['before_rho']} / {d['after_rho']}")
    print(f"\nlanguage-level rho (hard): {stats['language_spearman']}")

    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"engine": study.get("engine"), "judge": judge,
                               "specs": a.specs, "correlation": stats,
                               "paired_comparison": paired,
                               "languages": [r.as_dict() for r in after]},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
