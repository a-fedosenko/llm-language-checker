# 007 — FLORES sourcing and scheme mapping

| | |
|---|---|
| **Date** | 2026-09-16 |
| **Status** | valid |
| **Triggered by** | [005](005-backtranslator-fabrication.md) made control coverage the binding constraint: three hand-seeded languages meant everything else returned `unverified` |
| **Artifacts** | `scripts/build_controls.py`, `data/controls/flores.json` |

## Hypothesis

That FLORES+ could be downloaded on first use without authentication, giving control texts for ~200 languages, and that its language codes would map cleanly onto the canonical scheme.

Both halves were partly wrong.

## What was tested

1. Which FLORES sources are reachable without credentials.
2. How many of its languages map to canonical tags, and what the misses are.
3. Whether the languages we actually care about are covered.

## Setup

| | |
|---|---|
| Sources probed | `openlanguagedata/flores_plus`, `facebook/flores`, `Muennighoff/flores200`, `dreamproit/flores_plus` on HuggingFace; Meta's `dl.fbaipublicfiles.com` tarball; Microsoft NTREX-128 on GitHub |
| Scheme | `schemes/default.json`, 9,589 tags from ISO 639-3 + SIL langtags |

## Results

**Availability:**

| Source | Status |
|---|---|
| `openlanguagedata/flores_plus` | `gated: auto` — **HTTP 401** unauthenticated |
| `facebook/flores` | `gated: auto` |
| `Muennighoff/flores200` | ungated but contains only a **loader stub** (3 files, no data) |
| **`dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz`** | **HTTP 200, 25 MB, no auth** ✅ |
| NTREX-128 (GitHub) | ungated, 128 languages — but **no Chuvash** |

**Contents:** 204 languages, 997 sentences per language in the `dev` split, line-aligned.

**Mapping:** 183/204 mapped on `(iso639_3, script)` alone. The 21 misses were macrolanguage *members* that the catalogue represents by the macro tag — `arb`, `azj`, `khk`, `lvs`, `gaz`, `kmr`. Adding a macrolanguage fallback raised it to **200/204**, leaving 2 unmapped (`ajp_Arab`, `arb_Latn`).

**Chuvash is not in FLORES.** ~1M speakers, absent from the 204.

## Conclusions

- FLORES is obtainable without credentials, but **not from the sources one would try first**. The HuggingFace route needs a token; the original tarball does not.
- Code mapping cannot be done on `(iso, script)` alone — the macrolanguage/member relation is required. This is the same relation that later caused two scoring bugs in [008](008-twenty-language-spread.md); it recurs everywhere.
- **204 languages is not the long tail.** Chuvash's absence is the concrete demonstration, and the reason the hand-seeded fact-based control path stays as a real mechanism rather than a stopgap.

## Impact

- `scripts/build_controls.py` ingests the tarball on first use into `data/`, gitignored (**corrected 2026-09-17**: the generated `flores.json` was in fact committed in S2 and only untracked later, when Andrei asked what the repository tracks) — so the repository stays clear of CC BY-SA text while the corpus does its work. Attribution in the README and on published results.
- Control coverage went from 3 to **201 languages** (200 reference + 1 facts).
- The macrolanguage fallback became a named function, reused by the scheme mapping.
