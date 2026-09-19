"""Batch scanning with class collapse, and variant probes on top of it.

Base-language capability is a property of the `(iso639_3, script)` equivalence
class, not of the tag: `af`, `af-NA` and `af-ZA` are one experiment. So the
ladder runs once per class and the result propagates to the class's other tags,
marked as inherited rather than measured.

**Inheriting the tier is not the same as inheriting the claim** (S6). A tag that
inherits `de`'s tier has said nothing about whether the model marks *that
variant*, so each inherited tag also gets a variant verdict:

  markers exist            -> its own probe, its own designator, marker-scored
  declared indistinguishable -> inheritance is correct, not a fallback
  neither                  -> `untested`, a tracked gap rather than a claim

A representative probed under a script-split language gets its variant verdict
for free: the gate already checked the script, which is the variant question for
those families.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from llmlc.bt import QualificationCache, RemoteBackTranslator
from llmlc.client import OpenAICompatClient
from llmlc.probe.corpus import Corpus
from llmlc.probe.ladder import LadderResult, run_ladder
from llmlc.probe.markers import MarkerSet, load_markers
from llmlc.probe.specs import Spec
from llmlc.probe.variant import (VariantEvidence, declared, from_markers, from_script,
                                 is_script_variant, untested)
from llmlc.scheme import Scheme


@dataclass
class ScanBudget:
    """Fails closed. Single-tenant removes the abuse case but not the accident."""

    max_calls: int | None = None
    calls: int = 0

    def spend(self, n: int) -> None:
        self.calls += n

    @property
    def exhausted(self) -> bool:
        return self.max_calls is not None and self.calls >= self.max_calls


@dataclass
class ScanResult:
    results: list[LadderResult] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    classes_probed: int = 0
    tags_inherited: int = 0
    variants_probed: int = 0
    stopped_early: bool = False
    stop_reason: str | None = None
    seconds: float = 0.0

    @property
    def calls(self) -> dict[str, int]:
        out = {"generation": 0, "backtranslation": 0, "judge": 0}
        for r in self.results:
            for k, v in r.calls.items():
                out[k] = out.get(k, 0) + v
        return out


def plan(scheme: Scheme, tags: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    """Group requested tags by equivalence class, representative first.

    The representative is the shortest tag in the class, which is the base form
    (`af` over `af-NA`) and therefore the one whose designator is least qualified.

    Returns (groups, unknown). Unknown tags are returned rather than dropped --
    silently ignoring a requested language is the wrong failure mode for a tool
    whose whole job is saying what it did and did not measure.
    """
    groups: dict[str, list[str]] = {}
    unknown: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        lang = scheme.get(tag)
        if lang is None:
            unknown.append(tag)
            continue
        if lang.tag in seen:
            continue
        seen.add(lang.tag)
        groups.setdefault(lang.cls, []).append(lang.tag)
    ordered = {cls: sorted(members, key=lambda t: (len(t), t))
               for cls, members in groups.items()}
    return ordered, unknown


def inherit(source: LadderResult, tag: str, scheme: Scheme) -> LadderResult:
    """Copy a class result onto another tag in the same class."""
    lang = scheme.get(tag)
    return LadderResult(
        tag=tag, engine=source.engine, language=lang, designator=source.designator,
        designator_kinds=source.designator_kinds, trials=source.trials,
        score=source.score, items=[], backtranslator=source.backtranslator,
        judge_model=source.judge_model, pivot=source.pivot,
        qualification=source.qualification, rungs_run=0,
        resolves_to=source.resolves_to, calls={"generation": 0, "backtranslation": 0, "judge": 0},
        inherited_from=source.tag)


def scan(
    *,
    scheme: Scheme,
    tags: list[str],
    engine: str,
    client: OpenAICompatClient,
    backtranslators: list[RemoteBackTranslator],
    judge_model: str,
    specs: list[Spec],
    corpus: Corpus,
    pivot: str = "en",
    incumbents: dict[str, str] | None = None,
    sweep_all: bool = False,
    cache: QualificationCache | None = None,
    budget: ScanBudget | None = None,
    on_result=None,
    should_stop=None,
    markers: dict[str, MarkerSet] | None = None,
    probe_variants: bool = True,
) -> ScanResult:
    groups, unknown = plan(scheme, tags)
    marker_sets = load_markers() if markers is None else markers
    out = ScanResult(unknown=unknown)
    budget = budget or ScanBudget()
    started = time.monotonic()

    for cls, members in groups.items():
        # Checked between classes rather than between calls: a half-probed class
        # would be a partial measurement, and a partial measurement is worse than
        # a missing one.
        if budget.exhausted:
            out.stopped_early, out.stop_reason = True, "budget"
            break
        if should_stop and should_stop():
            out.stopped_early, out.stop_reason = True, "cancelled"
            break
        representative = members[0]
        result = run_ladder(
            scheme=scheme, tag=representative, engine=engine, client=client,
            backtranslators=backtranslators, judge_model=judge_model, specs=specs,
            corpus=corpus, pivot=pivot,
            incumbent=(incumbents or {}).get(representative),
            sweep_all=sweep_all, cache=cache,
        )
        budget.spend(sum(result.calls.values()))
        result.variant = _variant_for_representative(scheme, result, marker_sets)
        out.results.append(result)
        out.classes_probed += 1
        if on_result:
            on_result(result)

        # Everything else in the class inherits the tier without further calls --
        # the pruning that makes a wide scan affordable. The variant claim is a
        # separate question and may cost its own calls.
        for tag in members[1:]:
            inherited = inherit(result, tag, scheme)
            inherited.variant = _variant_for_member(
                scheme=scheme, tag=tag, engine=engine, client=client, corpus=corpus,
                marker_sets=marker_sets, budget=budget,
                probe_variants=probe_variants and not (should_stop and should_stop()))
            if getattr(inherited.variant, "calls", 0):
                budget.spend(inherited.variant.calls)
                out.variants_probed += 1
            out.results.append(inherited)
            out.tags_inherited += 1
            if on_result:
                on_result(inherited)

    out.seconds = time.monotonic() - started
    return out


def _variant_for_representative(scheme: Scheme, result: LadderResult,
                                marker_sets: dict[str, MarkerSet]):
    """The variant verdict for the tag that was actually probed.

    Free where the language splits by script: the gate checked the script on
    every item, so "asked for Latin Kazakh, got Latin Kazakh" is already
    recorded. A marker set on the representative itself is honoured too, but it
    would need its own probe and the representative is by construction the least
    qualified tag in its class -- so it is reported as untested rather than
    quietly measured against the wrong sibling.
    """
    ms = marker_sets.get(result.tag)
    if ms is not None and ms.status == "not-distinguishable":
        return declared(result.tag, ms)
    if result.language is not None and is_script_variant(scheme, result.language):
        return from_script(result)
    return untested(result.tag, "Base form of the language, not a marked variant.")


def _variant_for_member(*, scheme: Scheme, tag: str, engine: str, client, corpus,
                        marker_sets: dict[str, MarkerSet], budget: ScanBudget,
                        probe_variants: bool):
    """The variant verdict for a tag that inherited its tier.

    This is the only place in a scan that spends calls on something other than a
    class probe, so it checks the budget itself: a variant probe must never be
    the reason a class goes unmeasured.
    """
    ms = marker_sets.get(tag)
    if ms is None:
        return untested(tag, "No marker set authored for this variant yet.")
    if ms.status == "not-distinguishable":
        return declared(tag, ms)
    if not ms.testable:
        return untested(tag, "Marker set is incomplete.")
    if not probe_variants:
        return untested(tag, "Variant probing disabled for this scan.")
    if budget.exhausted:
        return untested(tag, "Budget exhausted before the variant probe.")
    lang = scheme.get(tag)
    if lang is None:
        return untested(tag, "Tag is not in the scheme.")
    return from_markers(client=client, engine=engine, lang=lang, markers=ms,
                        corpus=corpus, scheme=scheme)
