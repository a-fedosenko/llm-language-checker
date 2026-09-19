# 013 — Can the judge grade a back-translation that is not in the facts' language?

| | |
|---|---|
| **Date** | 2026-09-19 |
| **Status** | valid |
| **Triggered by** | Measuring the pivot language. `en` reported `None`/`unverified` because back-translating English into English grades nothing; the fix is to measure it through a different pivot, which makes the judge read German while the fact checklist stays English |
| **Artifacts** | `src/llmlc/probe/pivot.py`, `src/llmlc/probe/judge.py`, raw responses in `experiments/results/cross_lingual_judge.jsonl` |

## Hypothesis

The judge's job is deliberately narrow: read a text, decide for each of a handful of facts whether it is present, missing or contradicted. Nothing about that requires the text and the facts to be in the same language, and the prompt already says to judge meaning rather than phrasing.

1. **Cross-lingual judging agrees with same-language judging.** The same generation, back-translated into English and into German and graded against the same English facts, will produce the same recall. Predicted mean absolute difference **< 0.10**, and no systematic direction.
2. **If it disagrees, it will be German scoring *lower*** — one extra translation step between the fact and the text, plus a judge that reads English facts more comfortably than German prose. A German arm scoring *higher* would suggest the judge is guessing rather than reading.
3. **The failure mode to watch is `contradicted`, not `missing`.** A judge under cross-lingual strain should drift toward "missing" (it did not find the fact) rather than "contradicted" (it found the opposite), because the latter requires actually understanding the text. An increase in `contradicted` would mean the judge is hallucinating disagreement.

What would kill the approach: a mean difference above ~0.2, or any increase in `contradicted` verdicts. Either would mean `en` measured through German is not comparable to anything else, and the honest answer would revert to reporting the pivot language as unmeasurable rather than measuring it badly.

## What was tested

One set of generations, graded twice. Each text was back-translated into English **and** into German by the same model, and both back-translations were judged against the **same English fact checklist**. The only variable is the pivot.

## Setup

| | |
|---|---|
| Models | generation `openai-gpt-4o`, back-translation `deepseek-deepseek-v4-pro`, judge `openai-gpt-4o-mini` |
| Parameters | temperature 0, `reasoning_effort: none`, 3 sentences per item, 5 facts per spec |
| Sample | 3 languages (`af`, `ru`, `cv`) × 3 content specs = 9 generations, 18 back-translations, 18 judgements |

Languages chosen to span the range: Afrikaans and Russian are well handled, Chuvash is known from protocol 005 to be where gpt-4o's output falls apart. Agreement at the bottom of the range matters as much as at the top — a judge that agrees only on easy cases has shown nothing.

## Method

Generate once per (language, spec). Back-translate that same text twice, into English and into German. Judge each back-translation against the spec's English facts. Compare recall per item.

## Results

| | |
|---|---|
| pairs | 9 |
| identical | **8 of 9** |
| mean absolute difference | **0.022** |
| max absolute difference | 0.200 |
| mean signed difference (German − English) | **+0.022** |
| `contradicted` verdicts | **0 of 45 in either arm** |

Hypothesis 1 is confirmed: 0.022 against a predicted ceiling of 0.10.

Hypothesis 3 is confirmed by absence — not one `contradicted` verdict in either arm. The judge under cross-lingual load did not start inventing disagreement.

**Hypothesis 2 was wrong in direction, and the single disagreement is worth reading in full.** It was `ru` / `market-fish-price`, where German scored *higher* (1.0 against 0.8). The fact was *"He walked home."*

> **English back-translation:** "...He buys less than he had planned and **goes home**." → judged `missing`
> **German back-translation:** "...Er kauft weniger, als er geplant hatte, und **geht nach Hause**." → judged `present`

Both judgements are defensible on the text they were given. English "goes home" genuinely does not state *walking*; German *gehen* carries the on-foot sense, and the Russian original meant walking. **The disagreement is in the back-translation, not in the judge** — one arm lost a detail in translation that the other kept, and the judge correctly reported what each text said. If anything, the German arm was the more faithful of the two.

The three Chuvash items scored 0.0 in both arms: gpt-4o's Chuvash did not carry the facts, and both pivots agreed on that too.

## Conclusions

1. **Cross-lingual judging is sound at this sample size.** 8 of 9 identical, no systematic direction, no hallucinated contradictions. The judge's task — does this text state this fact — does not appear to depend on the text and the fact sharing a language.
2. **The one disagreement is a translation artefact, not a judging one**, which is the better of the two failure modes: it is visible in the corpus, attributable to a specific word, and affects any pivot choice rather than this mechanism.
3. **The pivot language is now measurable.** `en` re-measured through German comes out Strong / `fact-recall` / content 1.00, where it previously reported `None` / `unverified`.

**Limits:** 9 pairs, one back-translator, one judge, one fallback pivot, and three languages that are not a random sample. This validates the mechanism enough to measure English with it; it does not license switching the whole catalogue to a non-English pivot. Note also that one arm of this comparison is the *instrument under test* — English back-translations graded by an English-reading judge are the method's own baseline, not independent ground truth.

## Impact

- `probe/pivot.py`: a language that is itself the pivot is measured through the first fallback that is not also the target (`de`, then `fr`, then `es`), so choosing an unusual pivot moves the blind spot along rather than leaving one.
- `bt/qualify.pivot_control()`: the control for English is the aligned FLORES pair read backwards — (English text → German reference) is the same data as (German text → English reference), so measuring the pivot needs no new corpus and no hand-written text.
- The judge prompt now states that the text may be in a different language from the facts.
- **The pivot rides in the back-translator id** (`remote:model@de`). One change, three effects: qualification is cached per pivot instead of shared across them; two results for one language measured through different pivots occupy separate rows under the existing uniqueness constraint rather than overwriting each other; and the pivot is visible wherever the instrument is shown. English stays unsuffixed so nothing written before this is orphaned.
- Three degenerate rows — `en`, `en-AU`, `en-GB` measured with `pivot=en` — were deleted. They were measurements the tool now refuses to make.
