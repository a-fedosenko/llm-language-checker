# 019 — The script check's alphabet is incomplete, and now that costs a verdict

| | |
|---|---|
| **Date** | 2026-09-26 |
| **Status** | valid — **one hypothesis wrong, and the protocol's own premise overstated by a factor of ten** |
| **Triggered by** | Planning the breadth run. `lid.detect_script` can emit **29** ISO 15924 codes; the shipped scheme asks for **202**. Where the scheme wants a script the function cannot produce, `gate.check` returns `wrong_script` whatever the model wrote — and since [protocol 018](018-eligibility-and-adequacy.md) that is `Unusable`, full stop, with no appeal and no interval |
| **Artifacts** | `scripts/build_script_table.py`, `scripts/script_audit.py`, `data/unicode/scripts.json`, re-analysis of `data/calibration/study.json`. No model calls |

## Why this is not the same as protocol 016's finding

016 measured the deterministic script check being **right**: 15 of 15 real mismatches caught, against 0 of 15 for a capable LLM told explicitly to look. That result is not in question here and nothing below touches it.

This is the same function being **blind** — returning a confident negative for a script it has no way to name. Incompleteness, not error. The two are easy to conflate and have opposite fixes: 016 says never replace the check with a model call, and 019 says the check has to be able to spell the alphabet it is checking against.

It has become urgent because of 018. Under the five-tier scale a script miss was one term among several and a language could still land mid-scale; under the new one, ineligibility is absolute. **A blind spot that used to cost resolution now costs the whole verdict.**

## Scope of the damage, measured before the hypotheses

| | tags |
|---|---|
| scheme tags whose script the detector can never emit | **1,274** of 9,589 |
| — of those, `Zyyy` / `Zxxx` / `Zzzz` / `Brai` (no real script claim, or not scannable) | 697 |
| — of those, a real living writing system | **577** |
| classes in the planned `--with-controls --living-only` scan | **6** of 199 |

The six: `kor|Hang`, `zho|Hans`, `zho|Hant`, `yue|Hant`, `lao|Laoo`, `sat|Olck`. Korean and both Chinese among them.

Four of the six are in the S7 calibration study — `ko-Hang`, `zh-CN`, `yue`, `sat` — with committed output, so this protocol costs nothing to run.

## The four failures are not one failure

Separating them before testing, because they need different fixes and only one of them is hard:

1. **Alias mismatch.** The scheme says `Hang`; the table maps HANGUL to `Kore`. Both name Korean writing — `Hang` is Hangul, `Kore` is the composite Hangul+Han code — and they compare unequal. Nothing is undetected; two spellings disagree.
2. **Absent hints.** `Laoo`, `Olck` and most of the other 577 are missing from a hand-written table of 29 entries. Unicode character names carry the script as a prefix (`LAO LETTER KO`, `OL CHIKI LETTER LA`), so this table should be *derived*, not maintained by hand.
3. **Genuinely undecidable by block counting.** `Hans` versus `Hant`. Every Chinese character in both is `CJK UNIFIED IDEOGRAPH`; the distinction is which characters, not which block. No amount of fixing the table reaches this.
4. **No script claim at all.** `Zyyy` (undetermined), `Zxxx` (unwritten), `Zzzz` (unknown). The check currently fails these; it should not run.

And one adjacent constant, found while reading the gate: **`MIN_CHARS = 25`**, which voids an item as `too_short`. Chinese says in 20 characters what English needs 90 for.

## Hypothesis

Recorded before any code was changed.

1. **Deriving the table from Unicode closes most of the gap.** Generating script hints from character-name prefixes instead of hand-listing 29 will make **at least 150 of the scheme's 202 requested scripts** emittable, and will resolve `Hang`, `Laoo` and `Olck` — five of the six blocked classes in the planned scan, everything except the `Hans`/`Hant` pair.

2. **`Hans` versus `Hant` is not decidable by block detection, at all.** Prediction stated so it can fail: **100%** of the study's Chinese items will detect as one and the same script code whether the output is simplified or traditional. If even a few separate, block detection is doing more than I think and the fix is smaller than I think.

3. **A character-set discriminator does decide it.** Simplified and traditional forms are largely disjoint character sets. Built from the committed FLORES Chinese references and applied to the study's `zh-CN` and `yue` output, it will classify **at least 90%** of items correctly. Below ~80% the honest move is to stop claiming the distinction rather than ship a coin flip — the scheme would keep `Hans`/`Hant` as an addressing convention the gate does not verify, recorded as a limit.

4. **`MIN_CHARS = 25` is a Latin-centric constant that voids correct output.** At least **one in five** items in dense scripts (`Hans`, `Hant`, `Jpan`, `Hang`, `Mymr`) will fall below 25 characters while recalling ≥ 0.75 of their facts — correct text thrown away for being short in a script that is short.

5. **Nothing already working changes.** The regression guard, and the one that would sink the fix rather than adjust it: re-running the gate over all 378 committed items must change **zero** verdicts for items whose expected script the detector already handled — `Latn`, `Cyrl`, `Arab`, `Deva`, `Hebr`, `Beng`, `Gujr`, `Armn`, `Geor`, `Jpan`, `Mymr`. Any movement there means the generated table disagrees with the hand-written one about a script that was never in question, and the generated table would then need auditing rather than trusting.

**What would change the plan rather than the code:** H3 failing. If simplified/traditional cannot be separated reliably, then `Hans`/`Hant` must be documented as unverified addressing rather than silently passed or silently failed — and that is a statement the README and S8 have to carry, not a constant to tune.

## What is being tested

Whether the eligibility filter — now the component that can single-handedly declare a language unusable — can actually name the scripts the catalogue asks it about, and what it should do where it cannot.

## Setup

| | |
|---|---|
| Models | none. Re-analysis plus local Unicode work |
| Data | `data/calibration/study.json` (378 committed items, 100 languages), `schemes/default.json` (9,589 tags), FLORES-200 Chinese references |
| Libraries | `unicodedata` from the standard library; GlotLID for the language half, unchanged |

## Method

Three parts, none of them costing a model call:

1. **Coverage.** Compare what the scheme asks for against what the detector can name — first the shipped hand-written table, then a replacement built from Unicode's own data.
2. **The Chinese question.** Test whether block detection can separate simplified from traditional at all, and whether a character-set discriminator can.
3. **Regression.** Re-run the gate over all 378 committed calibration items and require that nothing moves for a script that already worked.

## Correction to this protocol's own premise

**The "1,274 tags" figure in the trigger is wrong for the configuration the tool actually runs in**, and I should have checked before writing it down.

It was computed from `_SCRIPT_HINTS` in isolation. But `lid.identify` did not use `detect_script` for the final answer — it used `scr or script`, where `scr` is the script suffix of **GlotLID's own label** (`kor_Hang`, `ary_Arab`). GlotLID's 2,102 labels carry **163 distinct script suffixes**, and those were silently doing the naming wherever they were present. The hand-written table of 29 was the fallback, not the instrument.

So the real damage was an order of magnitude smaller:

| | scripts | tags |
|---|---|---|
| real scripts the scheme asks about | 198 | 8,892 |
| nameable before 019 (GlotLID's suffixes) | 158 | 8,773 |
| **blocked before 019** | **40** | **119** |
| nameable after 019 | 176 | 8,865 |
| abstained after 019 (unencoded, undeciphered, invented) | 22 | 27 |

The 1,274 figure is true of exactly one configuration: the **script-only fallback**, which `lid.py` supports by design for a machine with no GlotLID model — *"falls back to a script-block check when the model file is absent, so the tool still runs, with reduced power."* In that mode the hand-written table **is** the instrument and all 1,274 really are unpassable. That is worth fixing too, but it is not what the breadth run would have hit.

What survives intact is the part that prompted the protocol: **63 of those 119 tags are Chinese** (`Hant` 36, `Hans` 27), and Korean's `Kore` is 3 more.

## Results

### H1 — wrong as stated; the right fix was a different one

I predicted a table *derived from Unicode character-name prefixes* would cover ≥ 150 of 202 scripts. Built, it covered **81**, and it *lost* Latin, Cyrillic and Greek outright.

The reason is simple and I should have seen it: **ISO 15924 codes are not the first four letters of the script's name.** `LATIN` is `Latn`, not `Lati`; `CYRILLIC` is `Cyrl`, not `Cyri`; `GREEK` is `Grek`. There is no rule — the codes are assigned.

The fix is to stop deriving and start reading the authority. Unicode publishes the mapping directly:

| file | supplies |
|---|---|
| `Scripts.txt` | codepoint ranges → Unicode script long name |
| `PropertyValueAliases.txt` | `sc ; Latn ; Latin` — long name → ISO 15924 |
| `Unihan_Variants.txt` | which Han characters are simplified-only and which traditional-only |

`scripts/build_script_table.py` turns these into a committed 98 KB table, so a clean clone needs no network. Coverage goes from 29 hand-written prefixes to **177 scripts, zero heuristics**.

Three residues needed rules rather than data:

- **Composites.** `Jpan`, `Kore` and `Hanb` are ISO codes for *combinations* — Japanese is Han plus two kana. The Unicode script property has no value for them. Without an explicit rule, switching to Unicode data would have **regressed Japanese and Korean**, which the old table happened to get right. H5 caught this; see below.
- **Typographic variants.** `Latf` (Fraktur), `Latg` (Gaelic), `Cyrs` (Old Church Slavonic) are encoded as their parent script. Detection can honestly return the parent, so they map to it.
- **Unencoded, undeciphered and invented.** Tengwar, Klingon, Indus, Mayan, Blissymbols and eighteen others — 22 scripts, 27 tags. Nothing available here can verify these, so the gate **abstains** rather than convicting. That is the category I had not anticipated at all and it is the one that matters most in principle: a confident negative about a question you cannot ask is the worst possible output.

### H2 — confirmed, exactly as predicted

**100%** of the study's Chinese and Cantonese items detect as one and the same code under block counting. Every character in both forms is `CJK UNIFIED IDEOGRAPH`; the script property has one value, `Hani`, and no table can change that.

### H3 — confirmed, and it caught a real failure on the way

Built from Unihan's variant fields — a character with a traditional variant other than itself is a simplified form, and vice versa — the discriminator yields 6,825 simplified-only and 6,872 traditional-only characters.

On the seven committed Chinese items it is **7 of 7 correct about what the text is**, with clean margins (20–0, 0–9, 0–10), no ambiguous calls. Against the *requested* script it reads 6 of 7, and the seventh is the interesting one:

> `yue-0`, requested Cantonese in traditional script. Simplified characters 17, traditional 0. The model answered in **simplified Mandarin** — which GlotLID independently called `cmn_Hani` at 0.91 confidence.

The discriminator is right and the request was not met. Previously this item was `wrong_script` for the wrong reason, and its three siblings were `too_short`.

### H4 — confirmed, above the predicted rate

**5 of 19** dense-script items (26%, against a predicted 1 in 5) sit below the 25-character floor while recalling **every** fact. A correct Chinese sentence — *当地媒体报道，一辆机场消防车在出动时翻车。* — is 21 characters. The floor guards against a one-word answer, and one word is not 25 characters everywhere. `MIN_CHARS_DENSE = 10` applies to twelve dense scripts.

### H5 — confirmed, after it failed twice and caught two real bugs

The regression guard did more work than any other part of this protocol. It required zero verdict changes among items whose script already worked, and on the first two attempts it was violated:

1. **`ja-0`: `pass` → `wrong_script`.** The composite rule required a text to consist *only* of a composite's parts. Real output does not: *"JAS 39C Gripenは午前9時30分頃、滑走路に墜落した。"* is nine Latin letters against nine Han and five kana. A composite is now weighed as a whole — its parts summed and compared against the largest script that is not one of them — rather than by dominance or purity.
2. **Chinese landing on `low_confidence` instead of `pass`**, which exposed the premise error above: `identify` was preferring GlotLID's coarse label suffix over the deterministic reading, so no improvement to the script table could reach the gate's verdict.

Final state: **6 verdicts change across 378 items, 0 of them regressions.**

| item | before | after | |
|---|---|---|---|
| `zh-CN` ×3 | `wrong_script`, `too_short` ×2 | **`pass`** | correct simplified Chinese, now recognised |
| `yue` ×3 | `too_short` ×3 | **`relative_substitution`** | traditional-script *Mandarin* when asked for Cantonese |
| `ko-Hang` ×4 | `pass` | `pass` | unchanged — GlotLID's `_Hang` suffix was already carrying it |
| `sat` ×4 | `wrong_script` | `wrong_script` | unchanged, and now for the right reason: Santali answered in Latin and Devanagari (protocol 016) |

The scale from [protocol 018](018-eligibility-and-adequacy.md) stays monotonic on the corrected verdicts, ρ 0.644, with `zh-CN` moving from `Unusable` to `Proficient`.

## Conclusions

1. **The gate was not comparing what protocol 016 measured.** 016's 15-of-15 script result was measured on `detect_script` directly; the gate's verdict came from GlotLID's label suffix. They agree for most scripts and disagree for Chinese, where GlotLID has one label for a distinction ISO 15924 makes. The deterministic reading now wins and GlotLID's suffix is the fallback. **016's finding is unaffected and is now actually the one in force.**

2. **A check that cannot name the answer must abstain, not convict.** 22 scripts have no verifiable form here — unencoded, undeciphered, or invented. Under the five-tier scale a wrong `wrong_script` cost resolution; under protocol 018's scale it costs the entire verdict, unappealably. Abstention is recorded on the result rather than being silent.

3. **Simplified versus traditional is decidable, cheaply and deterministically.** 7 of 7 with clean margins, from a committed table derived from Unicode's own variant data. This matters commercially out of proportion to its size: 63 tags, and they are among the most-requested locales a TMS handles.

4. **Constants have a script.** `MIN_CHARS = 25` was a reasonable number written by someone thinking in Latin. It voided a quarter of the adequate Chinese sample.

5. **The premise-checking failure is the transferable lesson.** I wrote "1,274 tags can never pass" into a protocol from a measurement of one function in isolation, without checking what the calling path actually did with its result. It was wrong by a factor of ten, and it was wrong in the direction that made the work look more urgent. Convention 6 says read the raw evidence before claiming a finding; this is the same rule applied to a number rather than to a model's output.

**Limits:** seven Chinese items is a small sample for H3, though the margins are wide and the mechanism is a character-set lookup rather than a model. The 27 abstaining tags are untested by construction — there is no output in Tengwar to test against. Korean, Lao and Ol Chiki are fixed by construction and verified only for Korean, which the study happens to contain.

## Impact

- `probe/lid.py`: `detect_script` reads a committed Unicode-derived table instead of 29 hand-written prefixes; gains `expect` so a composite or variant can be named the way the catalogue names it; gains `script_is_verifiable`; and `identify` now prefers the deterministic reading over GlotLID's label suffix.
- `probe/gate.py`: abstains where the expected script is unverifiable; voids ambiguous Han as `low_confidence` rather than convicting; length floor follows the script (`MIN_CHARS_DENSE = 10` for twelve dense scripts).
- `scripts/build_script_table.py` generates `data/unicode/scripts.json` from the UCD; `--refresh` re-downloads.
- Six new tests in `tests/test_gate.py`, including the two failures H5 caught.
- **The breadth run is unblocked.** Of the six classes it could not have passed, five are fixed and `sat|Olck` now fails for the right reason.
