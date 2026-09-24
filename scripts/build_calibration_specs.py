#!/usr/bin/env python3
"""Extract fact checklists from FLORES source sentences, for the calibration study.

The calibration compares two scores on one translation: chrF++ against the human
reference, and our own fact recall. Fact recall needs a checklist, and FLORES
ships sentences rather than checklists -- so they are extracted once, here.

**Not committed.** The checklists are derived from FLORES-200 text, and CC BY-SA
share-alike attaches to derived text, so they are built locally under `data/`
like the controls themselves.

**Extraction is done by a model and is therefore part of the instrument.** Two
guards follow from that, both deliberate:

  never the model under test   the same self-preference problem as the judge
  facts must be checkable      each one has to be decidable from the sentence
                               alone, or the judge is grading a guess

Usage:  python scripts/build_calibration_specs.py [--tags af,ru,...] [--items 4]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from llmlc.bt.qualify import load_controls  # noqa: E402
from llmlc.client import OpenAICompatClient  # noqa: E402
from llmlc.config import settings  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "calibration" / "specs.json"

#: Two checklist styles. `plain` asks what the sentence says; `hard` asks for the
#: details a merely adequate translation drops. Protocol 014 found `plain`
#: saturates -- 84% of items scored a perfect recall -- so `hard` exists to test
#: whether that is a property of the checklist or of the metric (protocol 015).
EXTRACT_PROMPT = """Extract the checkable factual claims from this sentence.

SENTENCE:
{sentence}

Rules:
  - Each fact must be decidable from the sentence alone, with no outside knowledge.
  - Each fact must be one simple English clause.
  - Cover who, what, where, when and how many, where the sentence states them.
  - Do not infer, embellish, or restate the same fact twice.
  - Between 3 and 6 facts.

Reply with JSON only: {{"facts": ["...", "..."]}} and nothing else."""

HARD_PROMPT = """Extract the factual claims from this sentence that a careless translation \
would lose.

SENTENCE:
{sentence}

Target the detail that survives only a faithful rendering:
  - exact numbers, quantities, dates, times and units, with their precise values
  - negation, and any claim about something NOT happening or NOT being the case
  - modality and hedging: may, might, expected to, reportedly, approximately
  - who did what to whom — agent and patient, not merely that an event occurred
  - causation and sequence: because, after, despite, in order to
  - named entities exactly as given, including titles and roles

Rules:
  - Each fact must be decidable from the sentence alone, with no outside knowledge.
  - Each fact must be one simple English clause.
  - A fact must be specific enough that a vague paraphrase of the sentence would FAIL it.
  - Do not invent detail the sentence does not state.
  - Between 4 and 8 facts.

Reply with JSON only: {{"facts": ["...", "..."]}} and nothing else."""


def extract(client: OpenAICompatClient, model: str, sentence: str,
            profile: str = "plain") -> list[str]:
    prompt = (HARD_PROMPT if profile == "hard" else EXTRACT_PROMPT).format(sentence=sentence)
    c = client.complete(model, prompt, max_tokens=500)
    if not c.ok:
        return []
    raw = (c.text or "").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < 0:
        return []
    try:
        facts = json.loads(raw[start:end + 1]).get("facts", [])
    except json.JSONDecodeError:
        return []
    return [f.strip() for f in facts if isinstance(f, str) and f.strip()]


def save(out: dict, model: str, items: int) -> None:
    """Write the whole file. Called after every language, not only at the end.

    Extraction is hundreds of calls over tens of minutes, and the first version
    of this script held everything in memory until the final write -- so any
    failure, anywhere, threw away every call already paid for. Rewriting a small
    JSON file per language costs nothing next to one API call.
    """
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "meta": {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "extractor": model, "items_per_language": items,
                 "source": "FLORES-200 (c) Meta AI, CC BY-SA 4.0",
                 "note": "Derived from FLORES text; share-alike applies. Not committed."},
        "specs": out,
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tags", default=None,
                   help="comma-separated tags to build for; omit for every tag with "
                        "reference controls")
    p.add_argument("--items", type=int, default=4, help="sentences per language")
    p.add_argument("--model", default=None, help="extraction model (not the model under test)")
    p.add_argument("--refresh", action="store_true", help="re-extract tags already built")
    p.add_argument("--profile", choices=("plain", "hard"), default="plain",
                   help="'hard' targets the detail a careless translation loses (protocol 015)")
    p.add_argument("--out", default=None, help="output path; defaults by profile")
    a = p.parse_args(argv)

    if not settings.aggregator_base_url or not settings.aggregator_admin_api_key:
        print("No endpoint configured. Copy .env.example to .env and fill it in.",
              file=sys.stderr)
        return 2

    controls = load_controls()
    wanted = ([t.strip() for t in a.tags.split(",") if t.strip()] if a.tags
              else sorted(t for t, e in controls.items() if e.get("kind") == "reference"))

    global OUT
    OUT = (pathlib.Path(a.out) if a.out else
           (ROOT / "data" / "calibration" /
            ("specs.json" if a.profile == "plain" else f"specs.{a.profile}.json")))

    existing: dict[str, dict] = {}
    if OUT.exists() and not a.refresh:
        existing = json.loads(OUT.read_text(encoding="utf-8")).get("specs", {})

    client = OpenAICompatClient(settings.aggregator_base_url, settings.aggregator_admin_api_key)
    model = a.model or settings.judge_model
    out: dict[str, dict] = dict(existing)
    built = skipped = 0

    for tag in wanted:
        entry = controls.get(tag)
        if not entry or entry.get("kind") != "reference":
            print(f"  {tag}: no reference control, skipped", file=sys.stderr)
            skipped += 1
            continue
        if tag in out and not a.refresh:
            continue

        items = []
        for i, item in enumerate(entry["items"][: a.items]):
            # `reference` is the English side; `text` is the target language.
            source, reference = item["reference"], item["text"]
            facts = extract(client, model, source, a.profile)
            if len(facts) < 3:
                print(f"  {tag} item {i}: extraction returned {len(facts)} facts, dropped",
                      file=sys.stderr)
                continue
            items.append({"id": f"{tag}-{i}", "source": source,
                          "reference": reference, "facts": facts})
        if not items:
            skipped += 1
            continue
        out[tag] = {"items": items}
        built += 1
        save(out, model, a.items)
        print(f"  {tag}: {len(items)} item(s), "
              f"{sum(len(i['facts']) for i in items)} facts", flush=True)

    save(out, model, a.items)
    print(f"\nwrote {OUT}  {len(out)} language(s)  (+{built} built, {skipped} skipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
