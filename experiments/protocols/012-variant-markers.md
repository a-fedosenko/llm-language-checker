# 012 — Variant marking: can a closed marker set measure dialect ability?

| | |
|---|---|
| **Date** | 2026-09-18 |
| **Status** | valid |
| **Triggered by** | S6. Every variant tag inherited its macrolanguage's tier with `variant_evidence: untested`, a placeholder whose alternative had never been tested |
| **Artifacts** | `markers/english.json`, `src/llmlc/probe/markers.py`, `src/llmlc/probe/variant.py`, raw responses in `experiments/results/variant_markers.jsonl` (round 1) and `variant_markers_round2.jsonl` (round 2), corpus in `data/corpus/` |

## Hypothesis

Recorded before any variant probe was run.

1. **A closed marker set discriminates.** Asked to write `en-AU` under an elicitation context engineered to force the choice, gpt-4o will produce variant markers (`boot`, `petrol`, `-ise`) at a materially higher rate than sibling markers (`trunk`, `gas`, `-ize`). Predicted variant rate **> 0.7**.
2. **The base tag is not neutral.** The same contexts sent with the plain `en` designator will lean **sibling** (American), because CLDR's likely subtag for `eng` is `en-US` and the training distribution leans the same way. If `en` came out at the same variant rate as `en-AU`, the marker probe would be measuring the context rather than the designator, and the method would be dead.
3. **Void items will be rare but non-zero.** Predicted < 20%.
4. **Orthography is easier than lexis.** `-ise`/`-our` should be marked more reliably than lexical shibboleths, because orthography is a global property of the model's register and lexis needs the specific word to come up.

The prediction I most expect to be wrong is (2): a strong showing for `en` on Australian markers would mean the elicitation contexts leak the answer.

## What was tested

A two-arm comparison. The same elicitation contexts were sent twice — once under the variant designator (`Australian English`, `British English`) and once under the plain base designator (`English`) — and both arms were scored against the same marker set. The base arm is the control: it is what the contexts alone produce.

Two rounds, because the first found defects in the instrument.

## Setup

| | |
|---|---|
| Models | `openai-gpt-4o` through the configured aggregator |
| Parameters | temperature 0, `max_tokens` 400, `reasoning_effort: none`, 3 sentences per item |
| Libraries / data | `markers/english.json` (unreviewed draft), GlotLID v3 for the gate |
| Sample | round 1: 12 generations (2 tags × 2 arms × 3 contexts). Round 2: 16 (4 contexts) |

## Method

For each tag, each arm and each context: generate, gate, then score the text by counting variant markers against sibling markers. An item where neither appears is **void** — the context failed, not the model. The per-tag score is the mean rate over scoreable items.

No marker is ever named in the prompt. The prompt carries the designator and the situation; nothing else.

## Results

**Round 2, after the fixes below (means over scoreable items):**

| tag | variant arm | base arm | void |
|---|---|---|---|
| `en-AU` | **1.00** | 0.00 | 1 of 4 |
| `en-GB` | **1.00** | 0.11 | 1 of 4 |

Hypotheses 1 and 2 are confirmed, and 2 — the one most likely to kill the method — is confirmed decisively. The same context produces `boot`/`petrol`/`car park` under "Australian English" and `trunk`/`gas`/`parking lot` under "English". The designator does the work, not the context.

Void rate was **25%**, above the predicted 20%, and all of it came from one context — the hospital/treatment one, which targets the grammar axis.

**Hypothesis 4 was wrong, and in an instructive way.** Across every scoreable item, the axis breakdown was:

| axis | variant hits | sibling hits |
|---|---|---|
| lexis | 8 | 0 |
| orthography | 4 | 0 |
| **grammar** | **0** | **0** |

Lexis fired everywhere. Orthography fired only in the one context written specifically to force it — and only after the inflection fix below. **The grammar axis never fired once**, in any item, in either round. Three-sentence narrative prose does not reach for *in hospital* or *different to*.

### Three defects in the instrument, all found by running it

**1. The elicitation contexts leaked markers.** One `en-GB` context read *"leaving a block of flats in autumn, walking to the nearest underground station"* — naming three of its own markers. The American arm then scored hits by echoing the prompt, which is why round 1's `en-GB` base arm scored 0.50. This is the rule docs/01 already states — *the markers are never named in the prompt* — broken by accident in the contexts rather than the instructions.

**2. `pavement` does not discriminate.** gpt-4o wrote it unprompted in the American arm, where it means the road surface. It was a marker in the `en-GB` lexis list and has been removed. Same failure class as `chips`, which was caught at authoring time.

**3. Inflected forms were invisible, asymmetrically.** The marker `neighbour` did not match "neighbours", while the sibling `neighbor` did match "neighbor's" — because an apostrophe is a word boundary and a plural `s` is not. The orthography-targeted context scored **void** in the variant arm and **0.00** in the base arm, when both had plainly made the choice. This did not merely lower the score, it *moved* it.

The fix is a morphological rule — a single-word marker matches its regular inflections, including the dropped `e` of *organise → organising* — and it was validated by **re-scoring round 2's saved responses offline**, with no new model calls. That is the corpus-as-durable-asset principle from docs/01 doing exactly what it was designed for:

| item | before | after |
|---|---|---|
| `en-AU` variant, orthography context | void | **1.00** |
| `en-GB` variant, orthography context | void | **1.00** |
| `en-AU` base, orthography context | 0.00 | 0.00 |

### Two bugs found in the surrounding pipeline

**The designator omitted the script for exactly the tags that need it.** Candidate A qualified a language by script *unless the script was Latin* — right for most languages, and precisely wrong for `kk-Latn`, whose marked script *is* Latin. `kk-Latn` was therefore asked for as plain "Kazakh", answered in Cyrillic, and recorded as failing to produce Latin Kazakh. It was the correct answer to the question we actually asked. This is docs/02's rule — a negative must mean "none under our best designator" — violated by a heuristic written before script variants existed.

**A model that answered every item wrongly was scored as having refused every item.** The deterministic-negative path passed an empty `lang_pass` list, so attempts came out as zero and `reliability` as 0.00 — indistinguishable from total refusal, and under S5's availability bands it would have read `refused` for a model that was entirely willing.

### What the corrected run found

| tag | mechanism | variant evidence | what happened |
|---|---|---|---|
| `en-AU` | markers | **proven** (1.00) | marks Australian English on demand |
| `en-GB` | markers | **proven** (1.00) | marks British English on demand |
| `ru-BY` | declared | **not-distinguishable** | inheriting `ru` is correct, not a fallback |
| `sr-Latn` | script | **proven** (1.00) | 3 of 3 items in Latin script |
| `kk-Latn` | script | **untested** | see below |

`kk-Latn` is the interesting one. Asked properly — "Kazakh (Latin script)" — gpt-4o produced **Latin script that GlotLID identified as Crimean Tatar and Turkmen**, not Kazakh. The script was right and the language was wrong, which is a base-language failure, not a variant one. The script mechanism correctly reports `untested` and says why, rather than claiming the variant failed. Plausible on its face: Kazakh's Latin alphabet is a recent official transition with little text behind it, and the nearest Latin-script Turkic neighbours are what a model reaches for.

Note also that `sr-Latn` is `proven` on the variant axis while its *tier* is `unverified`, because the back-translator could not be qualified for it. The two axes are independent and it is useful to see them disagree.

## Conclusions

1. **The marker method works.** Clean separation (1.00 vs 0.00) on identical contexts, from a designator alone. That is the result the whole of S6 rests on.
2. **It measures variant marking, not dialectal competence**, and the gap is visible in the data: the Australian arm wrote *ambos*, *old mate*, *cuppa* and *barbie*, none of which are in the marker list. The score under-counts, which is safe in the direction that matters — it cannot manufacture a variant that is not there.
3. **Elicitation contexts are the hard part, not the markers.** Every defect found here was in a context or in matching, none in the marker concept. The grammar axis has markers and no context that reaches them, which makes it currently dead weight.
4. **Two of the three instrument defects are now impossible to reintroduce**, because they are validated at load time: a marker on both sides, and a context naming its own markers. The third (inflection) is a matching rule with tests.

**Limits:** one model, two variants of one language, 28 generations. English is the pivot language, which makes it the easiest possible case for the back-translator and an unusually well-resourced case for the model. Nothing here shows the method works for `ar-EG` vs `ar-MA`, which is where it would actually be load-bearing. The marker lists are drafted, **not** human-reviewed.

## Impact

- `probe/markers.py` and `probe/variant.py`: marker schema, comparative scoring, the void rule, and the four `variant_evidence` states.
- Three validators now enforce at load time what was previously a convention: no marker on both sides, no marker named in its own elicitation context, and `not-distinguishable` must carry its reason.
- Inflection matching, with the shipped lists reduced to base forms so one word cannot score twice.
- `designator.candidates(qualify_script=...)`, set for marked script variants — `kk-Latn` is now asked for as "Kazakh (Latin script)".
- The deterministic-negative path counts attempted-and-wrong items as attempts, so `reliability` stops reading as refusal.
- A variant tested and failed is **withheld from the mergeable support artifact** even when its base language is Strong: the file promises Australian English for `en-AU`, and docs/01 forbids inheriting "supported" through a failed variant test.
- `llmlc markers` reports coverage: **534 variant tags, 2 with marker sets, 1 declared not-distinguishable, 531 untested.** The gap is now a number.
