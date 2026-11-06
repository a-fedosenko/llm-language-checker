# 021 — Attestation: measuring dialect command without a marker corpus

| | |
|---|---|
| **Date** | 2026-11-05 |
| **Status** | hypotheses recorded; run pending |
| **Triggered by** | Marker sets exist for **7 of 534** variant tags, and the owner's decision that the remaining 527 will never be authored: each one needs somebody who reads the language, and that throughput does not exist. The instrument is sound (protocol 012 proved it) and cannot be scaled, which makes it the wrong instrument. |
| **Artifacts** | S12.5. Planned: `probe/attest.py`, `probe/variant.py`, a capability-record table, `api/bench.py`. `markers/` is retained as fixtures, not deleted — see *Consequences known in advance*. |

## Hypothesis

Recorded before any attestation call is made.

The method replaces a pre-authored marker corpus with evidence the models produce and we verify. Five claims, each falsifiable.

**H1 — A blind attestor identifies the variety.** Given generated text with no label, no expected answer and no sight of the producer's identity, a competent attestor names the correct variety materially above chance. Measured on `sr` against `sr-me-cyrl`, where protocol 012 already recorded `proven` at rate 1.00 through the marker instrument, so the answer is known independently.

**H2 — A contrast pair is separable exactly when the dialect is marked.** Asked for the same content under two sibling designators, a model that genuinely marks the variant produces a pair a blind attestor can label; a model that does not produces a pair it cannot. The claim is the biconditional, not either half: separability must track marking in both directions, or the probe is measuring something else.

**H3 — Conversion diff measures control, with no judge at all.** Given macrolanguage text and asked to render it in the variant, a model with productive command produces a diff concentrated on the variant's own alternations; a model without produces an empty or cosmetic diff. If this holds, the cheapest probe in the battery needs no attestor, no control text and no panel — which is what makes breadth affordable.

**H4 — The three role capabilities dissociate.** Generation, discrimination and comprehension are separate competences, and some model in the panel is qualified in one and not another on the same dialect. If H4 fails — if the three always move together — the capability record collapses to one category and gets substantially cheaper.

**H5 — The Russian set produces no distinction, and that is the point.** `ru-ru`, `ru-by`, `ru-kz`, `ru-md` and `ru-ua` do not differ in everyday written register. Real differences exist, but they are narrow and lexical and nothing in this battery reaches them. The method must therefore return `no-evidence` across the Russian set. **This is the false-positive control, and it is the most important measurement in the protocol**: an attestor asked "is this Belarusian Russian?" is being handed a presupposition, and the failure mode we are guarding against is a model obligingly inventing markers to justify a yes. If the battery finds distinctions here, it manufactures evidence, and no positive result elsewhere in the protocol can be trusted. `markers/not-distinguishable.json` already carries `ru-BY` (the same locale in canonical spelling) as a declared non-difference, so there is a recorded human decision to measure against.

**The one I expect to break is H1, and not for the reason it looks like.** The risk is not that attestors cannot read these languages — these are five of the best-resourced families there are. It is that a three-sentence generation frequently contains nothing to identify. Protocol 012 measured a **25% void rate** on exactly this problem, all of it from one context that failed to force a choice, and an honest blind attestor handed neutral prose should answer "generic" rather than guess. If H1 fails this way the remedy is item length and elicitation design, not the method — but it must be diagnosed correctly, because "the attestor could not tell" and "the model did not mark it" are the two readings and only the contrast arm separates them.

## What was tested

Not "is attestation better than markers". Five separate questions, in the order above: can a blind judge identify a variety; does separability track marking; does conversion diff work without a judge; do the three roles come apart; and does the battery stay silent where there is nothing to find.

## Setup

| | |
|---|---|
| Producer | `deepseek-v4-pro` first. The other three engines follow, so the same text is eventually produced and attested by every pairing |
| Attestor panel | the remaining measured engines — `gemini-3-8-flash`, `openai-gpt-4o`, `groq-qwen3-8-27b` — minus the producer's whole family, per the S8 panel guard. No model attests its own output |
| Parameters | `temperature: 0.0`, `max_tokens: 400`, `reasoning_effort: "none"` with per-model fallback — unchanged, because protocol 002 |
| Pivot | `en`, except the English family, which uses **`ru`** by the owner's decision. See the limits below: this puts English results on a different instrument from every stored `en` row |
| Libraries / data | GlotLID v3 for the gate; `markers/serbian.json` and `markers/english.json` as known-answer fixtures only, never as the instrument |

**Sample.** Five families, chosen to put controls at both ends of the method rather than only in the middle. The scheme is **`catmint`**, the 602-tag TMS locale list, which is now the operating scheme for every scan. Its dialects are named explicitly and its script subtag appears last and only where it discriminates — `sr-me-cyrl`, but `en-gb` and never `en-Latn-GB`.

That convention is what makes the contrast probe possible. In the public catalogue the unqualified tag *is* a variety — `pt` resolves to `pt-Latn-BR` — so there is no neutral arm and every contrast has to be base-against-marked. Here `pt` is the umbrella and `pt-br` is a variety beside it, carrying its own tag. Every tag below was verified present in `schemes/catmint.json`.

| family | neutral arm | varieties measured against it | role in the protocol |
|---|---|---|---|
| Serbian | `sr` | `sr-rs-cyrl`, `sr-rs-latn`, `sr-me-cyrl`, `sr-me-latn`, `sr-ba-cyrl` | **known positive** — 012 recorded `proven` 1.00 on the Cyrillic yat pair |
| English | `en` | `en-us`, `en-gb`, `en-au` | **known positive** — 012 recorded `proven` 1.00 on GB and AU; pivot `ru` |
| Portuguese | `pt` | `pt-br`, `pt-pt` | **floor** — if this does not separate, the method is broken |
| Spanish | `es` | `es-es`, `es-mx`, `es-ar` | **floor**, and the first three-way contrast |
| Russian | `ru` | `ru-ru`, `ru-by`, `ru-kz`, `ru-md`, `ru-ua` | **null control** — must return `no-evidence` |

The umbrella tag is identified by the scheme's `inclusive` flag, which is the locale list's own claim and **not** ISO 639-3 scope. The two were conflated in one field until this stage: `kk` is an umbrella over `kk-kz` and ISO still calls it an individual language, and writing the first claim into `scope` made it a macrolanguage with no members. They are now separate fields, because the dialect probes read the first and the macrolanguage logic reads the second.

`sr-me-latn` and `sr-rs-latn` are the Latin-script Serbian cases the gate blocked until Part 1 (see below). They are in the sample deliberately.

**The option set is the varieties under test, not everything the family holds.** Catmint carries 22 Spanish tags and 11 English ones, and a 22-way blind identification is a different and much harder task than the one being measured: chance falls to 4.5%, and an attestor that tells Mexican from Peninsular Spanish perfectly well can still miss by answering Uruguay. The varieties listed in the table above are the option set for their family. Two tags naming one variety in two scripts — `sr-me-cyrl` and `sr-me-latn` — contribute one option, since they are Montenegro written twice; and the umbrella tag contributes none, because it is the arm being contrasted *against* and `generic` already means "none of these".

## Method

Five probes, each independently meaningful, each writing its raw exchange to the corpus. The gate runs before any attestor sees any text: eligibility is deterministic and is never handed to a model (protocol 016, 15/15 against 0/15).

1. **P1 — blind identification.** The attestor receives text and the language family, and names the variety. It does not receive the expected tag, the producer's identity, or any other attestor's output. **This is enforced by the function signature, not by prompt wording** — the expected answer is not a parameter, so it cannot leak into the prompt.
2. **P2 — contrast pair.** The producer writes the same scenario under two sibling designators. A blind attestor is given the unlabelled pair and asked to assign the labels.

   A forced two-way assignment floors at 0.5 by guessing, which would make the null control unreachable — a model that can see no difference would still score half the Russian pairs "correct". So the attestor may answer **`indistinguishable`**, and the prompt says in as many words that two texts being different texts does not make them different varieties. That escape is what lets H5 come back clean rather than at chance.

   The pair is presented in an order salted by the texts themselves. Without it, an attestor that answers the options in the order they were listed scores 100% on every pair by habit, and we would read a formatting tic as dialect knowledge. The caller knows the order and scores against it; the attestor never learns it.
3. **P3 — conversion.** Macrolanguage text in, variant text out, one producer call. The diff is the measurement. No attestor.

   Measured with a token-level diff rather than chrF++. chrF++ yields a similarity number and nothing a person can read; what a reviewer needs is *which words changed*, because that is how a real dialect conversion is told from a paraphrase — and protocol 020, which proposed chrF++ for this, concedes in its own text that the metric does not distinguish the two.

   **There is no lower threshold, and the reason is worth recording.** A dialect conversion is supposed to be a small edit: ekavian to ijekavian moves a handful of morphemes and leaves the sentence standing. Any floor expressed as a share of the text therefore convicts exactly the models that did the job correctly — one correct substitution in a 50-word paragraph is 2% of it and is a conversion. Punctuation and case are discarded by tokenisation, so any surviving edit is a real word substitution and one is enough.

   The **ceiling** is the live risk, and it is the one a floor would have missed: a model that rewrites the whole passage has produced something that is no longer the same text, and its diff is sentence rewrites rather than the variety's own alternations. `paraphrased` is kept distinct from `converted` because they are opposite failures and a reader has to know which happened.
4. **P4 — self-consistency.** P3 repeated independently, scored as Jaccard agreement between the two runs' edit sets. Systematic command produces repeatable transformations; bluffing produces noise. No attestor. Protocol 020 already recorded that `temperature: 0.0` is not determinism on a hosted endpoint — six identical calls gave two distinct outputs — so the same-tag floor is measured, not assumed.

   **Runs that converted nothing are excluded before scoring, and this is what decides whether the probe is worth having.** Two empty edit sets agree perfectly and mean nothing: a model that changed nothing twice is consistent in a way that says nothing about dialect command, and scoring it 1.0 would make the most ignorant possible answer the highest-scoring one — `systematic` would then be true of every model that cannot do the task at all. Jaccard rather than containment for the same reason in the other direction: a run that makes every edit the other made *plus five more* is improvising, not agreeing.
5. **P5 — marker grounding.** Not a call of its own: `identify` and `separate` ground their own results and this only tallies what they found, because a fabricated marker is evidence about the *attestor* and belongs beside that attestor's verdict. Where an attestor cites markers, two mechanical checks: the cited markers must actually occur in the text, and markers cited for one variant must not be equally present in the sibling's. This reuses `probe/markers.py`'s stem matching. **Markers are not retired here — they are demoted from ground truth to evidence under verification**, which is the shape convention 15 asks for: marker scoring is string matching, so a fabricated marker yields a plausible number with nothing to flag it.

**Attestor controls, and why no corpus is needed.** No attestor verdict is trusted on faith. Each attestor is checked per family by controls **manufactured rather than collected** — constructed from the texts already in hand, needing no speaker of the language, and correct by construction rather than by authority. That is the whole reason this escapes the problem that killed the marker approach.

The design drafted three controls whose answers we "already know" — macrolanguage text offered as a variant, a sibling's text offered as a decoy, and a genuine item. **Two of those turned out not to be manufacturable.** Knowing that a given text is genuinely Montenegrin, or that a decoy should be rejected, is knowledge about the dialect, which is exactly what we do not have for an arbitrary variety; building a control on it would smuggle the retired marker corpus back in under another name. Only controls whose answer follows from *construction* survive:

| control | construction | correct answer | catches |
|---|---|---|---|
| **identity** | one text shown as both halves of a pair | `indistinguishable`, necessarily — the two texts *are* one text | an attestor manufacturing differences |
| **order** | one real pair shown twice, in both orders | answers that correspond | an attestor answering by position rather than by text |

Both run on every attestor for every family, three calls, and failing either is disqualifying on its own — each tests a different way of being wrong, so a majority rule over two controls is one control. An attestor that fails is **disqualified for that dialect** and its verdicts are discarded rather than counted.

**What the controls cannot catch, stated plainly.** An attestor that answers `indistinguishable` to everything passes both. Detecting over-merging needs a pair known to be distinguishable, and knowing that independently is precisely what we lack for an arbitrary dialect. It is available for Serbian and English, where protocol 012 measured `proven` at 1.00 — which is why those two families are in the sample as **calibration rather than as subjects**. For Portuguese, Spanish and Russian, over-merging is indistinguishable from a true negative, and a negative there must be reported as *"no evidence of a difference"* and never as *"no difference"*. This is the sharpest limit on H5: the Russian null coming back clean is consistent with the method working and also with every attestor merging everything, and only the Serbian and English arms can tell those apart.

This replaces a model's self-reported "I do not know this dialect" as the load-bearing mechanism. That self-report is still recorded — volunteered ignorance is honest and worth having — but it is not depended on, because models rarely produce it.

**Panel decision rule.** Only controls-passing members vote. Among them, agreement is the signal and disagreement is stored as disagreement, never averaged into a number that hides it. One qualified member is a single-judge verdict, stamped lower-confidence, never silently promoted to a panel result. **Judge competence is per dialect, not per model**: a strong engine may be a weak attestor for one variety, and the record must be able to say so rather than letting its silence pass as evidence.

**The capability record.** Every attestation produces a record keyed by *(model, tag, script, role, method version)*, role being `generation` | `discrimination` | `comprehension`, carrying verdict, confidence, the probes that produced it, an evidence pointer, and `measured_at`. It mirrors the existing `Qualification` table, which is already a per-(instrument, language) competence cache keyed by method version. Scanning the first engine therefore measures the other three as a byproduct, and later scans get cheaper.

Its governing invariant, which is what keeps it from becoming the thing it replaced: **the record routes, it does not vouch.** It decides who is asked first; controls in the live run decide whether the answer is believed, and they run every time regardless of what the record says. A stale record then costs wasted routing, never a wrong verdict — a cache, not an authority. Without that rule an attestor wrongly recorded as competent keeps being asked and keeps being believed, and the error becomes self-confirming.

That invariant is **structural rather than documented**: `CapabilityRecord` exposes `put`, `get`, `known` and `rows`, and no method that answers "is this attestor trustworthy". A test pins the public surface, because the moment such a method existed somebody would call it. Routing reorders and never removes — an attestor recorded as *failing* is still tried, since a record is a cache of a past measurement and models change under a fixed id. Three states are kept apart and ordered differently: qualified before, failed before, never tried.

Negatives are recorded alongside positives. A record holding only successes would read as a list of models that work while silently dropping the evidence that the others do not.

**Verdict ladder:** `no-evidence` / `recognition-only` / `production` / `full-command` / `indeterminate`. It sits **beside** `VariantEvidence` rather than extending it — the four marker states describe how a variant was established where a marker set exists, and the seven authored ones remain valid; merging the two would make `proven` mean different things depending on which instrument ran.

Aggregation is a transparent function of the per-probe outcomes: no weights, no tuned coefficients, no number that cannot be traced to an observation. The order of the checks is the whole of the logic:

1. **No competent attestor → `indeterminate`**, checked first, because every check below it would otherwise read an absent measurement as a negative. For a rare dialect this is the common case and the easiest error to make.
2. **An attestor that fabricated its evidence → `indeterminate`.** A verdict propped up by invented quotations was not read off the text, so the panel measured nothing however confident it sounded.
3. **Blind identification confirmed → `production`**, or `full-command` with conversion on demand *and* the same conversion twice. Writing a variety when free and rewriting on request are different competences, and only the second earns the top of the ladder.
4. **Separation without identification → `recognition-only`.**
5. **Otherwise `no-evidence`** — which, outside the calibration families, is the weak negative described above.

`indeterminate` **is a result, reported as such** and never folded into a negative: it is in `NOT_A_CLAIM`, counted separately wherever a figure is quoted, for the same reason the project already splits `Unusable` from `unverified`. Confidence is `low` for a single qualified attestor however clean its answer, and `low` for a split panel, because the disagreement is the finding.

Records are persisted in a `capability` table (Alembic `c3f8a1e5d904`), unique on *(model, tag, role, method_version, script)*. Script is in the key because one variety written in two scripts is two measurements — `sr-me-cyrl` is identified cleanly where `sr-me-latn` cannot be told from Bosnian at all. The persistent record is required to expose the same surface as the in-memory one, pinned by a test, so the "routes but never vouches" rule survives persistence rather than surviving only as a comment.

## Known limits, stated in advance

- **These are five of the best-resourced language families in the world, and that is the point and the limit.** The method is being calibrated where the answer is checkable, not demonstrated where it would be load-bearing. Nothing here shows it works for `ar-EG` against `ar-MA`, which remains the open case the handoff names.
- **Only the Serbian and English families have an independent answer** (protocol 012's marker verdicts). Portuguese and Spanish are "should obviously separate" on general knowledge, which is weaker evidence than it feels like, and Russian's null is a human judgement recorded in `markers/not-distinguishable.json` rather than a measurement.
- **English on a Russian pivot is not comparable with any stored `en` result.** Convention 4 is not a formality here: the instrument id becomes `remote:<model>@ru` where every existing English row carries `@de` from protocol 013's fallback chain. The choice is defensible — a typologically distant pivot leaks fewer English dialect markers than German does — but it buys that at the cost of comparability, and the English rows from this protocol must not be read against the 2026-09-29 programme.
- **P2 and P3 measure compliance as much as competence.** The designator names the variety and the system message asks for it. A pass means the model *can mark it when told*, not that it would unprompted — which is a different claim, and the one the marker instrument was built to keep out of the prompt. The results must not be reported as the second.
- **Three sentences may be too short to carry an identifiable marker.** This is H1's expected failure mode and it is an instrument limit, not a model limit.
- **No native-speaker review.** Serbian and Russian fixtures were drafted by someone who does not read them, which is why `markers/` validates against worked examples at load time, and why every set still carries `reviewed: false`.
- **Read the raw text before believing any number here.** An attestor agreeing that two texts differ is not evidence they differ dialectally. Protocol 018's first table had Swahili at chrF++ 79.8 in the "did not write Swahili" bucket, and it was visible only to someone who opened the list.

## Consequences known in advance, independent of the result

**Protocol 020 is partly superseded, and only partly.** Its H1 (does naming the region separate `sr` from `sr-ME`) and H3 (does naming a region pull the model to the wrong language or script) are answered better here than by chrF++ between two generations — 020's own text already concedes H1 wants a better metric, and blind identification is that metric. **Its H2 is not superseded**: whether method 3.0.0's system/user split moves the verdict on the 30 no-region languages is a question about the generation prompt, unrelated to dialect attestation, and it still gates the programme re-run. 020 is therefore marked partly-superseded with H2 open, not closed.

**The equivalence-class decision does not have to be settled first.** P3 and P4 are per-tag and need no class change, so this protocol can run against the data model as it stands. If base capability really does differ by region, H4's records will show it, and the ~65% scan cost is then justified by evidence rather than argued in advance. That decision is deferred on purpose, not forgotten.

**The gate blocked Latin-script Serbian; it now abstains. Built in Part 1, before any run.** GlotLID reads ijekavian Serbian in Latin as Bosnian or Croatian — correctly, since the three written standards nearly coincide in that script — so the gate returned `relative_substitution` and scoring never ran. A blind attestor does not have that limitation, but the gate fires first and would have discarded the text before any attestor saw it.

`gate.check` now takes `abstain_lang`: codes the *instrument* cannot tell from the target, as opposed to codes that would be a wrong answer. Seeing one is `LOW_CONFIDENCE` — a void item — rather than a conviction, because the finding is about LID and not about the model. It is checked **before** the confidence floor, since the instrument is not unsure here: it is confidently sure, and confidently unable to tell these apart, so a high-confidence `bos_Latn` would otherwise sail past into a conviction.

The set is authored (`INDISTINGUISHABLE` in `probe/ladder.py`), keyed by script, and deliberately narrower than `accept_lang`: an abstention voids an item and never passes it. We are not saying Croatian satisfies a request for Serbian; we are saying we cannot tell, so we decline to answer. Keying by script is what keeps `srp_Cyrl` working — Croatian is not written in Cyrillic, so the four do not collapse there, and voiding the one Serbian case that already works end to end would have been a regression. Verified: `sr-rs-latn` and `sr-me-latn` abstain against `bos`/`hrv`/`cnr`/`hbs`, while `sr-me-cyrl`, `pt-br` and `en-gb` abstain against nothing.

Same shape as the carried-forward `mag`-in-Bhojpuri item, which this mechanism could also settle. `sr-me-latn` and `sr-rs-latn` are in the sample to exercise it.

**A defect found while switching to this scheme, and fixed before any run.** `candidates_for` passed `region_name` unconditionally, and a locale list's unqualified tag has no region subtag while still inheriting a region *name* from the reference catalogue's likely-subtag resolution. So `pt` was asked for as **"Portuguese (Brazil)"** — the identical designator `pt-br` gets — and likewise `en` as `en-us`, `es` as `es-es`, `ru` as `ru-ru`, `sr` as `sr-rs-cyrl`. The neutral arm was being asked to be the dialect it is supposed to be contrasted against, so every contrast in this protocol would have been null by construction and the null would have looked like a finding.

This is protocol 020's trigger in mirror image: there two tags produced one prompt because the region was never passed, here because it was passed where the tag carried none. The region is now named only when the tag has a region subtag, and a test pins both halves — the umbrella must not name a region, and the variety must still name its own, since dropping the region everywhere would be method 3.0.0 undone.

**`markers/` is retained, not deleted.** The three files stop being the instrument and become fixtures: `serbian.json` and `english.json` are the known-answer calibration for H1 and H2, and `not-distinguishable.json` is a human decision about register, which a measurement does not invalidate. The owner's reason for keeping them is additionally that they are interesting artifacts in their own right and the approach may be revisited.

**The Bench.** The `Demo` tab, `api/demo.py` and their prose were renamed to **Bench** before this protocol was written, because "demo" implied a showcase and the thing is an instrument driven by hand. The attestation probes must be reachable there one at a time, including the routing — which attestors were chosen, why, forcible to a full panel, and a record markable stale. `attest_steps()` is a generator drained by the batch runner, exactly as `ladder_steps()` is, so that bench and scan cannot disagree about what the method does (convention 11).

## Results

Not yet run.

## Conclusions

Not yet run.
