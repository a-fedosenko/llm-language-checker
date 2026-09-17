# 009 — The adaptive ladder and the designator sweep

| | |
|---|---|
| **Date** | 2026-09-17 |
| **Status** | valid |
| **Triggered by** | S3: the ladder exists to make a wide scan affordable, and the designator sweep exists because an LLM has no language-code interface ([001](001-invented-language-control.md)) |
| **Artifacts** | `src/llmlc/probe/ladder.py`, `src/llmlc/probe/scan.py`, `data/results/evidence.openai-gpt-4o.1.0.0.jsonl` |

## Hypothesis

Three, stated before the run:

1. **The ladder prunes.** Most languages resolve at rung 1 on gate checks alone, so cost per tag is well below the naive "items × 3 calls".
2. **Class collapse works.** Regional variants (`de` / `de-AT` / `de-CH`) are one experiment, so only the class representative is probed.
3. **Designator choice matters**, and candidate A (English name, qualified by script and region) is usually the winner — which is why S1 could ship with A alone.

## What was tested

An 18-tag scan spanning script families and resource levels, deliberately including three regional-variant pairs and several languages expected to fail:

`de de-AT de-CH fr af af-NA sw cv yo am ka mt ga ug ti bo dv ee`

## Setup

| | |
|---|---|
| Model under test | `openai-gpt-4o` |
| Back-translator panel | `gemini-gemini-3-8-flash`, `deepseek-deepseek-v4-pro`, routed per language |
| Judge | `openai-gpt-4o-mini` |
| Parameters | `temperature=0`, reasoning off |
| Ladder | rung 1 = 3 items gate-only across designator candidates; rung 2 = judge survivors; rung 3 = 6 more items if borderline |

## Results

**Economics:** 18 tags, 15 classes, **165 calls total** (99 generation, 33 back-translation, 33 judge) in 298 s — **9.2 calls per tag**. `ee` resolved at rung 1 alone. Three tags inherited with zero calls.

**Designator sweep — the endonym sometimes wins:**

| Language | A English name | B endonym | C raw tag | D ISO+script |
|---|---|---|---|---|
| `ti` Tigrinya | 0.33 | **0.67 — ትግርኛ** | 0.00 | 0.00 |
| `cv` Chuvash | 0.00 | **0.33 — чӑваш** | 0.00 | 0.00 |
| `ug` Uyghur | **0.67** | 0.00 | 0.00 | 0.00 |
| `bo` Tibetan | **0.33** | 0.00 | 0.00 | 0.00 |
| `dv` Dhivehi | **0.67** | 0.00 | 0.00 | 0.00 |

**Candidate C — the raw BCP-47 tag — scored 0.00 on every language tested.**

**A scoring flaw the spread exposed.** `ug` produced fluent Uyghur on two items and `CANNOT` on the third. `s_lang` came out 0.667, which put it in tier **Token**, whose published meaning is *"recognises it, cannot use it"* — a false statement about a model that had just used it twice at content 1.0. `bo` was scored **None** on the same mechanism after writing correct Tibetan once.

## Conclusions

1. **Pruning and collapse both work**, at 9.2 calls per tag against a naive ~27.
2. **The designator sweep is justified by measurement, not argument.** The endonym beat the English name on 2 of 5 long-tail languages, and one of those (`cv`) was the difference between measuring something and measuring nothing at all.
3. **The raw tag is the worst possible designator** — 0.00 everywhere. This directly indicts the incumbent method in the Logrus TMS, where many `mt.chatgpt` entries are tag-shaped (`sq-MK`, `gsw-CH`, `zh-Hans`).
4. **`s_lang` was conflating two different questions.** Refusal is a *willingness* signal; wrong-language or degenerate output is a *capability* signal. Merging them lets a capable model be labelled incapable.

Limits: one model, 18 tags, 3 items per rung-1 cell. The designator finding is suggestive, not a measurement — a systematic sweep across many languages is the study that would settle it.

## Impact

- **Scoring changed:** refusals are excluded from `s_lang` and reported as `reliability` with a `refusals` count and an explanatory note. After the change `ug` reads **Strong, reliability 0.33** — "writes Uyghur well, refuses two-thirds of the time" — and `bo` **Strong, reliability 0.67**. Four tests added.
- **A separate bug fixed before the run:** 298 tags in the catalogue lacked `iso639_3`, and they were precisely the regional variants, so `de-AT` landed in class `de|Latn` while `de` was in `deu|Latn` — class collapse failing exactly where it matters. The generator now backfills from the base tag.
- **Unknown tags are reported rather than silently dropped** — `plan()` returns them, and both the scan and the dry run print them.
- `beat_incumbent` now distinguishes `False` (a comparison selection lost) from `None` (no comparison was possible), which are different facts.

**Open question for Andrei:** should low reliability cap the tier? `ug` at reliability 0.33 currently reads "Strong — light review", which is true about quality and potentially misleading about availability. Both numbers are shown, but the policy is a judgement call.
