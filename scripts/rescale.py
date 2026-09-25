"""Protocol 018 — re-analysis of the calibration study under a proposed scale.

No model calls. Reads `data/calibration/study.json` (protocol 014's 100-language
run) and asks whether an eligibility-filter-plus-adequacy-grade scale orders
languages better, and more honestly, than the five tiers it replaces.

The yardstick is mean chrF++ per language, with protocol 016's caveat attached:
it is an imperfect target, used here only because it is the one independent
per-language signal in the data.

    .venv/bin/python scripts/rescale.py
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

STUDY = pathlib.Path("data/calibration/study.json")
#: Gate verdicts recomputed under production semantics. The study's own `gate`
#: field was produced by a call that omitted `accept_lang` and `relatives`, which
#: convicts every macrolanguage that correctly resolves to one of its members —
#: see scripts/regate.py and protocol 018.
REGATE = pathlib.Path("data/calibration/regate.json")

# probe/gate.py: verdicts that are an accusation about the model, as opposed to
# a void item. `low_confidence` and `too_short` are explicitly "too weak to
# count against the model" there, but `ItemOutcome.lang_ok` is `gate.passed`,
# so today they count as failures anyway.
NEGATIVE = {"refused", "copy", "wrong_script", "wrong_language",
            "relative_substitution", "degenerate"}


# -- statistics ---------------------------------------------------------------

def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        mean_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[order[k]] = mean_rank
        i = j + 1
    return out


def spearman(a: list[float], b: list[float]) -> float | None:
    """Pearson over ranks; None when either side is constant and has no ordering."""
    if len(a) < 3 or len(set(a)) < 2 or len(set(b)) < 2:
        return None
    ra, rb = _ranks(a), _ranks(b)
    n = len(ra)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = sum((x - ma) ** 2 for x in ra) ** 0.5
    db = sum((y - mb) ** 2 for y in rb) ** 0.5
    return round(num / (da * db), 3) if da and db else None


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


# -- the languages ------------------------------------------------------------

class Lang:
    def __init__(self, rec: dict, regate: dict[str, dict[str, str]] | None = None):
        self.tag = rec["tag"]
        self.chrf = rec["mean_chrf"]
        items = [i for i in rec["items"] if i.get("recall") is not None]
        self.n = len(items)
        fixed = (regate or {}).get(self.tag, {})
        self.verdicts = [fixed.get(i["id"], i["gate"]) for i in items]
        self.verdicts_as_run = [i["gate"] for i in items]
        self.recalls = [i["recall"] for i in items]
        passing = [i["recall"] for i, v in zip(items, self.verdicts) if v == "pass"]
        # Production semantics: an item the gate rejected is never back-translated
        # and never judged, so it contributes no content score (probe/pipeline.py).
        self.s_content = mean(passing) if passing else None
        self.s_content_all = mean(self.recalls) if self.recalls else None
        self.n_pass = sum(1 for v in self.verdicts if v == "pass")
        self.n_negative = sum(1 for v in self.verdicts if v in NEGATIVE)
        self.n_void = self.n - self.n_pass - self.n_negative

    @property
    def s_lang(self) -> float:
        """As computed today: every non-pass counts against the model."""
        return self.n_pass / self.n if self.n else 0.0

    @property
    def s_lang_voidless(self) -> float:
        """Voided items out of the denominator rather than in it as failures."""
        d = self.n_pass + self.n_negative
        return self.n_pass / d if d else 0.0


# -- scales -------------------------------------------------------------------

#: The scale in probe/score.py today, for comparison.
CURRENT = [("Strong", 0.95, 0.70), ("Usable", 0.90, 0.50),
           ("Basic", 0.80, 0.30), ("Token", 0.50, 0.00)]
CURRENT_ORDER = ["None", "Token", "Basic", "Usable", "Strong"]


def current_tier(s_lang: float, s_content: float) -> str:
    for tier, min_lang, min_content in CURRENT:
        if s_lang >= min_lang and s_content >= min_content:
            return tier
    return "None"


def bin_tier(eligible: bool, s_content: float | None, cuts: list[float],
             names: list[str]) -> str:
    """names has len(cuts)+1 entries, lowest first. names[0] is the band below cuts[0]."""
    if not eligible or s_content is None:
        return "Unusable"
    band = 0
    for cut in cuts:
        if s_content >= cut:
            band += 1
    return names[band]


def monotonic(rows: list[tuple[str, int, float]]) -> bool:
    """rows are (tier, n, mean chrF++) in the scale's own ascending order."""
    seen = [chrf for _, n, chrf in rows if n]
    return all(a < b for a, b in zip(seen, seen[1:]))


def report(title: str, order: list[str], assign, langs: list[Lang]) -> dict:
    tiers = [assign(l) for l in langs]
    rows = []
    for name in order:
        members = [l for l, t in zip(langs, tiers) if t == name]
        rows.append((name, len(members), round(mean([m.chrf for m in members]), 1)))
    rho = spearman([float(order.index(t)) for t in tiers], [l.chrf for l in langs])
    mono = monotonic(rows)
    print(f"\n{title}")
    print(f"{'tier':<12}{'n':>5}{'mean chrF++':>14}")
    for name, n, chrf in rows:
        print(f"{name:<12}{n:>5}{(chrf if n else '—'):>14}")
    print(f"  Spearman vs mean chrF++: {rho}    monotonic: {'yes' if mono else 'NO'}")
    return {"title": title, "rows": rows, "spearman": rho, "monotonic": mono}



# -- follow-ups, added after the planned analysis ------------------------------
# These were not in protocol 018's hypotheses. They exist because H2 came in
# harder than predicted: chrF++ ranks the ineligible set *above* the lowest
# graded band, so the planned comparison cannot adjudicate the boundary and a
# yardstick that is not chrF++ is needed for it.

def within_eligible(langs, elig):
    """Ordering power among languages that clear the filter, where chrF++ is
    at least measuring the same thing on both sides of the comparison."""
    el = [l for l in langs if l.s_lang_voidless >= elig and l.s_content is not None]
    print(f"\nwithin the eligible set (n={len(el)}), Spearman vs mean chrF++")
    rho_c = spearman([l.s_content for l in el], [l.chrf for l in el])
    print(f"  s_content, continuous{'':<38}{rho_c}")
    out = {"n": len(el), "s_content": rho_c, "bins": {}}
    for cut in (0.50, 0.70, 0.85, 0.95):
        binned = [1.0 if l.s_content >= cut else 0.0 for l in el]
        rho = spearman(binned, [l.chrf for l in el])
        lo = [l.chrf for l, b in zip(el, binned) if b == 0.0]
        hi = [l.chrf for l, b in zip(el, binned) if b == 1.0]
        print(f"  two bands at {cut:<4}  n {len(lo):>3}/{len(hi):<3} "
              f"mean chrF++ {mean(lo):>5.1f} / {mean(hi):<5.1f}   {rho}")
        out["bins"][str(cut)] = {"n_low": len(lo), "n_high": len(hi),
                                 "mean_chrf_low": round(mean(lo), 1),
                                 "mean_chrf_high": round(mean(hi), 1), "spearman": rho}
    return out


def ineligible_detail(langs, elig, top=12):
    """Which ineligible languages carry the high chrF++, and why."""
    inel = sorted((l for l in langs if l.s_lang_voidless < elig),
                  key=lambda l: -l.chrf)
    print(f"\nineligible languages by mean chrF++ (threshold {elig})")
    print(f"  {'tag':<10}{'chrF++':>8}   verdicts")
    for l in inel[:top]:
        print(f"  {l.tag:<10}{l.chrf:>8.1f}   {', '.join(l.verdicts)}")
    return [{"tag": l.tag, "mean_chrf": l.chrf, "verdicts": l.verdicts} for l in inel]


def script_audit(langs, study, elig):
    """The one yardstick that is not a model and not chrF++.

    Protocol 016 checked 119 items this way and found the deterministic gate
    caught 15 of 15 script mismatches an LLM adjudicator missed entirely. Here
    the same check runs over the whole study, to ask whether the languages the
    eligibility filter rejects are ones a reader would also reject.
    """
    from llmlc.probe.lid import detect_script
    from llmlc.scheme.loader import load_scheme

    scheme = load_scheme("default")
    by_tag = {r["tag"]: r for r in study["languages"]}
    rows = {"eligible": [0, 0], "ineligible": [0, 0]}   # [wrong script, total]
    unknown = 0
    for l in langs:
        lang = scheme.get(l.tag)
        expect = lang.script if lang else None
        if not expect:
            unknown += 1
            continue
        key = "eligible" if l.s_lang_voidless >= elig else "ineligible"
        for item in by_tag[l.tag]["items"]:
            text = item.get("translation") or ""
            got = detect_script(text)
            if not got:
                continue
            rows[key][1] += 1
            if got != expect:
                rows[key][0] += 1
    print(f"\nscript audit (deterministic, no model), threshold {elig}")
    for key, (wrong, total) in rows.items():
        share = f"{wrong / total:.0%}" if total else "—"
        print(f"  {key:<12}{wrong:>4} of {total:<5} items in the wrong script   {share}")
    if unknown:
        print(f"  ({unknown} languages carry no expected script in the scheme)")
    return {k: {"wrong_script": v[0], "items": v[1]} for k, v in rows.items()}


def main() -> int:
    if not STUDY.exists():
        print(f"missing {STUDY}", file=sys.stderr)
        return 1
    study = json.loads(STUDY.read_text(encoding="utf-8"))
    regate = json.loads(REGATE.read_text(encoding="utf-8")) if REGATE.exists() else {}
    if not regate:
        print("no regate.json — run scripts/regate.py first", file=sys.stderr)
        return 1
    langs = [Lang(r, regate) for r in study["languages"]]
    langs = [l for l in langs if l.n and l.s_content_all is not None]
    print(f"{len(langs)} scored languages, {sum(l.n for l in langs)} paired items")

    # -- descriptive: what the gate verdicts actually are ---------------------
    verdicts: dict[str, int] = {}
    for l in langs:
        for v in l.verdicts:
            verdicts[v] = verdicts.get(v, 0) + 1
    print("\ngate verdicts across items")
    for v, n in sorted(verdicts.items(), key=lambda kv: -kv[1]):
        kind = "negative" if v in NEGATIVE else ("pass" if v == "pass" else "void")
        print(f"  {v:<24}{n:>5}  ({kind})")

    out: dict = {"n_languages": len(langs), "verdicts": verdicts, "scales": []}

    # -- the signals, on their own -------------------------------------------
    print("\nsignal vs mean chrF++ (Spearman, by language)")
    signals = {
        "s_content (over gate-passing items, production semantics)":
            ([l.s_content for l in langs if l.s_content is not None],
             [l.chrf for l in langs if l.s_content is not None]),
        "s_content (over all items, as 017 scored it)":
            ([l.s_content_all for l in langs], [l.chrf for l in langs]),
        "s_lang (as computed today)": ([l.s_lang for l in langs], [l.chrf for l in langs]),
        "s_lang (voids excluded)":
            ([l.s_lang_voidless for l in langs], [l.chrf for l in langs]),
    }
    out["signals"] = {}
    for name, (xs, ys) in signals.items():
        rho = spearman(xs, ys)
        out["signals"][name] = {"n": len(xs), "spearman": rho}
        print(f"  {name:<58}{rho}  (n={len(xs)})")

    # -- H5: does excluding voids move anyone across the line? ---------------
    print("\nH5 — void exclusion, at eligibility threshold 0.5")
    moved = [l for l in langs
             if (l.s_lang >= 0.5) != (l.s_lang_voidless >= 0.5)]
    print(f"  {len(moved)} of {len(langs)} languages cross the line: "
          f"{', '.join(sorted(l.tag for l in moved)) or '—'}")
    out["h5_moved"] = sorted(l.tag for l in moved)
    for l in sorted(moved, key=lambda x: x.tag):
        print(f"    {l.tag:<10} pass {l.n_pass}  negative {l.n_negative}  void {l.n_void}"
              f"   verdicts {l.verdicts}")

    # -- H6: threshold sensitivity -------------------------------------------
    print("\nH6 — eligibility threshold sensitivity (voids excluded)")
    base = {l.tag for l in langs if l.s_lang_voidless >= 0.5}
    for t in (0.5, 0.75, 0.95):
        eligible = {l.tag for l in langs if l.s_lang_voidless >= t}
        print(f"  threshold {t:<6} eligible {len(eligible):>3}   "
              f"differs from 0.5 by {len(base ^ eligible)}")
    out["h6"] = {str(t): sorted(l.tag for l in langs if l.s_lang_voidless >= t)
                 for t in (0.5, 0.75, 0.95)}

    # -- the current scale, for the baseline ---------------------------------
    out["scales"].append(report(
        "current five tiers (probe/score.py today)", CURRENT_ORDER,
        lambda l: current_tier(l.s_lang, l.s_content if l.s_content is not None else 0.0),
        langs))

    # -- H2: is the ineligible set below the eligible bands? -----------------
    print("\nH2 — where the ineligible set sits on the yardstick")
    for t in (0.5, 0.75):
        inel = [l for l in langs if l.s_lang_voidless < t]
        el = [l for l in langs if l.s_lang_voidless >= t]
        print(f"  threshold {t}: ineligible n={len(inel)} mean chrF++ "
              f"{mean([l.chrf for l in inel]):.1f}   "
              f"eligible n={len(el)} mean chrF++ {mean([l.chrf for l in el]):.1f}")
    out["h2"] = {str(t): {"ineligible_mean_chrf":
                          round(mean([l.chrf for l in langs if l.s_lang_voidless < t]), 1),
                          "eligible_mean_chrf":
                          round(mean([l.chrf for l in langs if l.s_lang_voidless >= t]), 1)}
                 for t in (0.5, 0.75)}

    # -- H1/H3/H4: candidate scales ------------------------------------------
    ELIG = 0.5
    candidates = [
        ("2 bands: Unusable / Adequate", [], ["Adequate"]),
        ("3 bands, cut 0.50", [0.50], ["Assisted", "Proficient"]),
        ("3 bands, cut 0.70", [0.70], ["Assisted", "Proficient"]),
        ("3 bands, cut 0.85", [0.85], ["Assisted", "Proficient"]),
        ("3 bands, cut 0.95", [0.95], ["Assisted", "Proficient"]),
        ("4 bands, cuts 0.50/0.85", [0.50, 0.85], ["Assisted", "Proficient", "Strong"]),
        ("4 bands, cuts 0.70/0.95", [0.70, 0.95], ["Assisted", "Proficient", "Strong"]),
    ]
    for title, cuts, names in candidates:
        order = ["Unusable"] + names
        out["scales"].append(report(
            title + f"  (eligibility s_lang ≥ {ELIG}, voids excluded)", order,
            lambda l, c=cuts, nm=names: bin_tier(
                l.s_lang_voidless >= ELIG, l.s_content, c, nm),
            langs))

    # -- choosing the eligibility threshold on evidence, not on taste --------
    print("\neligibility threshold sweep, adequacy cut fixed at 0.95")
    out["elig_sweep"] = {}
    for t in (0.5, 0.75, 0.95):
        r = report(f"  eligibility ≥ {t}", ["Unusable", "Assisted", "Proficient"],
                   lambda l, tt=t: bin_tier(l.s_lang_voidless >= tt, l.s_content,
                                            [0.95], ["Assisted", "Proficient"]),
                   langs)
        r["script_audit"] = script_audit(langs, study, t)
        out["elig_sweep"][str(t)] = r

    # -- the scale as shipped, not as prototyped ------------------------------
    # The candidates above are prototypes written in this script. This one calls
    # probe/score.py itself, so the protocol's table and the code cannot drift.
    from llmlc.probe.score import ORDER as SHIPPED_ORDER
    from llmlc.probe.score import tier_for as shipped_tier_for
    out["shipped"] = report(
        "the scale as shipped (probe/score.py)", [t.value for t in SHIPPED_ORDER],
        lambda l: shipped_tier_for(
            l.s_lang_voidless, l.s_content if l.s_content is not None else 0.0).value,
        langs)

    out["within_eligible"] = within_eligible(langs, ELIG)
    out["ineligible"] = ineligible_detail(langs, ELIG)
    out["script_audit"] = script_audit(langs, study, ELIG)

    pathlib.Path("data/calibration/rescale.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\nwrote data/calibration/rescale.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
