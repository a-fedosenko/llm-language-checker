# Experiment protocols

Every test run against a live model or a new dependency gets a protocol here,
written at the time rather than reconstructed afterwards. The point is that a
reader — including a future us — can tell what was measured from what was
assumed, and can see which results were later invalidated.

Each protocol records: the hypothesis before the test, what was actually tested,
what was used (models, parameters, libraries, data), the results including the
inconvenient ones, the conclusions with their limits, and how the project
changed as a result.

`TEMPLATE.md` is the shape. Numbering is chronological.

| # | Date | Experiment | Outcome |
|---|---|---|---|
| [001](001-invented-language-control.md) | 2026-09-15 | Invented-language control: does the tag self-report method fabricate? | Confirmed. 9–10 of 10 nonexistent languages received confident tags |
| [002](002-reasoning-mode-confound.md) | 2026-09-15 | Was the cross-model comparison confounded by reasoning mode? | Yes. One conclusion withdrawn; reasoning disabled for all measurement |
| [003](003-hardware-and-gpu.md) | 2026-09-15 | Can the reference machine run local ML, and in Docker? | Yes. RTX 4060 8 GB, GPU passthrough works, `gpu-int8` profile |
| [004](004-glotlid-capability.md) | 2026-09-16 | Is GlotLID accurate enough to carry the deterministic gate? | Yes, and it confirmed two predicted failure modes on live data |
| [005](005-backtranslator-fabrication.md) | 2026-09-16 | Does an unqualified back-translator corrupt results? | Severely. A verdict moved two tiers. Qualification pulled forward to S1 |
| [006](006-chrf-as-qualification-metric.md) | 2026-09-16 | Can chrF++ replace a judge call for qualification? | Yes. Fabricated 10.5 vs faithful 81.9; threshold 30 |
| [007](007-flores-sourcing-and-mapping.md) | 2026-09-16 | Is FLORES obtainable without auth, and does it map to our scheme? | Meta's tarball is ungated; 200/204 map; Chuvash absent |
| [008](008-twenty-language-spread.md) | 2026-09-16 | Does the pipeline hold up across 20 languages? | 20/20 real evidence, and it exposed two systematic bugs |
| [009](009-ladder-and-designator-sweep.md) | 2026-09-17 | Do the ladder, class collapse and designator sweep pay off? | 9.2 calls/tag; the endonym beats the English name on some long-tail languages |
| [010](010-country-qualified-designators.md) | 2026-09-17 | Should the designator name the country? | No — it does not help, and it produced the one wrong-language output. Underpowered |
| [011](011-reliability-and-tier.md) | 2026-09-17 | Should low reliability cap the tier? | No. n=3 cannot support a cap, and it would restate unwillingness as inability. Availability became a second axis |

## Writing one

Start it before the run, not after. The hypothesis is only useful if it was
recorded while it could still turn out to be wrong — 001 and 005 are the two
that mattered most, and in both cases the prediction was written down first.

Record the inconvenient results. Protocol 002 exists because a conclusion in 001
had to be withdrawn; 005 exists because a documented claim turned out to be
backwards. Those are the entries a reader should be able to find.
