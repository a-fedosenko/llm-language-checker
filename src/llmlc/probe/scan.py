"""Batch scanning with class collapse.

Base-language capability is a property of the `(iso639_3, script)` equivalence
class, not of the tag: `af`, `af-NA` and `af-ZA` are one experiment. So the
ladder runs once per class and the result propagates to the class's other tags,
marked as inherited rather than measured.

Dialect-level testing -- where a variant gets its own probe and its own
designator -- is S6. Until then an inherited tag carries `variant_evidence:
untested`, which is a tracked gap, not a claim.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from llmlc.bt import QualificationCache, RemoteBackTranslator
from llmlc.client import OpenAICompatClient
from llmlc.probe.corpus import Corpus
from llmlc.probe.ladder import LadderResult, run_ladder
from llmlc.probe.specs import Spec
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
) -> ScanResult:
    groups, unknown = plan(scheme, tags)
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
        out.results.append(result)
        out.classes_probed += 1
        if on_result:
            on_result(result)

        # Everything else in the class inherits without further calls -- the
        # pruning that makes a wide scan affordable.
        for tag in members[1:]:
            inherited = inherit(result, tag, scheme)
            out.results.append(inherited)
            out.tags_inherited += 1
            if on_result:
                on_result(inherited)

    out.seconds = time.monotonic() - started
    return out
