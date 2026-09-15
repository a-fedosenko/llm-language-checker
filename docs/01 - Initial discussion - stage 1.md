# 01 — Initial discussion (Stage 1: assumption check, Stage 2: methodology)

Date: 2026-09-13 … 2026-09-15
Status: Stages 1 and 2 discussed. Stage 3 (architecture + costs) not started.

---

## Very short summary — current understanding

We are building an **empirical capability oracle for language coverage of LLMs**: given a model (by name, or by an OpenAI-compatible endpoint + API key), answer "which of our ~600 locales can this model actually produce usable text in?" — measured, dated, reproducible, and exposed over an API.

Three query depths: (1) list languages for a model, (2) yes/no for one language, (3) graded quality with user-supplied texts. One shared measurement pipeline underneath; results cached in a DB so common questions become cache hits.

**Not commercial.** Two real drivers: (a) our TMS/CAT system needs this data per locale, (b) portfolio project. Others (LSPs, academics) may find it useful; that is a side effect, not a goal.

**Key methodological decisions reached:**

- The primitive is **content-controlled generation**, not translation. We specify *what to say* as a semantic spec in a pivot language; the model chooses every word. This avoids both the copy/paraphrase problems of translation and the memorization escape hatch of free generation.
- Grading is by **fact recall in the pivot language**, not fuzzy string match. Consequence: **the judge model never needs to know the target language** — it does English reading comprehension against a checklist. This eliminates the "we need expert LLMs covering 600 languages" bootstrap problem for the grader.
- The one component that still must read the target language is the **back-translator**. It is fixed, independent of the model under test, tiered (local MADLAD-400 → pinned frontier LLM → `unverified`), and **qualified per language against aligned text before it is trusted**. A failure of our instrument is never reported as a failure of the model. Results are only comparable within the same back-translator, so it is part of the cache key and of every API response.
- The **judge** is a pinned LLM working blind in the pivot language, three-valued per fact (`present` / `missing` / `contradicted`), never the model under test, with injected positive and negative controls. A local NLI model runs as a free cross-check and as the reproducibility anchor.
- **Batch is the only job mode.** A job takes a list of languages; a full scan is that list with 600 entries, a single-language check is that list with one. No special cases.
- For an LLM there is **no language-code list** — the per-language value is a **prompt designator**, and choosing the best one is itself part of the experiment. A `None` verdict always means "None under our best designator."
- The scan is driven by the **family graph**: base-language capability is tested once per `(lll, script)` class (423, not 602), variants are tested only for variant-marking, and a failed class prunes its whole subtree.
- Output is **two artifacts**: a minimal file in the master's exact shape (mergeable by per-key, per-engine upsert) and a separate full-evidence report. Adding languages later is just a batch job over the new keys.
- **Language identification is done locally** by GlotLID/OpenLID, not by an LLM. Cheaper, faster, more accurate, covers 1600+ languages.
- Most negatives die in a **free deterministic gate** (refusal, copy, wrong script, wrong language, nearest-relative confusion, degeneration, memorized boilerplate) before any judge call.
- Support is **not binary**: graded tiers with a bootstrap confidence interval and an explicit evidence class. Intervals that straddle a tier boundary are reported as `borderline`, never rounded.
- Positioning: **not a leaderboard** (one already exists, free and government-funded). The gap is bring-your-own-endpoint + a queryable API + the long tail beyond 200 languages + dialects.

---

## Stage 1 — Assumption check

### Prior art (it exists, and it is close)

- **AI Language Proficiency Monitor** — [paper](https://arxiv.org/html/2507.08538v1), [live space](https://huggingface.co/spaces/fair-forward/evals-for-every-language). Auto-updating leaderboard, up to 200 languages, composite "Language Proficiency Score" over FLORES+, MMLU variants, ARC, GSM8K, TruthfulQA. MIT-licensed, funded by BMZ/GIZ/DFKI. Most direct overlap.
- **MEXA** — [arXiv](https://arxiv.org/pdf/2410.05873). Scores multilingual capability via cross-lingual embedding alignment on parallel data. Cheap, no generation needed. Relevant to the cost problem.
- **MuBench** (61 langs), **BenchMAX**, **MEGA/MEGAVERSE** (83 langs), **P-MMEval**, **INCLUDE** (44 langs), **Eka-Eval** — academic benchmark suites. Curated list: [awesome-multilingual-llm-benchmarks](https://github.com/NaiveNeuron/awesome-multilingual-llm-benchmarks).

### What none of them do — our positioning

1. **Bring-your-own-endpoint.** All of the above evaluate a fixed roster of public models. None accepts an OpenAI-compatible base URL + key for a fine-tune, a self-hosted vLLM deployment, or a regional provider.
2. **A queryable API.** They ship dashboards and papers, not `GET /models/{id}/languages`. There is no machine-readable "can I ship this locale on this model" endpoint anywhere found.
3. **The long tail.** They stop at ~200 languages (the FLORES+ ceiling). Our ~600 macrolanguages and dialects is unique territory — and exactly where measurement is hardest.
4. **Answer latency.** They are batch research pipelines. "Answer for this one language in 90 seconds" is a different product.

**Conclusion: do not build a leaderboard.** It exists, is free, is publicly funded, and cannot be out-resourced. Build the API + BYO-endpoint checker; let accumulated public results be a free SEO/discovery surface rather than the product.

### Open human-translated datasets and licenses

| Dataset | Langs | License | Use |
|---|---|---|---|
| [FLORES+](https://huggingface.co/datasets/openlanguagedata/flores_plus) | 200+ | CC BY-SA 4.0 | **Primary.** Human, professionally translated, sentence-aligned, many-to-many. Gold references. |
| NTREX-128 | 128 | CC BY-SA 4.0 | Second reference set; guards against FLORES contamination in training data |
| [Tatoeba](https://github.com/Helsinki-NLP/Tatoeba-Challenge) | ~429 | CC BY 2.0 FR | Extends past FLORES; uneven quality (crowd), short sentences |
| OPUS / OPUS-100 | 600+ | mixed per-corpus | Long tail, but licensing is per-subcorpus and must be audited individually |
| Bible corpora (eBible etc.) | 100–1000+ | **mixed, often restrictive** | Widest coverage; many translations are not freely redistributable. Severe domain bias. |
| SIB-200 | 200 | CC BY-SA 4.0 | Topic classification, derived from FLORES — a non-translation task signal |

License notes:

- CC BY-SA bites on **redistribution of derived test sets**, not on using the data to run an evaluation. If we publish sample sentences in reports or ship a test-set download, attribution + share-alike apply.
- Bible corpora need a per-translation audit before going near the product. "It's the Bible" does not mean "it's public domain."

### Other Stage-1 findings

- Google Translate now claims 243 languages; Cloud Translation API covers ~195 via NMT. Vendor LLM claims are far vaguer — Claude is benchmarked on ~15 languages and "capable in dozens more"; Gemini claims 100+. These vendor numbers are unfalsifiable marketing, which is the gap the project exists to fill.

---

## Stage 2 — Methodology

### Critique of the original algorithm (from `Basic idea v0.md`)

**1. Round-trip translation + fuzzy match is the weakest link.** It fails in both directions:

- *False pass:* a model that cannot write Yoruba emits English-ish or transliterated slop, back-translates it trivially, and round-trips to a high fuzzy score. Round-trip rewards **self-consistency**, not correctness. A model that is consistently wrong scores well.
- *False fail:* a correct but legitimately paraphrased translation round-trips to different English wording and scores low.

**2. Do not use LLMs for language identification.** GlotLID (1600+ languages) and OpenLID (200+) run locally on CPU, cost nothing, and beat LLMs at exactly this task.

**3. Most negatives are catchable before spending a token on a judge** — via a deterministic local gate. Biggest cost lever in the design.

**4. Script ≠ language.** The dominant long-tail failure mode is *right script, wrong language* (Hindi returned for Bhojpuri, Indonesian for Minangkabau, MSA for a dialect), not gibberish. Must be tested explicitly against the nearest high-resource relative, or we will report support that does not exist.

**5. "Supports" must not be binary.** With 5–20 items per language the uncertainty is wide. A single boolean will be wrong often enough to destroy trust.

**6. Scope the claim.** Translating *into* a language, chatting *in* it, and following instructions written *in* it are three capabilities that dissociate. Headline claim = **generation adequacy in the target language**. Say so everywhere.

**7. Logprobs when available.** Many OpenAI-compatible endpoints expose `logprobs`; where they do, per-token surprisal on gold reference text is a nearly free fluency signal with no generation. Worth a capability probe at job start.

### Andrei's answers to the Stage-1 questions

1. **No paying users assumed.** Two reasons: the TMS/CAT system needs the data; and it is a portfolio pet project. Possible usefulness to LSPs/academics is incidental.
2. **The ~600 list** is the macrolanguage + dialect list from the TMS/CAT system. The existing GPT-4o estimate was produced by a script doing translate → back-translate, then manually reviewed from a general linguistic standpoint. Not precise.
3. **Budget** is reasonable but small. A company API key routes to all models available to us. Methodology alternatives explicitly open for discussion.
4. **"Expert LLM" was only an idea**, not a requirement. The actual purpose is to automate verification that the examined LLM produces real output rather than an obvious fake. Any better method is fine.
5. **No key storage.** Password-style field with a disclaimer that nothing is saved; we do not want to carry the API charges ourselves.

### Andrei's idea: prompt for free generation instead of translation

Proposal was: instead of giving English text to translate, ask the model to write a few phrases in the selected language or report that it does not know the language — and for dialects, prompt for phrases using dialect-specific lexis and grammar. The acknowledged problem was how to grade the result.

**Assessment: right instinct, one fatal flaw.**

Right, because translation-from-English conflates "can translate" with "can write," lets a model score by copying, and is useless for dialects.

Fatal flaw: **memorization**. Asked to "write a few sentences in Chuvash," a model has an easy out — the UDHR preamble, a Bible verse, a national anthem, a Wikipedia lead. Models have these memorized in hundreds of languages they cannot otherwise use. Free generation hands the model control over the content, so it steers toward its one memorized fragment. False-positive rate would be severe precisely on the long-tail languages we care about.

**The real axis is not translate vs. generate. It is:**

- **Content must be controlled by us** — otherwise it cannot be graded, and the model escapes into memorized text.
- **Form must be controlled by the model** — otherwise we are measuring translation and penalizing legitimate paraphrase.

Translation controls both (gradeable, but form-locked and copy-prone). Free generation controls neither (memorizable, ungradeable). The diagonal is **content-controlled generation**: specify *what to say* as a semantic spec in a pivot language — not a sentence to translate — and let the model choose every word.

Example prompt shape:

> "Write 3 sentences in Chuvash describing this situation: a woman misses her morning bus, walks to work in the rain, and arrives late to find the office closed. Do not translate — write naturally. If you cannot write Chuvash, reply exactly `CANNOT`."

Novel content (unmemorizable), free form (no paraphrase penalty), and gradeable because we know which facts must be recoverable.

Then grade the round-trip on **fact recall, not string similarity**: a judge reads the back-translation and answers "which of these 5 facts are present?" A checklist, not a fuzzy match. Paraphrase costs nothing; hallucinated or missing content costs everything.

**The decisive payoff:** the judge never needs to know the target language — all grading happens in the pivot. The judge only needs strong reading comprehension in English (or Russian). This eliminates the entire "we need expert LLMs covering 600 languages" premise, which was the expensive, circular, hardest-to-validate part of the original design. There is no bootstrap problem anymore.

### Andrei's idea: Gemini instead of GPT-4o as first expert LLM

Largely moot under the above — and that is good news, because using the broadest-coverage model as ground truth is the most dangerous version of the design: whatever Gemini cannot do becomes permanently invisible to us.

- **Judge role:** pivot-language comprehension only. Any competent model works. Pin the exact version. **Never let a model judge itself** (self-preference bias is well documented).
- **Gemini's actual value:** a second opinion on language identification where GlotLID has no coverage, and — more usefully — **drafting the dialect marker lists** for Probe 4, human-reviewed once. A one-off authoring task, not a per-run dependency.

### The probe battery

Not all probes run for every language — see the adaptive ladder.

**Probe 0 — Self-report (1 call, near-free).** "Can you write in X? Answer YES or NO." Unreliable in both directions: models over-claim constantly, and some refuse languages they handle fine. **Never ground truth.** Its real use is Probe 1.

**Probe 1 — Honesty calibration (fake-language control).** Ask the model to write in ~10 plausibly-named languages that do not exist, plus ~10 real languages already confirmed to fail. A model that confidently produces fluent-looking output for a nonexistent language has worthless self-reports and inflated scores everywhere.

This yields a **per-model honesty coefficient**, computed once per model, not per language. It is the direct answer to "is the output real or an obvious fake." It is also a budget lever: a model with a high honesty score lets us trust its `CANNOT` responses and skip expensive probes; a dishonest model is forced through the full ladder. The calibration pays for itself.

**Probe 2 — Deterministic gate (free, local, no API calls).**

| Check | Verdict on failure |
|---|---|
| Explicit refusal / `CANNOT` | None (self-reported) |
| Output ≈ input (copy behavior) | None |
| Wrong Unicode script block | None |
| **GlotLID** says wrong language | None |
| Assigned to nearest high-resource relative | None — *"outputs Hindi, not Bhojpuri"* |
| Degenerate repetition / n-gram loop | None |
| Matches memorization blocklist (UDHR, Bible, anthems, Wikipedia leads) | Void the item, re-roll |

Most of the 600 languages die here for zero marginal cost. One model call per item, no judge call.

**Probe 3 — Content-controlled generation + fact recall.** As described above. Score = fraction of specified facts recovered by a pivot-language judge from the model's own output, back-translated by a **fixed** translator.

Where FLORES+ exists, *additionally* score chrF++ against the gold reference. This is the **calibration study**: validate the cheap fact-recall metric against a trusted reference metric on ~200 languages, then apply it to the other ~400 with known error bars. This is the most portfolio-worthy artifact in the whole project.

#### The back-translator

Step 4 of the pipeline (target language → pivot) is the only component that must *read* the target language. Reading is a much lower bar than writing, but the choice matters, so it is pinned by policy rather than left to chance.

| Tier | Who | Coverage | Notes |
|---|---|---|---|
| **A** | Local MT model — **MADLAD-400-3B-MT** | 400+ languages | Apache-2.0, free, deterministic, reproducible. The default. |
| **B** | A pinned frontier LLM (e.g. GPT-4o or Gemini), **different vendor from the model under test** | the remainder | Costs money; used only where Tier A has no coverage, or when a user opts into it |
| **C** | Nothing can read it | — | `evidence: unverified`; report the deterministic-gate verdict only |

Note: MADLAD-400-3B-MT is a proposal, not yet verified. Its real per-language reading ability must be established by the qualification test below before any of this is relied on.

**Rule 1 — Independence.** The back-translator is never the model under test, and preferably not the same model family. Otherwise we are back to measuring self-consistency — the exact flaw in the v0 round-trip design.

**Rule 2 — Qualify the instrument before trusting it.** To qualify *any* back-translator (local or frontier) for language L, hand it aligned text in L whose pivot meaning is already known, and check that it recovers the facts. If it cannot recover facts from a professional human translation, it is broken for L: any low score it then produces for the model under test is uninterpretable, and L is marked `unverified` rather than "unsupported."

This is a **direct reading test**. It runs once per language per back-translator — one call, not a full ladder — and it guarantees that a failure of *our instrument* is never misreported as a failure of *the model*.

Corollary: qualifying a frontier LLM as a back-translator does **not** require running the full generation ladder on it first. Running the ladder would measure its *writing* and let us infer its *reading*; the inference runs in the safe direction (writing is harder than reading), but it is indirect and far more expensive than testing reading directly.

**The gap worth seeing now.** The languages where a frontier back-translator is most wanted are precisely the ones where nothing can be qualified. MADLAD covers ~400; our list is 600. For the missing ~200 there is no aligned text, so neither MADLAD nor GPT-4o can be validated there and both yield `unverified`. Aligned text beyond FLORES+ — NTREX, Tatoeba, OPUS, Bible corpora — pushes the qualifiable set outward, and that stretch is a Stage-3 work item. Where nothing aligned exists at all, the honest ceiling is the deterministic gate: *"GlotLID says this is plausibly Ainu; we cannot assess quality."* That is still a useful answer for a TMS.

**Consequence for the data model.** Results are only comparable within the same back-translator. `backtranslator` (with version) must be part of the cache key and must be surfaced in every API response, alongside `judge` and `method_version`.

**Consequence for external users.** For a custom-endpoint scan, the user picks the back-translator: the free local one (limited coverage), or a paid frontier one for which they supply a key. They pay for their own back-translation; we pay for none of it. The coverage ceiling differs between the two, and the UI must say so before the job starts.

Open engineering trade-off for Stage 3: MADLAD-400-3B wants a GPU, or int8 quantisation and patience on CPU. The smaller distilled NLLB-600M is faster but covers ~200 languages and is CC-BY-NC — acceptable for a non-commercial project, but it constrains any later reuse.

#### The judge

Primary: **a pinned LLM judge working only in the pivot language** — one call per item, all facts of that item graded together, JSON out. Roughly 1,200 calls per full model scan; negligible cost.

Five rules make it trustworthy:

1. **Blind.** The judge sees the back-translation and the fact checklist. Never the target-language text, never which model produced it, never the original prompt prose.
2. **Three-valued per fact:** `present` / `missing` / `contradicted`. Missing is incompleteness; contradicted is hallucination — worse, and weighted differently.
3. **Never the model under test.** Self-preference bias is well documented.
4. **Pinned and recorded** in every result.
5. **Validated by injected controls.** About 5% of items are controls: some where the "back-translation" is gold text (must score ~1.0), some where the facts come from a different scenario entirely (must score ~0.0). A judge that passes the negative controls is broken — and we find out in-run rather than never.

Secondary: a **local NLI model** (DeBERTa-v3-MNLI class — each fact as hypothesis, the back-translation as premise, check entailment) can do this task for free, deterministically, with no vendor. Keep the LLM judge as primary for robustness and run NLI as a cheap cross-check: disagreements flag either a bad item or a judge failure. NLI is also the reproducibility anchor — anyone can re-grade the published corpus without an API key.

**Probe 4 — Variant discrimination (dialects).** Do not ask for "Australian lexis" and grade impressionistically. Use a **closed marker set** per variant: 20–40 shibboleths where the variants diverge deterministically.

| Axis | en-AU | en-US |
|---|---|---|
| Lexis | ute, arvo, thongs, boot, petrol | pickup, afternoon, flip-flops, trunk, gas |
| Orthography | -ise, -our, tyre | -ize, -or, tire |
| Grammar/idiom | "in hospital", "different to" | "in the hospital", "different from" |

Give a content spec engineered to **force** the markers ("describe filling the car with fuel and putting bags in the back"), then score = rate of variant-appropriate choices vs. the sibling variant. Objective, cheap, and it measures what a CAT tool actually needs. Marker lists are authored once per variant pair (Gemini drafts, human reviews) and become a reusable open dataset in their own right.

Honest caveat to publish: this measures **variant-marking ability**, not full dialectal competence. It is the right proxy, and we should state that it is a proxy.

### The language scheme and the output contract

Added 2026-09-15 after reading `languages/languages.json` (602 entries) and `languages/languages_mt_support.json` (602 entries). This section supersedes anything above that assumes a flat list of 600 independent languages.

#### The scheme

Tags are close to BCP-47 but with **script moved to the end**: language, then country, then script — and script appears only when the language has more than one. `ace-ID-Arab`, not `ace-Arab-ID`. The lowercased tag is the object key and the ID in the TMS; output must follow this exactly or it will not merge.

Two fields carry the family structure:

- `inclusive: "True"` — a macrolanguage, an umbrella over a family of dialects. 74 of these.
- `link` — membership in a family. 354 entries have one. **It is polymorphic:** 63 resolve to a tag key, 291 resolve to an ISO-639-3 code that is not itself a key (`ara`, `spa`, `zho`, `eng`). The resolver must handle both.

#### Finding 1 — for an LLM, the value is a prompt designator, not a code

`languages_mt_support.json` maps each internal tag to the identifier each engine expects. These engine identifiers follow no common rule — each vendor invented its own, and they are unrelated both to each other and to our internal scheme. For the MT engines the identifier is a genuine API parameter drawn from a closed, published list: support is **definitional**, wrong codes produce errors, and the right way to populate those columns is to ingest the vendor's documentation rather than run experiments.

**For an LLM there is no tag interface at all.** There is no lookup table inside the model. Whatever string we pass is simply tokens in a prompt. So unlike every MT column, the LLM column has **no ground truth to discover — only strings that perform better or worse.** OpenAI's documentation lists languages they *benchmark*; it does not document codes the API parses, because nothing parses them.

This has a nasty property: **a bad designator does not error, it silently degrades.** That is precisely why an ad-hoc designator cannot detect its own failure.

The column reflects that. It holds five incompatible shapes:

| Shape | Count | Examples |
|---|---|---|
| `lang (Script)` | 307 | `afr (Latin)`, `ace (Arab)` |
| `lang-CC` | 85 | `sq-MK`, `gsw-CH` |
| bare `ll`/`lll` | 26 | `ace`, `ara`, `bos` |
| other | 4 | `ar-DZ (Arabic)`, `urd ` (trailing space), `zh-Hans` for `zh-mo-hans` |

The script vocabulary mixes standards too: `Latin` ×181 vs `Latn` ×11, `Arabic` ×31 vs `Arab` ×5, `Cyrillic` ×19 vs `Cyrl` ×6, plus `Perso-Arabic`, `Hanzi`, `Ge'ez`.

That is not sloppiness, it is a structural fact: the value is a **string somebody puts in a prompt**, authored ad hoc. So the deliverable per language is two things, not one — a **verdict**, and **the designator that best elicits the language**.

**Provenance of the existing column** (per Andrei, 2026-09-15) — two very different sources, currently indistinguishable in the file:

| Source | Approx. count | What it is actually evidence of |
|---|---|---|
| Vendor documentation | ~100 | that OpenAI *benchmarks* the language — says nothing about which string works |
| Asked the model itself | ~322 | the model's claim about its own interface, kept if the answer "looked reasonable" |

The second group is unvalidated in both directions: nobody checked that the tag elicits the language, and nobody checked that the model can write the language at all. It is also the same failure mode as the fake-language control, one step removed — *"what tag would you understand for Acehnese (Indonesia) with Arabic script?"* is exactly the question a model answers fluently and confabulates freely, whether or not it can produce a word of Acehnese.

**Testable prediction:** the original method, run on an invented language, would have returned a plausible-looking tag.

**CONFIRMED — 2026-09-15, across three models.** See `02 - Experiment - invented language control.md`. GPT-4o produced a confident tag for **10/10 nonexistent languages** under the original phrasing, and did so by silently substituting a real neighbour (Nurdagh → Turkish, Lombric → French, Zhalgari → Kazakh). Adding an explicit escape hatch fixed that completely (10/10 refused) but then over-refused 3 of 10 real languages. Most importantly, of 7 real languages that produced a confident tag, **only 2 would actually write the language** — tag-presence predicts writing ability at ~29%. The ~322 self-reported entries therefore need re-derivation, and Probe 1 must run both phrasings to measure over-claim and over-refusal as separate per-model coefficients.

Repeated with reasoning disabled on `gemini-3-8-flash` (7/10 fabricated) and `deepseek-v4-pro` (10/10), so this is not a GPT-4o quirk. Two further results: stronger models fabricate *more* convincingly — precise invented ISO codes with invented language families attached — and self-report fails in **both** directions within one model (DeepSeek refused an Aromanian tag, then wrote Aromanian on request). Two harness rules follow: **reasoning must be disabled** for every measurement call, and **"OpenAI-compatible" is not uniform** — `reasoning_effort` is honoured by some routes and rejected outright by others, so the pipeline needs a per-model capability probe at job start.

**Designator selection becomes part of the method.** Rung 1 of the ladder tries candidates and keeps the winner:

| | Candidate | Example |
|---|---|---|
| A | English name + country | `Swiss German (Switzerland)` |
| B | Endonym | `Schwiizerdütsch` |
| C | Our tag | `gsw-CH` |
| D | ISO-639-3 + script name | `gsw (Latin)` |
| E | **The incumbent** — whatever the current column holds | `gsw-CH` |

The deterministic gate scores these for free — no judge calls — so the overhead is small and lands only on rung 1. The winning *family* of designator is largely model-independent, so the rule is established once and alternates are re-tested only where rung 1 fails.

Candidate E is deliberate: carrying the incumbent as a competitor — never as ground truth — yields a direct measurement, *"selection beat the incumbent designator in N of 422 languages."* That is a clean headline result and it validates the method against data Andrei has already reviewed by hand.

**Hard rule: a `None` verdict means "None under our best designator," never "None under one arbitrary string."** The existing GPT-4o estimate used a single ad-hoc designator per language, so some of its negatives are plausibly designator failures rather than capability failures.

#### Finding 2 — the family graph drives the scan

602 tags collapse to **423 distinct `(lll, script)` classes**: 363 singletons, then `spa/Latn` 22 tags, `ara/Arab` 19, `eng/Latn` 11, `por/Latn` 8, `rus/Cyrl` 7.

Base-language capability is a property of the class, not the tag — `af`, `af-NA` and `af-ZA` are one experiment. Therefore:

- **Probe 3 runs 423 times, not 602.**
- **Probe 4 runs only for the 179 non-singleton members**, and only where the class passed. For those tags the base language is already established; the only open question is whether the model marks the variant.
- A class that fails prunes every tag under it at zero extra cost.
- The 74 `inclusive: "True"` tags are natural roots: test the macrolanguage first, prune the subtree on failure.

This is strictly better than a flat ladder — fewer calls, and it cleanly separates "can write Arabic" from "marks Iraqi Arabic specifically," which is exactly the distinction the 19 `ar-*` rows need.

#### Finding 3 — data notes (normalize defensively, do not demand fixes)

- `cat_latn` and `tlh` appear in `languages.json` with no support entry; `null` and `tlh-piqd` appear in support with no language entry.
- `inclusive` is the string `"True"`, not a boolean.
- `"urd "` carries a trailing space; `zh-mo-hans → "zh-Hans"` drops the region while its sibling `zh-mo-hant → "zh-MO-Hant"` keeps it.
- 97 entries are `{}` — the established convention for "no engine supports this."

The pipeline normalizes on ingest and tolerates the master as it stands.

#### The output contract

Two artifacts, deliberately separate.

**1. Mergeable, minimal — the master's exact shape:**

```json
{ "gsw-ch": { "mt.openai-gpt-4o": "Swiss German (Switzerland)" } }
```

Absent engine key = not supported, matching the existing `{}` convention.

**2. Full evidence, never merged** — `results/<engine>/<method_version>.json`, carrying per key: tier, `S_lang`, `S_content`, `S_variant`, confidence interval, evidence class, designators tried and the winner, back-translator, judge, `tested_at`, and references to raw outputs.

Plus, on every entry, **`provenance`**: `documented` | `self-reported` | `measured`. The existing column mixes the first two with no way to tell them apart; anything this pipeline produces is `measured`. The three warrant very different trust and must never again be conflated.

**Identical shape, different semantics.** `mt.google: "ab"` is a required API parameter — omit or mistype it and the call fails. `mt.openai-gpt-4o: "Swiss German (Switzerland)"` is an empirically-best prompt string with a score behind it and no error mode. Keeping the file shape identical is right for TMS compatibility, but the side file must carry the score and provenance so the two are never mistaken for one another.

**Merge semantics:**

- **Per-key, per-engine upsert.** Never a whole-file replace — a partial run must not be able to wipe other engines' data.
- **"Key absent from run output" never means "delete."** Removal is explicit only.
- **Conflict rule:** higher `method_version` wins; on a tie, newer `tested_at`.

**Incremental growth** then falls straight out of batch-only mode. New languages added to the scheme → run a batch over the new keys only → upsert. And a **staleness view** — keys whose stored `method_version` is behind the current one — covers the other direction: the method improved, re-run only what is out of date.

#### Consequence: do not run this algorithm on the MT engines

Google, DeepL, NLLB, ModernMT and Microsoft publish their supported-language lists. Ingest them. This project's experiment exists only where no list exists — that is, LLMs. Clean boundary, and it keeps the cost model honest. (Validating whether MT engines are actually *good* at the languages they claim is a possible later use of the same pipeline, but it is out of scope.)

### Job modes

**Batch is the only mode.** A job takes a list of target languages plus a model reference (name, or endpoint + key) and a back-translator choice. Everything else is a degenerate case of that:

| Scenario | Language list |
|---|---|
| Full scan (stage-3 style) | all ~600 |
| Batch check | the subset the user cares about |
| Single-language check (scenario 2) | one |
| Quality check with user texts (scenario 3) | one, plus supplied reference material |
| Incremental update after the scheme grows | only the newly added keys |
| Re-run after a method change | only the keys whose `method_version` is stale |

One endpoint, one queue, one progress model, one result shape. Batch check was missing from `Basic idea v0.md` and is the case real users will want most — "can this model handle our 40 shipping locales" rather than all 600.

### Scoring and expression of uncertainty

Per language, three sub-scores over n items:

- `S_lang` — LID + script pass rate
- `S_content` — mean fact recall
- `S_variant` — marker rate (variants only)

| Tier | Condition | Meaning for the TMS |
|---|---|---|
| **None** | refusal, or `S_lang < 0.2` | do not offer |
| **Token** | `S_lang ≥ 0.5`, `S_content < 0.3` | recognizes it, cannot use it |
| **Basic** | `S_lang ≥ 0.8`, `S_content` 0.3–0.5 | MT-assist only, mandatory human pass |
| **Usable** | `S_lang ≥ 0.9`, `S_content` 0.5–0.7 | post-editing workflow |
| **Strong** | `S_lang ≥ 0.95`, `S_content > 0.7` | light review |

Every result carries, and the API returns:

- `evidence`: `gold-reference` (FLORES+ chrF++) | `fact-recall` (calibrated proxy) | `deterministic-negative` (died in Probe 2) | `unverified`
- `ci`: bootstrap 90% interval over items. **If the interval straddles a tier boundary, report `borderline(Basic..Usable)` — never round.** Refusing to collapse uncertainty is the honest move and is cheap to implement.
- `method_version`, `tested_at`, `model_fingerprint`

The tier→workflow mapping (rightmost column) is what makes this useful internally rather than merely interesting. It should be baked into the schema. **Open question: confirm these match how the TMS actually thinks about locale readiness.**

### Adaptive ladder and budget

Never run a fixed 20 items:

The ladder walks the **423 `(lll, script)` classes**, not the 602 tags.

1. **Rung 1 — 3 items × 2–4 candidate designators**, graded by the deterministic gate only (no judge calls). Picks the winning designator; all candidates failing → `None` for the class, and every tag in it is pruned. The long tail ends here.
2. **Rung 2 — +3 items** with fact-recall grading, using the winning designator. Clearly Strong or clearly Token → stop at 6.
3. **Rung 3 — borderline classes only, +14 items** to tighten the CI. Perhaps 60–100 classes.
4. **Probe 4 — the 179 non-singleton tags** whose class passed: variant-marker scoring, local and free apart from generation.

Rough per-model full scan: on the order of **4,000–4,500 generation calls and ~800 judge calls**. The designator sweep adds calls on rung 1 but they are gate-only; the class collapse removes ~30% of Probe-3 work and the subtree pruning removes more. Still single-digit dollars on a mid-tier model, low tens on a frontier one, and under an hour with modest concurrency. Exact figures belong in Stage 3, gated on the MADLAD qualification result.

**Store every raw generation.** When the method moves to v2, re-grade the existing corpus for free instead of re-running every model. That corpus — 600 languages × N models × raw outputs with gradings — is the durable asset and the thing worth publishing.

### Dropped from the original design

- **The "expert LLM consensus" stage.** Replaced by GlotLID + a pivot-language judge + a fixed independent back-translator + the calibration study. No bootstrap, no circularity, far cheaper. Note this does not remove the need for a target-language-capable component altogether — it demotes it from "expert judge of quality across 600 languages" to "a reader we can swap out and validate," and makes its failures explicit (`unverified`) instead of silent.
- **English as the fixed pivot.** English by default, but a closer pivot for non-European spheres (Russian for Turkic/Caucasian, Arabic for Semitic, Hindi for Indic) reduces judge error. Cheap to configure, measurable effect.

### API key handling

Password-type input, `autocomplete="off"`, held in memory for the job's lifetime only, never written to disk or logs, dropped on completion, with a visible disclaimer. Two additions:

- **Redact keys from error traces** — the classic leak path.
- Prominently recommend a scoped or throwaway key. Costs nothing, and it is the kind of detail a portfolio reviewer notices.

---

## Notes on the other challenges from `Basic idea v0.md`

**LLM cost.** The dominant cost is the **model under test**, not the judges. Levers in order of impact: (a) the gold-reference path removes judges entirely for ~200 languages; (b) local LID + the deterministic gate remove judges for most negatives; (c) sequential/adaptive testing; (d) cache keyed on `(model fingerprint, language, test-set version)`, shared across all users — one full scan becomes everyone's cache hit.

**Hosting cost.** The architecture sketched in v0 (SPA + microservices + Kafka + Redis + docker-compose) is heavier than the workload. This is a queue with a few workers and a Postgres table. Proposed instead: one VPS, Caddy, Postgres, a single worker process with a job table. Redis only if a need is measured; Kafka not at all. Roughly €5–20/month instead of a machine that needs 8 GB to idle. **Numbers to be worked out in Stage 3.**

**Discoverability.** Organic search intent — "does Claude speak Tigrinya", "GPT-5 Quechua support" — one static page per (model, language) pair generated from the DB gives tens of thousands of long-tail pages with a real answer on each. Plus an embeddable badge for HuggingFace model cards.

---

## Dialects, macrolanguages and markers (decided 2026-09-15)

This supersedes the earlier "defer Probe 4" recommendation. Variant coverage is never blocked: the marker corpus is a **growable asset**, not a precondition. Ship with zero marker lists — every dialect inherits from its macrolanguage — then add lists over time and watch tags upgrade from inherited to proven.

### A macrolanguage tag is an addressing convention, not a linguistic entity

`kk`, `en`, `ar`, `ru` exist because many systems carry only coarse tags. Testing `kk` answers *"does this model do Kazakh at all"* — it does **not** prove anything about `kk-Cyrl` or `kk-Latn` as dialects, and a single observation of Cyrillic output is not even a stable claim about how `kk` resolves.

Three separate questions, three separate answers:

| Question | How it is answered | Result field |
|---|---|---|
| Does the model support the macrolanguage? | probe `kk` | tier |
| What does `kk` resolve to in this model? | observed, never decided | **`resolves_to`** — a reference field |
| Can the model produce `kk-Latn` when asked? | **its own probe, its own designator** | dialect tier + `variant_evidence` |

`resolves_to` is recorded as a **distribution**, not a single value — LID already runs on every generated item, so `{"kaz_Cyrl": 6, "kaz_Latn": 0}` is free and honest about variability.

Useful byproduct: `resolves_to` across all 74 macrolanguages tells you what each model *defaults to* — whether `ar` yields MSA or a dialect, `zh` yields Hans or Hant, `en` leans US or UK. Operationally valuable for the TMS (you know what you get when you send a coarse tag) and an interesting published result in its own right.

### Dialect testing logic

1. Test the macrolanguage → tier + `resolves_to` distribution.
2. Test **each dialect with its own designator** — a separate probe, always.
3. Score that probe by whichever mechanism applies:
   - **script check** (GlotLID) where the family splits by script;
   - **marker comparison** where a marker list exists;
   - **`not-distinguishable`** where the marker file explicitly says the variants do not differ in everyday register;
   - otherwise **`untested`** → inherit the macrolanguage's tier as a placeholder.
4. Record `variant_evidence`.

### `variant_evidence` — four states, not two

| State | Meaning |
|---|---|
| `proven` | markers (or script) existed, tested, passed |
| **`proven-failed`** | tested and the model did **not** mark the variant — must **not** silently inherit "supported" from the macrolanguage |
| `not-distinguishable` | explicitly flagged (e.g. `ru-BY`); inheritance is *correct*, not a fallback |
| `untested` | no markers authored yet; inheritance is a *placeholder* and a tracked coverage gap |

Separating `not-distinguishable` from `untested` is what makes remaining work countable — a finished decision must be distinguishable from an unfilled gap.

### Script-split families need no markers, but still need testing

Of 239 variant tags in non-singleton classes, **22 belong to families that split by script** (`ace`, `kaz`, `zho`, `srp`, `bos`, `pan`, `snd`, `mon`, `tzm`, `jav`, `kas`, `knc`, `min`, `mnk`, `shi`, `taq`, `vai`, `bjn`). GlotLID returns language *and* script, so these need **no authored marker list**.

They are not free of *testing*: each still gets its own probe with its own designator, because "emitted Cyrillic when asked for `kk`" is not "produces Cyrillic when asked for `kk-Cyrl`". The script check is the **scoring mechanism**, not a substitute for the test.

The remaining **217 are country-only** (`ar-*` ×19, `es-*` ×22, `af-NA`/`af-ZA`, `sq-MK`/`sq-XK`, `gsw-*`). These need markers or the `not-distinguishable` flag. The flag likely disposes of a large fraction cheaply — `af-NA` vs `af-ZA` is probably in the same category as `ru-BY`, whereas `ar-EG` vs `ar-MA` genuinely is not.

### Marker file schema

Markers are **not** accompanied by a prompt telling the model to use them. Naming the markers measures instruction-following rather than competence, and "write with Australian vocabulary" invites a word list instead of natural text. The file carries marker pairs plus **elicitation contexts** — semantic specs that make the marker unavoidable without naming it. Same primitive as Probe 3.

```json
{
  "en-AU": {
    "status": "markers",
    "sibling": "en-US",
    "markers": [
      { "axis": "lexis",       "variant": ["boot", "petrol", "ute"],
                               "sibling": ["trunk", "gas", "pickup"] },
      { "axis": "orthography", "variant": ["-ise", "-our", "tyre"],
                               "sibling": ["-ize", "-or", "tire"] },
      { "axis": "grammar",     "variant": ["in hospital", "different to"],
                               "sibling": ["in the hospital", "different from"] }
    ],
    "elicitation": [
      "Describe loading luggage into the back of a car and stopping to fill the fuel tank.",
      "Describe someone being taken to hospital after a fall, and how their treatment differed from what was expected."
    ]
  },
  "ru-BY": { "status": "not-distinguishable",
             "note": "No markers in everyday register; inherits from ru." }
}
```

Two scoring rules follow:

- **Comparative, not absolute.** Score = variant markers vs sibling markers. Writing "trunk" for `en-AU` is a miss; "boot" is a hit.
- **Void the item if neither appears.** That means the elicitation context failed, not the model. Otherwise models are punished for bad contexts, and bad contexts are never detected.

The variant may be named in the prompt — that is the designator. The markers never are.

## Deployment pivot — self-hosted only (decided 2026-09-15)

**We do not deploy.** The project is packaged as microservices that anyone runs locally or in their own cloud: clone, supply a `.env`, `docker compose up`, UI on localhost. Target is minutes from clone to a working environment.

This resolves three of the hardest open problems at once:

| Problem | Resolution |
|---|---|
| Hosting cost (Challenge 2 in v0) | None. No VPS, no domain, no GPU machine to rent. |
| API-key custody | Gone. No password field, no UI key entry, no liability. Each user supplies their own `.env`. |
| Back-translator free/paid toggle | Gone. Each user pays their own costs directly; no metering, no abuse surface. |

It also changes the positioning: the README now presents an **empirical heuristic tool**, explicitly not a linguistic authority and not a leaderboard, with its limits stated on the front page.

Consequence for scope: the queue, worker pool and multi-tenancy concerns from `Basic idea v0.md` shrink dramatically. This is a single-tenant local application, not a service.

### Hardware profiles

The stack detects hardware at startup and picks a profile; `HARDWARE_PROFILE` in `.env` can override.

| Detected | Back-translator | Coverage |
|---|---|---|
| GPU ≥ 6 GB VRAM | MADLAD-400-3B-MT, fp16 | ~400 languages |
| GPU 4–6 GB VRAM | MADLAD-400-3B-MT, int8 | ~400 languages |
| CPU only, or < 4 GB | NLLB-200-distilled-600M, or a remote API back-translator | ~200 languages, or as configured |

GlotLID runs on CPU everywhere; no GPU required for language identification.

### Reference hardware (verified 2026-09-15)

Andrei's development machine, checked directly:

- **RTX 4060 Laptop, 8 GB VRAM**, driver 596.08, compute capability 8.9 (Ada — native bf16/FP8)
- **Docker 27.5.1 with the `nvidia` container runtime already registered**; `docker run --gpus all` verified to see all 8188 MiB inside a container
- 20 CPU cores, 15 GB RAM (WSL2), 928 GB free disk
- torch not yet installed

Memory fit at 8 GB VRAM: GlotLID is CPU-only (~1.2 GB RAM); DeBERTa-v3 NLI ≈ 0.9 GB fp16; MADLAD-400-3B-MT ≈ 6 GB fp16 (marginal with activations) or ≈ 3 GB int8 (comfortable). All required components co-resident at int8 ≈ 5 GB. MADLAD-400-10B does not fit. **8 GB decides quantisation, not feasibility** — the heavy path runs on a laptop, which is what makes the self-hosted promise credible.

## Decisions taken 2026-09-15

1. **Engine namespace stays `mt.*` for both MT engines and LLMs.** An LLM can be used as an MT engine, and the TMS generates one list of available MT engines that includes them. This supersedes open question 7; no `llm.*` namespace is introduced.
2. **No dialect marker resources exist in the TMS.** Rather than defer variant testing, marker lists are made optional and incremental — see *Dialects, macrolanguages and markers* above. Coverage is never blocked by their absence. This supersedes open question 2.

## Open questions carried into Stage 3

1. Does the content-controlled-generation + fact-recall design land, or should the gold-reference translation path stay **primary** for the ~200 languages that have one? (Recommendation: run both on those 200 — that is the calibration study.)
3. **Judge model** — a preference, or design it provider-agnostic behind the OpenAI-compatible interface and pin whichever the company key routes to?
4. Confirm the **tier → workflow mapping** matches how the TMS actually reasons about locale readiness, or supply the real categories.
5. **MADLAD-400-3B-MT is unproven for us.** First concrete experiment: run the back-translator qualification test over as much of the 600-language list as has aligned text, and find out what its real coverage is. This gates the cost model in Stage 3.
6. How far can the **qualifiable set** be stretched past FLORES+ using NTREX, Tatoeba, OPUS and Bible corpora — and at what licensing cost?
8. **Which tiers earn a designator in the master file?** Presence there reads as "we will send this locale to this engine." Recommendation: `Basic` and above, with tiers carried in the side file so the TMS can route workflows accordingly. Andrei's call.
9. Should the **existing `mt.chatgpt` column be re-derived** by this pipeline rather than trusted? Its designators were authored ad hoc, so some of its negatives are plausibly designator failures. Re-running it would also be the first end-to-end validation of the method.

---

## Sources

[AI Language Proficiency Monitor](https://arxiv.org/html/2507.08538v1) · [evals-for-every-language](https://huggingface.co/spaces/fair-forward/evals-for-every-language) · [MEXA](https://arxiv.org/pdf/2410.05873) · [MuBench](https://arxiv.org/html/2506.19468) · [BenchMAX](https://arxiv.org/pdf/2502.07346) · [P-MMEval](https://arxiv.org/pdf/2411.09116) · [Eka-Eval](https://arxiv.org/pdf/2507.01853) · [awesome-multilingual-llm-benchmarks](https://github.com/NaiveNeuron/awesome-multilingual-llm-benchmarks) · [FLORES+](https://huggingface.co/datasets/openlanguagedata/flores_plus) · [NLLB-200 / FLORES-200](https://ai.meta.com/blog/nllb-200-high-quality-machine-translation/en-gb/) · [Tatoeba Challenge](https://github.com/Helsinki-NLP/Tatoeba-Challenge) · [OPUS-MT](https://arxiv.org/pdf/2212.01936) · [Bible in 100 languages](https://pmc.ncbi.nlm.nih.gov/articles/PMC4551210/) · [common-parallel-corpora](https://github.com/common-parallel-corpora/common-parallel-corpora)
