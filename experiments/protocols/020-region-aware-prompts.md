# 020 — Region in the designator, and a system/user split

| | |
|---|---|
| **Date** | 2026-11-03 |
| **Status** | hypotheses recorded; run pending |
| **Triggered by** | Running `sr-RS-Cyrl` and `sr-ME-Cyrl` through the demo stand returned identical verdicts, because both produced the identical prompt. `region_name` was a parameter in `designator.py` that no caller had ever passed. |
| **Artifacts** | method 3.0.0; `probe/designator.py`, `probe/steps.py`, `client/openai_compat.py` |

## Hypothesis

**Recorded before the run.** Three claims, each falsifiable, and the third is the one I expect to be wrong.

**H1 — Naming the region, with an instruction to use it, changes the output.** Serbian as written in Belgrade and in Podgorica differ in spelling and vocabulary (ekavian against ijekavian). If the designator names the region *and* the system message tells the model to use that variety's grammar, spelling and vocabulary, the generated text for `sr-RS-Cyrl` and `sr-ME-Cyrl` will differ measurably — by chrF++ between the two outputs for the same scenario, against a baseline of two runs of the *same* tag, which differ only by sampling.

**H2 — Splitting the prompt into a system and a user message does not change the verdict.** It is an infrastructure change: the stable half becomes cacheable, and the model is given a task rather than a text to continue. Adequacy and eligibility should be statistically indistinguishable from 2.0.0 on the same languages.

**H3 — Naming the region will not reproduce protocol 010's failure.** 010 found that a bare `name (Country)` designator pulls a model toward that country's dominant language — Swiss German became Standard German. The claim here is that the pull came from naming a country with no instruction attached, and that casting the model as *a speaker of this specific variety* removes it.

**I expect H3 to be the one that breaks**, and `gsw-CH` is where it will break first. 010 saw it once in 84 calls, which is why that protocol called itself a screening test.

## What was tested

Not "are region-aware prompts better". Three separate questions:

1. Does the output actually differ between two regional variants of one language?
2. Does the system/user split move the verdict on languages where region is irrelevant?
3. Does naming the region reintroduce the wrong-language failure 010 found?

## Setup

| | |
|---|---|
| Models | at least three engines from the four-engine programme, so a result is not one vendor's quirk |
| Parameters | `temperature: 0.0`, `max_tokens: 400`, `reasoning_effort: "none"` — unchanged, because protocol 002 |
| Method versions | 2.0.0 (one message, no region) against 3.0.0 (two messages, region named) |
| Sample | **H1/H3:** regional pairs — `sr-RS-Cyrl`/`sr-ME-Cyrl`, `ar-EG`/`ar-MA`, `gsw-CH`/`gsw-FR`, `pt-BR`/`pt-PT`, `zh-CN`/`zh-TW`. **H2:** 30 languages with no regional variant in the list, drawn from the 199 with controls |

## Method

1. **H1.** For each regional pair, run both tags on the same five specifications under 3.0.0. Score chrF++ between the two outputs per scenario. The null is two runs of the *same* tag under 3.0.0 — that is the sampling floor, and the pair has to beat it.
2. **H2.** Run the 30 no-region languages under 2.0.0 and 3.0.0. Compare `s_content` and `s_lang` per language, paired. A difference in mean adequacy of more than 0.05, or any tier flip in more than 10% of languages, falsifies H2.
3. **H3.** Over every regional pair plus the `gsw` cases, count gate verdicts of `wrong_language` and `relative_substitution` under each method version. Any increase under 3.0.0 falsifies H3.

**Read the raw text before believing any of these numbers.** A chrF++ difference between two regional outputs could be two paraphrases of the same register rather than a dialect difference, and only reading them tells the two apart. Protocol 018's first table had Swahili at 79.8 in the "did not write Swahili" bucket.

## Known limits, stated in advance

- **This measures instruction-following as much as dialect competence.** The system message asks for the regional variety explicitly. A pass means the model *can comply when told* — not that it would mark the variant unprompted, which is what the marker mechanism measures and what doc 01 keeps out of the prompt on purpose. These are different claims and the result must not be reported as the second.
- chrF++ between two generations is not a dialect metric. It will register any lexical difference, including sampling noise, which is why the same-tag baseline exists.
- No native-speaker review. For Serbian, ekavian against ijekavian is checkable mechanically (`-е-` against `-ије-` in a closed word list); for Arabic it is not, and that pair's result is weaker evidence.

## Consequence already known, independent of the result

**Naming the region is inert in a scan as the code stands.** The equivalence class is `iso639_3|script`, so `srp|Cyrl` holds `sr`, `sr-BA`, `sr-ME`, `sr-RS` and `sr-XK`; a scan probes the class once — through bare `sr`, which has no region — and the other four inherit. The region reaches the prompt only when a tag is probed directly, which is what the demo stand does and what a scan does not.

Closing that means splitting equivalence classes by region, and the cost is measurable rather than arguable: on the 602-locale list, 81 classes hold more than one tag and **239 tags currently inherit instead of being probed**. Splitting by region turns those into probes — roughly 2,150 extra calls per engine on top of about 3,270, a 65% increase per scan.

That is a decision about budget, not about method, and it is recorded here so the result of this protocol is not read as settling it.

## Results

Not yet run. **One observation, recorded after the hypotheses above and before any measurement**, because it is what the implementation was smoke-tested with and it would be dishonest to leave it out of the record:

`deepseek-v4-pro`, one scenario, under 3.0.0:

| tag | designator | output |
|---|---|---|
| `sr-rs-cyrl` | Serbian (Serbia, Cyrillic script) | Жена је закаснила на јутарњи аутобус. Ишла је **пе**шице на посао по киши. **Када** је стигла… |
| `sr-me-cyrl` | Serbian (Montenegro, Cyrillic script) | Жена је закаснила на јутарњи аутобус. **Пје**шачила је на посао по киши. **Кад** је стигла… |

The divergence falls on the ekavian/ijekavian alternation — `пешице` against `пјешачила` — which is the standard marker separating the two varieties, and not somewhere arbitrary.

**This is n = 1, one scenario, one model, no control for sampling.** Two runs of the *same* tag would also differ, and nothing here establishes by how much; that baseline is the whole point of H1's method and has not been run. It is a reason to run the protocol, not a result from it. The failure mode to guard against is exactly the one 018 fell into: a number that points the right way, believed before the raw text beside it was read.

Nothing has been run for H2 or H3.

## Conclusions

Not yet run.
