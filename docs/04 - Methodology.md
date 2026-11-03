# Methodology

How llm-language-checker decides that a model can or cannot write a language, what each number means, and — at equal length — what none of it means.

This is the reference page. `docs/01` holds the original design discussion and the reasoning behind choices that were made before anything was built; `docs/03` holds the architecture and the implementation log; `experiments/protocols/` holds the nineteen experiments that settled the open questions. This page is what you need to read a result and to reproduce one.

**Method version 2.0.0.** Every stored result carries it, because the scale changed at 2.0.0 and rows either side of that line are not on the same scale.

---

## 1. The question

A vendor's language list is a marketing artifact. "Supports 100+ languages" has no definition attached: no threshold, no test, no evidence, and usually no list. For the long tail — the several thousand languages with a written form and no commercial market — nothing is published at all.

The question this tool answers is narrower and falsifiable: **given a locale tag, will this model produce usable text in that language, and how do we know?**

That it needs measuring at all was established before the tool was built. Asked directly which languages they support, models fabricate: presented with ten invented language names, one model returned confident support tags for nine or ten of them (`docs/02`, protocol 001). Self-report is not evidence. Neither is a vendor list, which is self-report with a logo on it.

## 2. What is measured, and what is not

**Measured:** whether the model, asked to write original prose in a named language, produces text that *is* that language, in the right script, carrying the meaning it was asked to carry.

**Not measured,** and these genuinely dissociate from the thing that is:

- chat quality or instruction-following *in* the target language — the prompt is always in the pivot language
- cultural appropriateness, register, politeness systems, terminology for any domain
- translation quality. The model is never asked to translate; it is asked to compose
- reading comprehension in the target language
- anything about the model's behaviour at longer lengths than three sentences

A result is evidence about one narrow competence, collected cheaply enough to cover two hundred languages. It is not a language-proficiency certificate and not a benchmark score.

## 3. The pipeline

Per language, in order. Costs are per *class*, not per tag — `de`, `de-AT` and `de-CH` are one experiment whose outcome the variants inherit (§5).

```
  spec (pivot)  ──▶  generate in target  ──▶  deterministic gate  ──┬─▶ Unusable, free
                      (designator sweep)      (local, no model)     │
                                                                    ▼
                                              back-translate to pivot
                                              (qualified reader only)
                                                        │
                                                        ▼
                                                 blind fact judge
                                                   (in pivot)
                                                        │
                                                        ▼
                                      eligibility filter + adequacy score + tier
```

### 3.1 Content-controlled generation

The model is given a **semantic specification** in the pivot language — a three-clause everyday scenario plus a checklist of five facts — and asked to write three sentences in the target language describing it. It chooses every word.

```
A woman misses her morning bus. She walks to work in the rain.
When she arrives, the office is closed.
```

This sits deliberately between the two obvious designs. *Translate this sentence* rewards copying and punishes legitimate paraphrase, and it measures translation rather than composition. *Write something in Tatar* lets the model emit a memorised passage, which proves it has seen the language and not that it can use it. A specification fixes the content — so the output is gradeable — while leaving the wording free.

Five specs ship in `data/specs/specs.json`. They are deliberately mundane and non-encyclopedic: a memorised Wikipedia opening cannot satisfy "an old man bought fish and the price had doubled."

The prompt also supplies the refusal channel: *If you cannot write X, reply with exactly CANNOT*. This matters — see §4.

### 3.2 Designator selection

An LLM has no language-code interface. Whatever identifier you pass is just tokens in a prompt, and nothing parses it. So the designator is not a fact to look up but **a prompt parameter to optimise**, and a negative verdict must mean *"nothing under our best designator"*, never *"nothing under one arbitrary string"*.

Five candidate kinds are enumerated per language and tried against the gate, cheapest signal first:

| | candidate | example for `cv` |
|---|---|---|
| A | English name, qualified by script and/or region where they disambiguate | `Chuvash (Cyrillic script)` |
| B | endonym | `Чӑвашла` |
| C | the tag itself | `cv` |
| D | ISO 639-3 code with script | `chv (Cyrillic)` |
| E | the consuming system's incumbent string | whatever the TMS already calls it |

Duplicate strings collapse but keep every candidate kind that proposed them, so a collision never hides the fact that a candidate was tested.

Script qualification is not cosmetic. The original rule was "name the script unless it is Latin", which is right for most languages and exactly wrong for the ones that matter: Kazakh's *marked* script is Latin, so `kk-Latn` was being asked for as plain "Kazakh", answered — correctly — in Cyrillic, and recorded as a failure to produce Latin Kazakh. It was the right answer to the question actually asked.

Naming the country does not help and was dropped (protocol 010): it produced no gain and produced the single wrong-language output in that run.

### 3.3 The deterministic gate

Before any paid call, every generated text goes through a **local, model-free filter**. It returns one of:

| verdict | meaning |
|---|---|
| `pass` | proceed to back-translation |
| `refused` | the model declined (`CANNOT`, or a recognised refusal shape) |
| `copy` | the output is the prompt, or the scenario, echoed |
| `wrong_script` | the characters are not the requested writing system |
| `wrong_language` | GlotLID identifies a different language with confidence |
| `relative_substitution` | the output is the nearest high-resource relative — Indonesian for Acehnese, Hindi for Bhojpuri |
| `degenerate` | repetition past a threshold |
| `memorised` | recognised boilerplate |
| `too_short` | not enough text to judge |
| `low_confidence` | GlotLID would not commit |

Three of these — `memorised`, `too_short`, `low_confidence` — **void the item rather than convicting it.** A voided item leaves the eligibility denominator instead of sitting in it as a failure, because a language-ID call too weak to commit is too weak to count against the model. The gate module held that position in a comment while the arithmetic did the opposite; protocol 018 moved the arithmetic to match.

**This job is never given to a language model.** Protocol 016 handed a capable model the same texts, told it explicitly to check the writing system, and named the expected script: it found **0 of 15** mismatches that the deterministic check found **15 of 15**. That result is the single strongest argument in this repository for keeping eligibility local and mechanical, and it is why eligibility decides *membership* and then stops rather than contributing to a grade.

The gate resolves most negatives before a judge is ever called, which is the entire economics of a wide scan. In the four-engine programme it alone accounted for 125 of the 796 verdicts, and in the wider Catmint scan for 318 of 616.

**The gate's language check needs GlotLID**, a 1.6 GB model that cannot be committed. Without it the gate keeps its script check and silently loses its language check — the half that answers the question the tool exists for. `llmlc bootstrap --check` and the UI readiness banner exist so that this is stated rather than discovered.

### 3.4 Back-translation, and qualifying the reader

Text that clears the gate is back-translated into the pivot language by a **fixed, independent back-translator** drawn from a panel outside the scan set.

An unqualified back-translator does not fail safely. Protocol 005 caught a model handed known Chuvash and asked to render it in English returning *"A man is walking. He is wearing a white shirt."* — fluent, confident, and unrelated to the input. A model that cannot read a language does not refuse; it invents. Fed into the judge, that fabrication moved a verdict two tiers.

So **every back-translator is certified per language before it is trusted.** It is given parallel text in that language whose English meaning is already known, and its output is scored with chrF++ against the known reference; the threshold is 30, measured against a fabricated-versus-faithful spread of 10.5 against 81.9 (protocol 006). chrF++ was chosen over a judge call because it is free, deterministic, and good enough for a pass/fail certification even though protocol 016 later showed it is *not* good enough as a quality gradient.

Control texts come from FLORES-200 (~200 languages) plus three hand-seeded (`cv`, `de`, `ru`). A control may answer for a script-compatible spelling of the same language and only that: ISO 15924's `Kore` is Hangul plus Han, so Hangul control text certifies a reader for both `ko` and `ko-Hang`. It may not stand in for a different script — Cyrillic Serbian text says nothing about a reader's Latin Serbian.

**Where no control exists, the reader cannot be qualified, and the result is `unverified`** with the reason named. `no-control` is never a pass. This is the ceiling on the whole method; §6 gives its size.

The panel is `gemini-gemini-3-6-flash, deepseek-deepseek-v4-flash`, in that order, and the order is measured rather than alphabetical: `route()` takes the first member that qualifies, and gemini-3-6-flash is the stronger reader at the hard end (`ug` 59.3 against 40.3, `am` 62.8 against 48.5). A member is dropped when the engine under test is in its **family**, not merely when it is the same model id — a sibling shares tokenizer, training data and failure modes, and is the reader most likely to decode a broken output charitably.

### 3.5 Judging

A **blind judge** receives the pivot-language back-translation and the pivot-language fact checklist, and marks which facts survived. It is never shown the target-language text, the language name, or the original output. The score is the share of facts recovered.

Grading therefore happens entirely in the pivot language, which is what makes breadth affordable: **the judge never needs to know the target language.** That this is sound was measured rather than assumed — protocol 013 compared judging a back-translation against judging the original across nine languages: 8 of 9 identical, mean difference 0.022, no hallucinated contradictions, and the single disagreement was a translation artefact rather than a judging error.

The pivot cannot be graded against itself, so **the pivot language is measured through a different pivot**: `en` falls through to `de`, then `fr`, then `es`. The fallback rides in the back-translator id (`remote:model@de`) so a pivot-measured row is never silently compared with the others.

### 3.6 The adaptive ladder

Never run a fixed number of items.

| rung | what it does | cost |
|---|---|---|
| 1 | designator selection, scored by the gate alone — if every candidate fails every item, stop | generation calls only |
| 2 | judge what survived. A clear result stops here | back-translation + judge |
| 3 | borderline only: more items to tighten the interval | more of everything |

Rung 1 is three items; rung 3 extends to six. A typical resolved language costs around nine model calls; the full 199-language programme cost between 2,083 and 2,396 calls per engine.

### 3.7 Scoring

Three parts, and the separation between them is the main result of protocols 016–018.

**Eligibility** — `s_lang`, the share of judgeable items in the requested language and script, against one threshold, `0.50`. One threshold and not three: `s_lang` moves in steps of 1/n, so telling 0.95 from 0.90 apart needs n ≥ 20 items per language, six to seven times the current cost and the wrong trade for a tool whose value is breadth. 0.50 reads as *"the model produced the requested language more often than not"*, and protocol 018 measured it as the most economical cut that still catches every wrong-script item: it leaves the eligible set 1% contaminated while rejecting 74 of 378 items, where 0.95 rejects 139 to catch exactly the same 23.

Failing eligibility means `Unusable`, full stop. Nothing else about the language is measured or reported as a grade.

**Adequacy** — `s_content`, mean fact recall over the items that cleared the filter. **This is the measurement.** It is published as a continuous number on every row, and it is the best ordering signal in the study: ρ 0.69 against chrF++ by language, against 0.52 for the gate.

Each result carries a 90% percentile-bootstrap interval over its per-item scores, seeded for determinism. A result whose interval spans the tier cut is flagged `borderline` rather than rounded.

**Tier** — a lossy routing convenience *derived* from the number, never replacing it.

| tier | condition | what a TMS does with it |
|---|---|---|
| `Unusable` | failed eligibility | do not offer |
| `Assisted` | eligible, `s_content < 0.95` | MT-assist only, mandatory human pass |
| `Proficient` | eligible, `s_content ≥ 0.95` | light review |

Three values because five were built, measured, and found not to exist: `Basic` was never assigned in 40 results, `Usable` ranked *below* `None` across 98 calibration languages, and the five-tier function ordered languages **worse** (ρ 0.436) than one of its own inputs (ρ 0.664) — it destroyed about a third of the ordering information in its own inputs. The three-tier replacement costs 0.04 of Spearman against the number it comes from (0.647 against 0.686), which is the price of giving a router something to route on.

The cut sits at 0.95 because protocol 016 established that fact recall is an **adequacy floor rather than a quality gradient** — above some threshold it is close to binary — so the one cut a floor can carry belongs at its top edge. Cuts at 0.50, 0.70, 0.85 and 0.95 were measured against mean chrF++ across 98 languages; 0.95 was the only one that ordered the three tiers monotonically.

None of the three names was reused from the five-tier scale, deliberately: `Strong` and `None` would have survived a rename, but reusing a label whose meaning has changed lets an old row be read as if it were comparable. A method-1.x tier string now fails to parse, which is the correct behaviour.

## 4. Availability: a second axis, not part of the tier

**Tier is capability. Availability is willingness.** They are reported separately and refusals are excluded from `s_lang` entirely.

| band | reliability |
|---|---|
| `reliable` | ≥ 0.90 |
| `intermittent` | ≥ 0.60 |
| `unreliable` | < 0.60 |
| `refused` | attempted, answered nothing |

Collapsing the two axes was considered and rejected (protocol 011) for a reason the data then confirmed emphatically: in the four-engine programme, **deepseek-v4-pro refused nothing across 199 languages while gpt-4o answered `CANNOT` 200 times**. On a single scale that would have been reported as "gpt-4o cannot write these languages", which the evidence does not support — it is a policy difference, and a user can route around a policy difference in ways they cannot route around an inability.

The caveat rides on the workflow sentence a planner reads, not on the tier. `ug` reported "light review" at reliability 0.33: true about the quality of what came back, and quiet about how rarely it came back at all. The sentence now says *"light review — needs a fallback engine (2 refusals of 3)"*; the tier still says `Proficient`, because that is what was measured.

## 5. Variants and dialects

A tag like `de-AT` inherits `de`'s tier, which says nothing about whether the model marks *that variant*. **Inheriting a tier is not inheriting a claim**, so each variant tag carries its own `variant_evidence`:

| mechanism | applies to | how |
|---|---|---|
| `script` | marked script variants (`sr-Latn`, `kk-Latn`) | the probe's own script check — free |
| `markers` | country-only variants (`en-AU`) | a closed shibboleth set, scored against the sibling variant's |
| `not-distinguishable` | variants that genuinely do not differ in everyday register (`ru-BY`) | an authored decision, with its reason |
| `untested` | everything else | a tracked gap, not a claim |

Marker scoring is comparative: under "Australian English" the Australian set hits and the British set misses, and an item where neither appears is **void**, because that means the prompt failed rather than the model. Markers are never named in the prompt — that would measure instruction-following — and the loader rejects any file that names its own markers in its elicitation contexts. Because marker scoring is string matching, a wrong marker produces a plausible number with nothing in the output to flag it, which is why the guard lives in the loader (protocol 012).

**This measures variant *marking*, which is a proxy for dialectal competence and not the thing itself.** See §8 for how little of it is actually proven.

## 6. Coverage: why 199 languages and not 9,589

```
shipped public catalogue                     9,589 tags
living languages                             8,607
living WITH a back-translator control          199   <- what can be graded
living WITHOUT a control                     8,408
```

**199 is not a choice; it is the control ceiling.** Grading requires a certified reader, certification requires parallel text whose meaning is already known, and that text exists for about two hundred languages. Beyond that set nobody can be qualified, so the honest output is `unverified`.

But **the deterministic gate needs no control at all.** A model that answers in Indonesian when asked for Acehnese, or refuses outright, is convicted locally and for free at full catalogue breadth. The shape of the method is: *inability can be proven without a reader; ability cannot.*

## 7. Reproducing a result

Every result stores the whole configuration that produced it, which is what makes this possible.

```bash
git clone https://github.com/a-fedosenko/llm-language-checker
cd llm-language-checker
cp .env.example .env            # your OpenAI-compatible endpoint and key
docker compose up -d
llmlc bootstrap                 # GlotLID + FLORES controls; neither can be committed
llmlc bootstrap --check         # confirm the instrument is complete before trusting a scan
llmlc scan --engine deepseek-deepseek-v4-pro --tag cv
```

A finished row looks like this (`cv`, from job 12):

```
tag           cv                              tier        Proficient
designator    Chuvash (Cyrillic script)       evidence    fact-recall
s_lang        1.0                             s_content   1.0   ci [1.0, 1.0]
reliability   1.0   refusals 0                rungs_run   2
calls         generation 3, backtranslation 3, judge 3
backtranslator  remote:gemini-gemini-3-6-flash
  qualification  qualified, score 1.0, kind "facts"
judge         openai-gpt-4o-mini              pivot       en
method_version  2.0.0
```

Read it as: under the designator *Chuvash (Cyrillic script)*, three generations were produced, all three were Chuvash in Cyrillic, all three were read back by a reader certified for Chuvash, and every specified fact survived the round trip.

To reproduce it exactly you need the same engine, the same back-translator, the same judge and the same method version — see §9 — and you need to accept that the generation step is not deterministic. Bootstrap intervals are seeded and reproducible; model output is not.

## 8. Limitations

Not a footnote. These are the terms on which every number above should be read.

**Small samples.** Three items per language, six for borderline cases. With five facts per item, the adequacy score moves in steps of 1/15. Intervals are published for exactly this reason, and **186 of the 653 graded rows in the four-engine programme — 28% — are flagged `borderline`** — their interval spans the tier cut and the tier should not be read as a flat statement.

**The `Assisted` band is wide and may be two things.** `Assisted` means "eligible but under 0.95", which currently spans fact recall from 0.00 to 0.93. Five languages in the programme scored adequacy of exactly **0.00** — fluent text in the right language carrying none of the requested meaning — and are routed identically to a language scoring 0.90. The routing sentence ("mandatory human pass") is defensible for both, but the tier is doing almost no work at the bottom of that band. Whether the honest scale is three tiers or two is an open question and the next experiment due.

**A swapped reader moves 13% of tiers.** The same engine measured through two qualified back-translators disagreed on tier for 13% of 136 languages, with a mean content delta of **0.000** — unbiased on average, noisy per language. A single tier for a single language is a noisier statement than the cross-engine aggregates are.

**chrF++ is a qualification metric, not a quality metric.** It is good enough to separate fabrication (10.5) from faithful reading (81.9), which is all certification needs. Protocol 016 showed that in the mid range it is simply wrong: 90% of the cases where it disagreed with fact recall were adequate translations that chrF++ scored badly.

**Fact recall saturates.** 84% of items score 1.0, so above the floor the measure has little resolution. Harder checklists were tried and changed nothing (protocol 015) — though that intervention was recorded in advance as too weak to conclude from.

**`unverified` is 8,408 of 8,607 living languages.** For the overwhelming majority of the catalogue, the tool can prove inability and cannot prove ability.

**Dialects are the least proven claim.** Marker sets exist for **2 of 534 variant tags**, both English — which is also the pivot and the easiest possible case — and both marked `reviewed: false`. The mechanism is tested; the mechanism is not tested *where it would be load-bearing*, which is `ar-EG` against `ar-MA`.

**Twenty-two scripts, twenty-seven tags, cannot be verified by any means** — Tengwar, Klingon, Indus, Mayan and eighteen others. The gate abstains rather than convicting, which is the correct behaviour and is untested, because there is no output to test it against.

**Known labelling errors.** `tl` is convicted for answering in Filipino — its standardised register, under a separate ISO code the accept-list does not reach. `mag` answering in Bhojpuri is labelled `wrong_language` where `relative_substitution` is the truth. Both are conservative in the direction of understating a model.

**Three sentences is the whole sample.** Nothing here speaks to a model's behaviour at document length.

**Vendor endpoints cannot be pinned.** The back-translator is a hosted model that can change under us without notice and can be retired. A published dataset whose instrument no longer exists cannot be re-graded. A local back-translator was designed and not built; the argument for finishing it is reproducibility, not cost.

## 9. Comparability

**Results are comparable only within the same back-translator, judge, pivot and method version.** This is enforced as part of the row's uniqueness constraint rather than left as advice, and it is not a formality — §8's 13% figure is what violating it costs.

Re-running an engine through a different reader therefore *adds* rows rather than replacing them, and the UI shows both. One case is exempt: a **deterministic negative has no instrument**, so it stores `NO_INSTRUMENT` (`"(not needed)"`) and is comparable against every back-translator rather than none.

The practical consequence for the four-engine programme is that three of the four engines share `gemini-3-6-flash` as a reader and are directly comparable; `gemini-3-8-flash` is read by `deepseek-v4-flash` because its own family is excluded from its panel. That is the weaker reader, which biases *against* gemini — a qualified-but-weaker reader loses facts and understates recall. The safe direction, and stated on every affected row.

## 10. Operating conventions

These are rules the project follows, each written down after it cost something:

1. **Every experiment gets a protocol, with the hypothesis recorded before the run.** Invalidated results are kept with `Status: invalidated`, never deleted. This has paid for itself repeatedly: 002 withdrew a conclusion from 001, 016 overturned 014's headline, 018 withdrew a correlation from 017, and 019 found its own trigger overstated tenfold.
2. **Reasoning is off for every measurement call.** Vendor defaults differ, and that confound already invalidated one conclusion (protocol 002).
3. **Before claiming a finding, read the raw evidence.** Nearly every real bug this project found came from looking at output rather than from tests.
4. **An analysis harness calls the production function; it never re-implements it.** A calibration script called the gate without its accept-list, convicted every macrolanguage of writing the wrong language, and a protocol drew a conclusion from 68 wrong verdicts before anyone noticed. The drift arrives looking like a finding.
5. **When the instrument is missing, say so — never quietly answer worse.**

## 11. Attribution

- **FLORES-200** © Meta AI, CC BY-SA 4.0 — <https://github.com/facebookresearch/flores>. Share-alike attaches to derived text, which is why controls are built locally rather than committed.
- **GlotLID** — language identification, CPU-only, fetched by `llmlc bootstrap`.
- **ISO 639-3** code tables and macrolanguage mapping © SIL International, used under the ISO 639-3 terms of use.
- **SIL langtags** © SIL International — <https://ldml.api.sil.org/langtags.json>
