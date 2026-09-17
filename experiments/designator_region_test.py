#!/usr/bin/env python3
"""Does qualifying a designator by COUNTRY help or hurt?

Current candidate A qualifies the English language name by script only --
"Chuvash (Cyrillic script)". Adding the country is untested: `region_name` is a
parameter of the designator builder that the pipeline never passes.

The risk, raised by Andrei: naming the country may pull the model toward that
country's dominant language -- "Chuvash (Russia)" producing Russian, "Uyghur
(China)" producing Chinese. That is the nearest-relative substitution failure,
and the gate can now measure it directly.

Scored on gate outcome only -- no judge calls.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[0] / ".." / "src"))

from llmlc.client import OpenAICompatClient          # noqa: E402
from llmlc.config import settings                     # noqa: E402
from llmlc.probe import designator as dsg             # noqa: E402
from llmlc.probe.gate import check as gate_check      # noqa: E402
from llmlc.probe.ladder import accepted_codes, relative_codes  # noqa: E402
from llmlc.probe.specs import load_specs              # noqa: E402
from llmlc.scheme import load_scheme                  # noqa: E402

# Chosen so that naming the country is a plausible trap: each has a dominant
# national language that the model could fall back to. `mt` and `af` are
# low-risk controls.
LANGUAGES = {
    "cv":  ("Russia", "rus"),        # Chuvash      -> Russian?
    "ug":  ("China", "zho"),         # Uyghur       -> Chinese?
    "bo":  ("China", "zho"),         # Tibetan      -> Chinese?
    "ti":  ("Eritrea", "amh"),       # Tigrinya     -> Amharic?
    "gsw": ("Switzerland", "deu"),   # Swiss German -> Standard German?
    "mt":  ("Malta", None),          # Maltese      -- control
    "af":  ("South Africa", None),   # Afrikaans    -- control
}


def variants(lang, region_name: str) -> dict[str, str]:
    name = lang.name or lang.tag
    script = dsg.SCRIPT_NAMES.get(lang.script or "", lang.script or "")
    return {
        "name": name,
        "name+script": f"{name} ({script} script)" if script else name,
        "name+country": f"{name} ({region_name})",
        "name+country+script": (f"{name} ({region_name}, {script} script)"
                                if script else f"{name} ({region_name})"),
        "endonym": lang.local_name or name,
        "tag": lang.tag,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="openai-gpt-4o")
    ap.add_argument("--items", type=int, default=2)
    ap.add_argument("--out", default="experiments/results/designator_region.jsonl")
    a = ap.parse_args()

    scheme = load_scheme("default")
    specs = load_specs()[: a.items]
    client = OpenAICompatClient(settings.aggregator_base_url, settings.aggregator_admin_api_key)
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    with out.open("w", encoding="utf-8") as fh:
        for tag, (region_name, trap) in LANGUAGES.items():
            lang = scheme.get(tag)
            if lang is None:
                print(f"  {tag}: not in scheme", file=sys.stderr)
                continue
            accept = accepted_codes(lang)
            relatives = relative_codes(scheme, lang)
            print(f"\n{lang.name} [{tag}]  trap={trap or '-'}")
            for label, designator in variants(lang, region_name).items():
                verdicts, labels = [], []
                for spec in specs:
                    prompt = dsg.generation_prompt(designator, spec.scenario, 3)
                    gen = client.complete(a.engine, prompt, max_tokens=400)
                    g = gate_check(gen.text, prompt=prompt, expect_lang=lang.iso639_3,
                                   expect_script=lang.script, relatives=relatives,
                                   accept_lang=accept)
                    verdicts.append(g.verdict.value)
                    if g.lid and g.lid.label:
                        labels.append(g.lid.label)
                    row = {"tag": tag, "variant": label, "designator": designator,
                           "spec": spec.id, "verdict": g.verdict.value,
                           "lid": g.lid.label if g.lid else None,
                           "detail": g.detail, "text": (gen.text or "")[:200]}
                    rows.append(row)
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    fh.flush()
                passed = sum(v == "pass" for v in verdicts)
                trapped = sum(1 for l in labels if trap and l.startswith(trap))
                flag = f"  <-- fell to {trap} x{trapped}" if trapped else ""
                print(f"   {label:22} {designator[:34]:36} {passed}/{len(verdicts)}"
                      f"  {Counter(labels).most_common(1)}{flag}")

    # summary across languages
    print("\n" + "=" * 74)
    print(f"{'variant':24}{'pass rate':>12}{'trap substitutions':>22}")
    for label in variants(scheme.get("cv"), "Russia"):
        sub = [r for r in rows if r["variant"] == label]
        passed = sum(r["verdict"] == "pass" for r in sub)
        trapped = sum(1 for r in sub
                      if LANGUAGES[r["tag"]][1] and (r["lid"] or "").startswith(LANGUAGES[r["tag"]][1]))
        print(f"{label:24}{passed}/{len(sub):<10}{trapped:>16}")
    print(f"\nraw: {out}")


if __name__ == "__main__":
    main()
