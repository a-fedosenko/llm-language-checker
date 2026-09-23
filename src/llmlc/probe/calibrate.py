"""The calibration study: fact recall against chrF++ on the same output.

The tool's whole method rests on a claim that has been asserted since doc 01 and
never measured -- that **fact recall is a usable proxy for translation quality**.
This is the measurement of that claim, and the one place in the project where the
instrument rather than a language is under test.

One translation, scored twice:

    model translates a FLORES source sentence into the target language
      -> chrF++ against the human reference          the reference metric
      -> back-translate, judge against a checklist   our proxy

Paired per item, averaged per language.

**Why a translation task, when the tool measures free generation.** chrF++ needs
a reference translation *of the text being scored*, and a free composition has
none -- scoring one against an unrelated FLORES sentence would return near zero
for a perfectly good answer. There is no way to compute the reference metric on
the task we normally run, so the calibration runs the task where both metrics are
computable, and the transfer to free generation is an assumption stated in
protocol 014 rather than engineered away.

This is also the only place `Evidence.GOLD_REFERENCE` is produced. It was
declared in S2 on the expectation that gold-reference scoring would fall out of
the ordinary probe as a by-product; it could not, for the reason above.
"""
from __future__ import annotations

import json
import pathlib
import statistics
from dataclasses import dataclass, field

from llmlc.bt import Qualification, QualificationCache, RemoteBackTranslator, route
from llmlc.client import OpenAICompatClient
from llmlc.probe import pivot as pivot_mod
from llmlc.probe.chrf import chrf
from llmlc.probe.corpus import Corpus, Record
from llmlc.probe.gate import check as gate_check
from llmlc.probe.judge import judge as run_judge
from llmlc.probe.score import Evidence
from llmlc.scheme import Language, Scheme

SPECS_PATH = pathlib.Path("data/calibration/specs.json")

TRANSLATE_PROMPT = """Translate the following text into {language}.
Reply with the translation only — no commentary, no notes, no original text.

TEXT:
{text}"""


@dataclass
class CalibrationItem:
    """One sentence, scored by both metrics."""

    item_id: str
    source: str
    reference: str
    translation: str | None = None
    back_translation: str | None = None
    chrf: float | None = None
    recall: float | None = None
    gate: str | None = None
    error: str | None = None

    @property
    def paired(self) -> bool:
        """Usable for the correlation: both metrics present."""
        return self.chrf is not None and self.recall is not None

    def as_dict(self) -> dict:
        return {"id": self.item_id, "chrf": None if self.chrf is None else round(self.chrf, 2),
                "recall": None if self.recall is None else round(self.recall, 3),
                "gate": self.gate, "error": self.error, "source": self.source,
                "translation": self.translation, "back_translation": self.back_translation}


@dataclass
class CalibrationResult:
    tag: str
    engine: str
    backtranslator: str
    judge_model: str
    pivot: str
    items: list[CalibrationItem] = field(default_factory=list)
    calls: dict[str, int] = field(default_factory=lambda: {"translation": 0,
                                                           "backtranslation": 0, "judge": 0})
    qualification: dict = field(default_factory=dict)
    qualified: bool = True
    note: str | None = None

    @property
    def evidence(self) -> str:
        """`gold-reference` where a human reference actually graded something."""
        return (Evidence.GOLD_REFERENCE.value if any(i.chrf is not None for i in self.items)
                else Evidence.UNVERIFIED.value)

    @property
    def paired(self) -> list[CalibrationItem]:
        return [i for i in self.items if i.paired]

    @property
    def mean_chrf(self) -> float | None:
        vals = [i.chrf for i in self.items if i.chrf is not None]
        return statistics.fmean(vals) if vals else None

    @property
    def mean_recall(self) -> float | None:
        vals = [i.recall for i in self.items if i.recall is not None]
        return statistics.fmean(vals) if vals else None

    def as_dict(self) -> dict:
        return {
            "tag": self.tag, "engine": self.engine, "evidence": self.evidence,
            "backtranslator": self.backtranslator, "judge": self.judge_model,
            "pivot": self.pivot,
            "mean_chrf": None if self.mean_chrf is None else round(self.mean_chrf, 2),
            "mean_recall": None if self.mean_recall is None else round(self.mean_recall, 3),
            "n_items": len(self.items), "n_paired": len(self.paired),
            "calls": self.calls, "note": self.note,
            "items": [i.as_dict() for i in self.items],
        }


def load_specs(path: pathlib.Path | None = None) -> dict[str, dict]:
    """Fact checklists extracted from FLORES source sentences.

    Built by `scripts/build_calibration_specs.py` and not committed: they are
    derived from FLORES text, so share-alike applies.
    """
    p = path or SPECS_PATH
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8")).get("specs", {})


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Rank correlation, computed here rather than pulled in as a dependency.

    Spearman rather than Pearson because the question is whether the two metrics
    *order* things the same way, not whether they are linearly related -- they
    are on different scales and there is no reason to expect linearity. Ties are
    averaged, which is what makes this honest on fact recall: a five-fact
    checklist takes only six values, so ties are the norm rather than the
    exception.
    """
    n = len(xs)
    if n < 3 or n != len(ys):
        return None

    def ranks(vs: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: vs[i])
        out = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and vs[order[j + 1]] == vs[order[i]]:
                j += 1
            shared = (i + j) / 2 + 1
            for k in range(i, j + 1):
                out[order[k]] = shared
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx)
    dy = sum((b - my) ** 2 for b in ry)
    if dx == 0 or dy == 0:
        return None          # one metric is constant; no ordering to compare
    return num / (dx * dy) ** 0.5


def calibrate_language(
    *, scheme: Scheme, tag: str, engine: str, client: OpenAICompatClient,
    backtranslators: list[RemoteBackTranslator], judge_model: str,
    spec: dict, corpus: Corpus, pivot: str = "en", n_items: int | None = None,
    cache: QualificationCache | None = None,
) -> CalibrationResult:
    """Translate, score both ways, and return the paired items for one language."""
    lang: Language | None = scheme.get(tag)
    if lang is None:
        raise KeyError(f"Unknown tag {tag!r}")

    backtranslators, pivot, controls = pivot_mod.panel_for(scheme, lang, pivot, backtranslators)

    # Qualify the instrument, exactly as a normal scan does. A back-translator
    # that cannot read the language does not fail loudly, it fabricates
    # (protocol 005) -- and a fabricated back-translation would corrupt the
    # recall side of the very correlation this study exists to measure, making
    # the proxy look worse than it is. chrF++ needs no back-translator, so an
    # unqualified language still contributes a reference score; it simply
    # contributes no pair.
    bt, qual = route(backtranslators, client, judge_model, tag,
                     controls=controls, cache=cache)
    out = CalibrationResult(tag=tag, engine=engine, backtranslator=bt.id,
                            judge_model=judge_model, pivot=pivot,
                            qualification=qual.as_dict() if qual else {},
                            qualified=bool(qual and qual.trustworthy))
    language_name = lang.name or tag

    for item in spec.get("items", [])[:n_items] if n_items else spec.get("items", []):
        ci = CalibrationItem(item_id=item["id"], source=item["source"],
                             reference=item["reference"])
        prompt = TRANSLATE_PROMPT.format(language=language_name, text=item["source"])
        gen = client.complete(engine, prompt, max_tokens=500)
        out.calls["translation"] += 1
        corpus.write(Record("calibration", engine, tag, item["id"], language_name,
                            prompt, gen.text, gen.error, gen.usage, gen.latency_s))
        if not gen.ok:
            ci.error = gen.error
            out.items.append(ci)
            continue
        ci.translation = gen.text

        # The gate runs for diagnosis only. A refusal or a wrong-language answer
        # is scored rather than dropped: chrF++ near zero for text that is not
        # the language is a true statement about the translation, and dropping it
        # would quietly restrict the study to the cases that went well.
        gate = gate_check(gen.text, prompt=prompt, expect_lang=lang.iso639_3,
                          expect_script=lang.script)
        ci.gate = gate.verdict.value
        ci.chrf = chrf(gen.text or "", item["reference"])

        if not out.qualified:
            # No trustworthy reader for this language: the reference score stands
            # on its own, and recall is left absent rather than fabricated.
            out.items.append(ci)
            continue

        tr = bt.translate(gen.text or "")
        out.calls["backtranslation"] += 1
        corpus.write(Record("backtranslation", bt.id, tag, item["id"], language_name,
                            "", tr.text, tr.error))
        if not tr.ok:
            ci.error = tr.error
            out.items.append(ci)
            continue
        ci.back_translation = tr.text

        judgement = run_judge(client, judge_model, tr.text or "", item["facts"])
        out.calls["judge"] += 1
        corpus.write(Record("judgement", judge_model, tag, item["id"], language_name,
                            "", judgement.raw, judgement.error,
                            meta={"verdicts": [v.value for v in judgement.verdicts]}))
        if judgement.ok:
            ci.recall = judgement.recall
        else:
            ci.error = judgement.error
        out.items.append(ci)

    if not out.qualified:
        out.note = (f"Back-translator {bt.id} is "
                    f"{out.qualification.get('status', 'unqualified')} for {tag}: recall was "
                    f"not measured, so this language contributes chrF++ only.")
    elif not out.paired:
        out.note = "No item produced both scores; nothing to correlate for this language."
    return out


def correlate(results: list[CalibrationResult]) -> dict:
    """Item-level and language-level correlation over a completed run.

    Both are reported because they answer different questions. The item level
    asks whether the proxy tracks quality sentence by sentence; the language
    level asks whether it *ranks languages* the way the reference metric does,
    which is what the tool actually claims, since tiers are per language.
    """
    items = [i for r in results for i in r.paired]
    unqualified = [r.tag for r in results if not r.qualified]
    item_rho = spearman([i.chrf for i in items], [i.recall for i in items])

    langs = [r for r in results if r.mean_chrf is not None and r.mean_recall is not None]
    lang_rho = spearman([r.mean_chrf for r in langs], [r.mean_recall for r in langs])

    # Where they disagree, is recall the forgiving one? chrF++ is 0-100 and
    # recall 0-1, so compare on a common scale before differencing.
    offsets = [i.recall - (i.chrf / 100.0) for i in items]
    bands: dict[str, list[float]] = {"chrf>=60": [], "chrf 40-60": [], "chrf<40": []}
    for i in items:
        key = "chrf>=60" if i.chrf >= 60 else ("chrf 40-60" if i.chrf >= 40 else "chrf<40")
        bands[key].append(i.recall - i.chrf / 100.0)

    return {
        "n_items": len(items), "n_languages": len(langs),
        "n_unqualified": len(unqualified), "unqualified": sorted(unqualified),
        "item_spearman": None if item_rho is None else round(item_rho, 3),
        "language_spearman": None if lang_rho is None else round(lang_rho, 3),
        "mean_offset_recall_minus_chrf": (round(statistics.fmean(offsets), 3)
                                          if offsets else None),
        "offset_by_band": {k: {"n": len(v), "mean": round(statistics.fmean(v), 3)}
                           for k, v in bands.items() if v},
    }
