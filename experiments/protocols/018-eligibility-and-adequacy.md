# 018 — Does an eligibility-plus-adequacy scale survive the data that broke the five tiers?

| | |
|---|---|
| **Date** | 2026-09-25 |
| **Status** | valid — **two of the six hypotheses were wrong, and the run found a defect that invalidates one of protocol 017's measurements** |
| **Triggered by** | [Protocol 017](017-are-the-tiers-measurable.md) showed the five-tier scale is not measurable: `Basic` never occurs, `Usable` ranks *below* `None`, and `tier_for()` orders languages worse (ρ 0.436) than one of its own inputs (ρ 0.664). 017 named the replacement but did not test it |
| **Artifacts** | `scripts/rescale.py`, `scripts/regate.py`, `data/calibration/rescale.json`, `data/calibration/regate.json`, `tests/test_scale_on_calibration.py`. Re-analysis only — no model calls |

## What is being proposed

Three protocols now point the same way, and the redesign follows from them directly:

| component | current role | proposed role | evidence |
|---|---|---|---|
| deterministic gate (`s_lang`) | first term of the grade, hard pre-gate with three thresholds | **eligibility filter**, one threshold: wrong script or wrong language means unusable, full stop | [016](016-which-metric-is-wrong.md): an LLM missed 15/15 script mismatches the gate caught. [017](017-are-the-tiers-measurable.md): the gate is a poor quality signal (ρ 0.370) |
| fact recall (`s_content`) | second term, binned into four coarse buckets | **the graded measurement**, published as a continuous number | [017](017-are-the-tiers-measurable.md): ρ 0.664, the best signal available. [016](016-which-metric-is-wrong.md): right about 90% of disputed items |
| tier | the headline output, five values | a lossy routing convenience **derived** from the number — monotonic, and fewer than five | [017](017-are-the-tiers-measurable.md): every discretisation tested lost signal |

Two details of the current code are in scope because the redesign exposes them:

- **`s_lang`'s three thresholds (0.95 / 0.90 / 0.80) cannot be distinguished below n = 20 items** (017, H4). At the ladder's 3 items they are one threshold wearing three hats. They collapse to one. Buying the resolution with more items is the wrong trade for a tool whose value is breadth, so the number of items does not change.
- **The gate has verdicts that are not accusations.** `low_confidence` and `too_short` void an item — `probe/gate.py` says so in as many words: *"too weak to count against the model"*. But `ItemOutcome.lang_ok` is `gate.passed`, so a voided item currently counts against `s_lang` exactly like a wrong-language one. If eligibility is to mean "the model produced the requested language", voids belong outside the denominator, not inside it as failures.

## Hypothesis

Recorded before the re-analysis was written.

1. **Monotonic within the eligible set.** Tiers formed by binning `s_content` among languages that clear the eligibility filter will be **strictly monotonic in mean chrF++** — each band above the one below it, with no inversion. This is the property the current scale lacks (`Usable` 20.9 below `None` 34.5) and the minimum bar for shipping anything.

2. **Eligibility will *not* be monotonic against chrF++, and that is expected rather than a failure.** Ineligible languages will average a mean chrF++ **at or above** the lowest eligible band, because chrF++ rewards a wrong-but-related language: protocol 014's `ace` scored chrF++ 37 for answering in Indonesian. Predicted: mean chrF++ of the ineligible set ≥ 25, overlapping the bottom eligible band rather than sitting below it.
   **This hypothesis is the one that decides how the result may be argued.** If it holds, chrF++ cannot adjudicate the eligibility filter at all, and the filter stands on 016's 15/15 script finding — a correctness requirement, not a quality dimension. If instead the ineligible set sits clearly below every eligible band, the gate *is* a quality signal, 017's H2 was mis-read, and the whole redesign needs revisiting.

3. **Two graded bands above the floor are all the data supports.** Splitting the eligible languages' `s_content` three ways will produce either an inversion or a band holding fewer than 5 of the ~98 languages; splitting two ways will do neither. Fact recall is an adequacy floor (016), and a floor has one edge.

4. **The derived tier loses ordering to the continuous score, and that loss is the price of routing.** ρ(derived tier vs mean chrF++) will land **below 0.664** (the continuous `s_content`) and **above 0.436** (the current five tiers). Predicted range 0.45–0.60. Anything at or above 0.664 would mean discretising added information, which is not possible, and would indicate a bug in the analysis.

5. **Excluding void verdicts from the eligibility denominator changes few languages but changes them correctly.** Fewer than 15 of 98 languages will move across the eligibility line, and the ones that move will be languages where LID was unsure rather than languages that produced the wrong text.

6. **The single eligibility threshold is insensitive across the range the ladder can express.** At 3–4 items per language, `s_lang` takes four or five distinct values, so thresholds of 0.5, 0.75 and 0.95 partition into at most three distinct eligible sets. Predicted: moving the threshold between 0.5 and 0.95 moves fewer than 20 of 98 languages.

**What would sink the proposal rather than adjust it:** a failure of H1 — no binning of `s_content` among eligible languages that is monotonic in chrF++. That would mean the continuous score cannot be discretised at all, and the tool would have to report a number and refuse to route on it.

## What is being tested

Whether the scale named in 017's *Impact* section, built and applied to the same 100-language calibration set, produces an ordering that is monotonic, better than the scale it replaces, and honest about what it gives up. Not whether it is better than chrF++ — 016 settled that chrF++ is the wrong arbiter for individual items, and it is used here only as the one independent per-language signal available.

## Setup

| | |
|---|---|
| Models | none. Re-analysis of an existing run |
| Data | `data/calibration/study.json` — 100 languages, 4 FLORES items each, 378 paired items, 98 languages scored (protocol 014's run: `openai-gpt-4o`, judge `openai-gpt-4o-mini`, panel `gemini-gemini-3-8-flash` / `deepseek-deepseek-v4-pro`, pivot `en`) |
| Yardstick | mean chrF++ per language, with 016's caveat attached: it is an imperfect target, and a design tuned to it is tuned to an imperfect target |
| Sample | the same 98 scored languages 017 used, so the two analyses are directly comparable |

## Method

Re-analysis of the 100-language calibration run. For each language, `s_lang` and
`s_content` are recomputed from the per-item gate verdicts and fact-recall
scores, candidate scales are applied, and each is scored by how well it orders
languages against mean chrF++ — plus, crucially, whether it orders them
*monotonically*, which is a separate question and the one the old scale failed.

`s_content` is computed **over gate-passing items only**, because that is what
production does: `probe/pipeline.py` never back-translates an item the gate
rejected, so a rejected item contributes no content score. Protocol 017 averaged
over all items. The difference is not cosmetic — production semantics score
0.686 against chrF++ where all-items scores 0.647 — and the production figure is
the one that describes the tool.

`scripts/rescale.py` runs the whole analysis and writes `rescale.json`. Its final
table calls `probe/score.py` directly rather than a prototype, so the numbers
below and the shipped code cannot drift apart.

## The run did not survive first contact: the study's gate verdicts were wrong

The first pass produced a result that made no sense. The ineligible languages —
those the gate said were not in the requested language at all — were led by
**Swahili at mean chrF++ 79.8, Malay at 67.1 and Tagalog at 60.7**, each with
four of four items marked `wrong_language`. A model does not score chrF++ 80
against the Swahili reference by writing something other than Swahili.

`probe/calibrate.py` calls the gate like this:

```python
gate = gate_check(gen.text, prompt=prompt, expect_lang=lang.iso639_3,
                  expect_script=lang.script)
```

`probe/pipeline.py` — the production path — passes two more arguments:
`accept_lang` and `relatives`. Without `accept_lang`, **a macrolanguage that
correctly resolves to one of its own members is convicted of `wrong_language`.**
Asking for Swahili (`swa`) and receiving Coastal Swahili (`swh`) is the
macrolanguage resolving to a member, which is the answer — `pipeline._accepted`
exists to say exactly that. Swahili, Malay, Albanian, Estonian, Uzbek, Mongolian
and Nepali are all macrolanguages in the shipped scheme, and all of them were
scored as total failures.

So the `gate` field in `data/calibration/study.json` **was never produced by the
gate this tool runs.** It came from a stricter instrument that exists nowhere
else in the codebase.

`scripts/regate.py` recomputes the verdicts with production semantics, from the
committed translations and the local GlotLID model — free, deterministic, no
model calls. **68 of 385 item verdicts change.** Everything below uses the
corrected verdicts; the comparison against the old scale is recomputed on them
too, so the two scales are judged on the same data.

### What this does to protocol 017

[Protocol 017's H2](017-are-the-tiers-measurable.md) reported `s_lang` at
Spearman 0.370 against mean chrF++ and concluded the gate is a poor quality
signal. On corrected verdicts it is **0.524**. That measurement is withdrawn.

The conclusion it supported does not change, and this is worth being precise
about. `s_content` is still the better signal, 0.686 against 0.524, and 017's
headline finding — that the five-tier assignment orders languages worse than one
of its own inputs — reproduces on corrected data at 0.595 against 0.686, still
non-monotonic, still with `Basic` empty. **The redesign stands on a result that
survived the bug; only the size of the gap between the two signals was wrong.**

| signal, by language, vs mean chrF++ | as 017 measured it | corrected |
|---|---|---|
| `s_content`, over gate-passing items (production) | — | **0.686** |
| `s_content`, over all items | 0.647 | 0.647 |
| `s_lang`, as computed today | 0.370 | **0.524** |
| `s_lang`, voids excluded | — | 0.520 |

## Results

98 scored languages, 378 paired items. Gate verdicts after correction: 283
`pass`, 35 `wrong_language`, 19 `relative_substitution`, 18 `wrong_script`, 10
`degenerate`, 8 `low_confidence`, 5 `too_short`.

### The old scale, on corrected data

| simulated tier | n | mean chrF++ |
|---|---|---|
| None | 20 | 28.4 |
| Token | 16 | 32.0 |
| **Basic** | **0** | — |
| **Usable** | **4** | **25.5** |
| Strong | 58 | 51.8 |

ρ 0.595, **not monotonic**: `Usable` still sits below `None` and `Token`, and
`Basic` is still empty. The fix to the verdicts did not rescue the scale.

### H1 — monotonic within the eligible set: confirmed

Every binning of `s_content` among eligible languages is monotonic in mean
chrF++. The inversion is never inside the graded set; it is only ever at the
eligibility boundary, which is H2's subject.

### H2 — wrong, but only just, and the reason matters

I predicted the ineligible set would sit **at or above** the lowest graded band,
because chrF++ rewards a wrong-but-related language. On corrected verdicts it
sits just below: **29.0 against 31.4** — 2.4 chrF++ points, on 19 languages
against 27.

So chrF++ does order the boundary correctly, and it does so by a margin far too
small to be the reason for anything. The prediction's *reasoning* was sound —
before the verdicts were corrected, the ineligible set led with Swahili at 79.8
and the boundary inverted hard. What that turned out to measure was the harness
bug, not the metric.

**The filter therefore needs a yardstick that is not chrF++, and there is one.**
Protocol 016 checked 119 items for script correctness deterministically; the same
check runs here over all 378:

| | wrong script | items | |
|---|---|---|---|
| eligible (`s_lang` ≥ 0.5) | 4 | 304 | **1%** |
| ineligible | 23 | 74 | **31%** |

The filter concentrates 23 of 27 wrong-script items into 19% of the sample and
leaves the graded set 1% contaminated. That is a measurement of the filter doing
its job, it involves no model and no reference translation, and it is the
justification the eligibility threshold actually rests on.

### H3 — wrong. Three bands work, with the cut at the top

I predicted that splitting the eligible set three ways would produce an inversion
or a band under 5 languages, and that only two bands would survive. Three bands
survive, provided the cut is placed where protocol 016 says the signal is:

| adequacy cut | Unusable | Assisted | Proficient | ρ | monotonic |
|---|---|---|---|---|---|
| 0.50 | 19 · 29.0 | 2 · 14.0 | 77 · 46.8 | 0.404 | no |
| 0.70 | 19 · 29.0 | 9 · 20.2 | 70 · 49.3 | 0.539 | no |
| 0.85 | 19 · 29.0 | 18 · 28.4 | 61 · 51.2 | 0.591 | no |
| **0.95** | **19 · 29.0** | **27 · 31.4** | **52 · 53.6** | **0.647** | **yes** |

*(cells are `n · mean chrF++`)*

Only 0.95 is monotonic, and it is also the best of the four. Four-band variants
were tested and none is monotonic.

**This is protocol 016's result arriving as a design constraint.** 016 established
that fact recall is an *adequacy floor*, not a quality gradient — above a
threshold adequacy is close to binary. A floor has one edge, and the edge is at
the top: "essentially every required fact survived". Cutting a floor in the
middle, at 0.50 or 0.70, splits off a band of 2 or 9 languages that is not a
quality band at all. The three low cuts fail for the same reason 015's attempt to
sharpen the metric failed.

### H4 — wrong in the direction worth being wrong in

Predicted ρ 0.45–0.60 for the derived tier. Measured **0.647**, against 0.686 for
the continuous score it is derived from. The loss to discretisation is **0.04**,
where the old scale lost about a third of its inputs' ordering.

### H5 — confirmed

Excluding voided verdicts from the eligibility denominator moves exactly **one**
language of 98 across the line: `kmb` (Kimbundu), whose three items are
`degenerate`, `pass`, `low_confidence` — one accusation, one pass, one item the
gate declined to rule on. Under the old arithmetic that is 1/3 and ineligible;
under the new one it is 1/2 and eligible, which is what "too weak to count
against the model" meant all along.

Small, and worth doing anyway: it makes the code match the comment that was
already in `probe/gate.py`, and the cases it affects are exactly the ones where
the instrument, not the model, was the weak link.

### H6 — confirmed

| eligibility threshold | Unusable | Assisted | Proficient | ρ | monotonic | wrong script in eligible set |
|---|---|---|---|---|---|---|
| **0.50** | 36 → 19 · 29.0 | 27 · 31.4 | 52 · 53.6 | 0.647 | yes | **1%** (4 / 304) |
| 0.75 | 31 · 30.7 | 20 · 33.6 | 47 · 54.5 | 0.635 | yes | 2% (4 / 259) |
| 0.95 | 36 · 30.0 | 16 · 36.5 | 46 · 54.8 | 0.668 | yes | 2% (4 / 239) |

All three are monotonic and ρ varies by 0.03. The threshold is not load-bearing,
which is the useful finding: **0.5 is chosen because it is the cheapest filter
that catches everything.** All three settings capture the same 23 wrong-script
items; 0.5 rejects 74 items to do it, 0.95 rejects 139. Rejecting 65 more items
to catch nothing more is a filter that has stopped filtering and started
guessing.

## Three residual defects, found and not fixed

Reading the ineligible list item by item, as convention 6 requires, turned up
three failures that are the *instrument's*, not the model's. None changes the
scale, and each would produce a false "unusable" — which matters more now than it
did, because the filter is no longer one term among several.

1. **`tl` — Tagalog convicted for writing Filipino.** chrF++ 60.7, four of four
   `wrong_language`, GlotLID calling it `fil_Latn` at 0.99. Filipino is the
   standardised register of Tagalog, but the two are separate ISO codes with no
   macrolanguage relation, so `accept_lang` does not cover it. Needs an explicit
   acceptance pair, and the scheme may hold others.

2. **Chinese is unmeasurable as shipped.** `zh-CN` and `yue` fail on two
   independent instrument defects at once: `lid.detect_script` maps every CJK
   ideograph to `Hani` while the scheme expects `Hans` / `Hant`, so every item is
   `wrong_script`; and `MIN_CHARS = 25` convicts a correct Chinese sentence as
   `too_short`, because Chinese says in 20 characters what English needs 90 for.
   Behind the script bug sits a genuine finding the tool currently cannot report:
   asked for Cantonese, the model returned Mandarin at LID 0.91.

3. **`mag` → `bho`.** Magahi answered in Bhojpuri. The conviction is correct;
   only its label is wrong — `wrong_language` rather than `relative_substitution`,
   because the two are not macrolanguage siblings in the scheme even though they
   are neighbours in fact.

These are recorded rather than fixed because each needs its own evidence. In
particular, `Hani` versus `Hans`/`Hant` is not a coding slip: simplified and
traditional are a distinction the tool *should* catch, and `detect_script` cannot
see it at all. That is a protocol, not a patch.

## Conclusions

1. **The scale is now three parts, and only one of them is a measurement.**
   Eligibility filters, adequacy grades and is published as a number, and the
   tier is a lossy view of that number for routing. Measured on 98 languages:
   monotonic, ρ 0.647 against the continuous score's 0.686.

2. **The eligibility filter is justified by the script audit, not by chrF++.**
   31% of items in the rejected set are in the wrong writing system against 1% in
   the kept set. chrF++ happens to order the boundary correctly by 2.4 points,
   which is not enough to lean on and is not what the filter is for. A model that
   writes fluent Indonesian when asked for Acehnese is unusable for Acehnese
   whatever its surface overlap with the reference.

3. **The adequacy cut belongs at 0.95 because adequacy is a floor.** This is the
   design consequence of protocol 016, and it is the only cut of four tested that
   orders the tiers monotonically. Cutting lower splits off a band of 2 to 9
   languages that is not a quality band.

4. **An analysis harness that re-implements a production call will drift from
   it, and the drift will look like a finding.** 68 of 385 verdicts, one
   withdrawn correlation in protocol 017, and a first-pass result that put
   Swahili at chrF++ 79.8 in the "not Swahili" bucket. The gate call is now
   shared, and the scale has a test that runs it over the calibration study
   rather than over invented numbers.

**Limits:** one model, one judge, one back-translator panel, four items per
language, a translation task standing in for free generation, and chrF++ as the
ordering yardstick with protocol 016's caveat that it is an imperfect one. The
monotonicity result and the script audit are the robust findings; the exact
correlations are not. The residual defects above mean the ineligible set still
contains at least three languages that do not belong in it, which makes the
eligible set's 1% script contamination a slightly optimistic figure and the
filter's rejection rate a slightly pessimistic one.

## Impact

- `probe/score.py` rewritten: `Tier` is `Unusable` / `Assisted` / `Proficient`,
  `ELIGIBLE_MIN_LANG = 0.50` replaces three `s_lang` thresholds,
  `PROFICIENT_MIN_CONTENT = 0.95` replaces four `s_content` bins, and `eligible`
  joins the output. **None of the three names is reused from the old scale**, so a
  1.x tier string fails to parse instead of reading as comparable.
- `probe/pipeline.py` passes a void count to scoring; `ItemOutcome.lang_void`
  names the distinction the gate module already described in prose.
- `probe/calibrate.py` shares the production gate call. This is the bug above.
- `export/adapters.py` derives its mergeable set from `export/artifacts.py`
  instead of restating it. It held a hand-written `{"Basic", "Usable", "Strong"}`
  that the rename would have turned into a silent empty export — every tier
  excluded, no error raised, a consuming system quietly told nothing is
  supported.
- `METHOD_VERSION` 1.0.0 → 2.0.0. All 11 stored results are now stale, and
  `llmlc status` says so.
- `tests/test_scale_on_calibration.py` runs the shipped scale over the study and
  asserts monotonicity, that every tier is reachable, and that discretising costs
  less than 0.10 of Spearman. The old scale passed every unit test it had while
  being non-monotonic on data, because nothing ever ran it over data.
- The CLI leads with the content score and prints the tier under it.
- **S8 is unblocked.** It should lead with protocol 016's script finding — 15/15
  against 0/15 — and can now document a scale that has been measured rather than
  asserted.
