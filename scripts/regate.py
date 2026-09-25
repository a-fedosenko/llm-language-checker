"""Re-run the deterministic gate over the calibration study's committed output.

Protocol 018 found that `probe/calibrate.py` calls `gate_check` without
`accept_lang` or `relatives`, while `probe/pipeline.py` — the production path —
passes both. The difference is not cosmetic: without `accept_lang`, a
macrolanguage that correctly resolves to one of its own members is convicted of
`wrong_language`. Swahili, Malay, Tagalog, Albanian, Estonian, Uzbek, Mongolian
and Nepali are all macrolanguages in the shipped scheme, and all of them scored
4 of 4 `wrong_language` in the study while averaging chrF++ 50–80.

So the `gate` field in `data/calibration/study.json` is not the gate this tool
runs. This script recomputes it with production semantics, using the committed
translations and the local GlotLID model. No model calls, no cost.

    .venv/bin/python scripts/regate.py
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from llmlc.probe.gate import check as gate_check
from llmlc.probe.pipeline import _accepted, _relatives
from llmlc.scheme.loader import load_scheme

STUDY = pathlib.Path("data/calibration/study.json")
OUT = pathlib.Path("data/calibration/regate.json")

#: calibrate.py's prompt, needed so the copy check behaves as it did in the run.
TRANSLATE_PROMPT = None


def main() -> int:
    study = json.loads(STUDY.read_text(encoding="utf-8"))
    scheme = load_scheme("default")
    from llmlc.probe.calibrate import TRANSLATE_PROMPT as prompt_template

    out: dict[str, dict[str, str]] = {}
    changed = 0
    total = 0
    for rec in study["languages"]:
        tag = rec["tag"]
        lang = scheme.get(tag)
        if lang is None:
            continue
        accept = _accepted(scheme, lang)
        relatives = _relatives(scheme, lang)
        out[tag] = {}
        for item in rec["items"]:
            text = item.get("translation")
            if not text:
                continue
            prompt = prompt_template.format(language=lang.name, text=item["source"])
            g = gate_check(text, prompt=prompt, expect_lang=lang.iso639_3,
                           expect_script=lang.script, relatives=relatives,
                           accept_lang=accept)
            out[tag][item["id"]] = g.verdict.value
            total += 1
            if g.verdict.value != item.get("gate"):
                changed += 1
        print(f"  {tag:<10}{' '.join(out[tag].values())}", flush=True)

    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\n{changed} of {total} item verdicts change under production semantics")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
