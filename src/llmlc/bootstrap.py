"""First-run assets: what a scan needs that the repository cannot ship.

Two files decide whether this tool measures anything, and neither can be
committed:

  GlotLID        1.6 GB. Too large for a repository, and it is the whole
                 language half of the deterministic gate. Without it `probe/lid`
                 falls back to script-only: the gate still catches wrong script,
                 and stops catching wrong *language* -- which is the question the
                 tool exists to answer (protocol 004).

  FLORES controls  Derived from FLORES-200, CC BY-SA 4.0. Share-alike attaches to
                 redistributing derived text, so it is built on first use. Without
                 it only the three hand-seeded controls (cv, de, ru) exist, and
                 since `no-control` is never a pass, a 200-language scan returns
                 ~197 `unverified`.

Before this module, a fresh clone could `docker compose up` and start a scan that
looked like it worked and was measuring with half an instrument, silently. That
is the same defect protocol 019 fixed in the script check and protocol 005 fixed
in back-translator qualification: **when the instrument is missing, say so —
never quietly answer worse.**

Downloading is deliberate rather than automatic. 1.6 GB on `compose up` would be
a rude surprise, and an unattended deployment can set `AUTO_BOOTSTRAP=1`.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import tarfile
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from llmlc.probe import lid

ROOT = pathlib.Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache"
CONTROLS_DIR = ROOT / "data" / "controls"
FLORES_CONTROLS = CONTROLS_DIR / "flores.json"

FLORES_URL = "https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz"
FLORES_ARCHIVE = CACHE / "flores200.tar.gz"
FLORES_EXTRACTED = CACHE / "flores200_dataset"
PIVOT = "eng_Latn"
ATTRIBUTION = ("FLORES-200 (c) Meta AI, CC BY-SA 4.0. "
               "https://github.com/facebookresearch/flores")


@dataclass(frozen=True)
class Asset:
    key: str
    title: str
    path: pathlib.Path
    size_hint: str
    licence: str
    #: What stops working without it, in the terms a user cares about.
    degraded: str

    @property
    def present(self) -> bool:
        return self.path.exists()

    def as_dict(self) -> dict:
        size = self.path.stat().st_size if self.present else 0
        return {"key": self.key, "title": self.title, "present": self.present,
                "path": str(self.path.relative_to(ROOT)), "bytes": size,
                "size_hint": self.size_hint, "licence": self.licence,
                "degraded": self.degraded}


ASSETS = (
    Asset("glotlid", "GlotLID language identification", lid.MODEL_PATH, "~1.6 GB",
          "Apache-2.0 (cis-lmu/glotlid)",
          "The gate cannot check which language was produced, only which script. "
          "A model answering in Indonesian when asked for Acehnese would pass."),
    Asset("controls", "FLORES-200 back-translator controls", FLORES_CONTROLS, "~25 MB download",
          "CC BY-SA 4.0 (Meta AI) — derived text, so built locally, never redistributed",
          "Only cv, de and ru can have a back-translator qualified. Every other "
          "language reports `unverified` rather than a score, because a "
          "back-translator that cannot read a language fabricates rather than refusing."),
)

ASSETS_BY_KEY = {a.key: a for a in ASSETS}


def status() -> dict:
    assets = [a.as_dict() for a in ASSETS]
    missing = [a for a in assets if not a["present"]]
    return {
        "ready": not missing,
        "assets": assets,
        "missing": [a["key"] for a in missing],
        # A scan will *run* without these. That is the problem: it runs and
        # measures less than it claims, so the answer is stated rather than left
        # for the user to infer from surprising results.
        "scan_meaningful": not missing,
    }


# -- fetchers -----------------------------------------------------------------

def _download(url: str, dest: pathlib.Path, on_progress: Callable[[str], None]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=900) as r:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        step = max(total // 20, 8 << 20) if total else 8 << 20
        next_mark = step
        with tmp.open("wb") as fh:
            while chunk := r.read(1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if done >= next_mark:
                    pct = f" ({done * 100 // total}%)" if total else ""
                    on_progress(f"    {done // (1 << 20)} MB{pct}")
                    next_mark += step
    # Move into place only once complete, so an interrupted download never looks
    # like a present asset on the next run.
    tmp.replace(dest)


def fetch_glotlid(on_progress: Callable[[str], None] = print) -> pathlib.Path:
    on_progress(f"  downloading GlotLID ({ASSETS_BY_KEY['glotlid'].size_hint}) ...")
    _download(lid.MODEL_URL, lid.MODEL_PATH, on_progress)
    lid.available.cache_clear() if hasattr(lid.available, "cache_clear") else None
    return lid.MODEL_PATH


def _fetch_flores(on_progress: Callable[[str], None]) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    if not FLORES_ARCHIVE.exists():
        on_progress("  downloading FLORES-200 (~25 MB) ...")
        _download(FLORES_URL, FLORES_ARCHIVE, on_progress)
    if not FLORES_EXTRACTED.exists():
        on_progress("  extracting ...")
        with tarfile.open(FLORES_ARCHIVE) as t:
            t.extractall(CACHE, filter="data")


def _tag_index(scheme) -> dict[tuple[str, str], str]:
    """(iso639_3, script) -> canonical tag, preferring the shortest form.

    Falls back to the macrolanguage where FLORES names a member code that the
    catalogue represents by its macro tag -- arb under ar, azj under az, khk
    under mn, lvs under lv, and so on.
    """
    index: dict[tuple[str, str], str] = {}
    for tag, lang in scheme.languages.items():
        key = (lang.iso639_3, lang.script)
        if key[0] and (key not in index or len(tag) < len(index[key])):
            index[key] = tag
    for tag, lang in scheme.languages.items():
        if not lang.is_macro:
            continue
        for member in lang.members:
            index.setdefault((member, lang.script), tag)
    return index


def build_controls(n_items: int = 4) -> dict:
    """Assemble the control set from the extracted FLORES corpus."""
    from llmlc.scheme import load_scheme

    scheme = load_scheme("default")
    index = _tag_index(scheme)

    pivot_lines = (FLORES_EXTRACTED / "dev" / f"{PIVOT}.dev").read_text(
        encoding="utf-8").splitlines()
    # Mid-length sentences: long enough to carry meaning, short enough to
    # back-translate cheaply and to keep chrF++ stable.
    chosen = [i for i, s in enumerate(pivot_lines) if 60 <= len(s) <= 160][:n_items]

    controls: dict[str, dict] = {}
    unmapped: list[str] = []
    for path in sorted((FLORES_EXTRACTED / "dev").glob("*.dev")):
        code = path.stem
        if code == PIVOT:
            continue
        iso, _, script = code.partition("_")
        tag = index.get((iso, script))
        if not tag:
            unmapped.append(code)
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) != len(pivot_lines):
            unmapped.append(code)
            continue
        # First mapping wins, so a base tag is not overwritten by a variant.
        controls.setdefault(tag, {
            "flores_code": code,
            "items": [{"text": lines[i], "reference": pivot_lines[i]} for i in chosen],
        })

    return {
        "meta": {
            "source": "FLORES-200 dev split",
            "url": FLORES_URL,
            "license": "CC BY-SA 4.0",
            "attribution": ATTRIBUTION,
            "pivot": "en",
            "kind": "reference",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "items_per_language": len(chosen),
            "counts": {"languages": len(controls), "unmapped": len(unmapped)},
            "unmapped": unmapped,
        },
        "controls": controls,
    }


def fetch_controls(on_progress: Callable[[str], None] = print,
                   n_items: int = 4) -> pathlib.Path:
    _fetch_flores(on_progress)
    data = build_controls(n_items)
    FLORES_CONTROLS.parent.mkdir(parents=True, exist_ok=True)
    FLORES_CONTROLS.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                               encoding="utf-8")
    c = data["meta"]["counts"]
    on_progress(f"  {c['languages']} languages x {data['meta']['items_per_language']} "
                f"items ({c['unmapped']} unmapped)")
    return FLORES_CONTROLS


FETCHERS: dict[str, Callable[..., pathlib.Path]] = {
    "glotlid": fetch_glotlid,
    "controls": fetch_controls,
}


def ensure(keys: list[str] | None = None,
           on_progress: Callable[[str], None] = print) -> dict:
    """Fetch the named assets, or every missing one. Idempotent."""
    wanted = keys or [a.key for a in ASSETS if not a.present]
    fetched, skipped = [], []
    for key in wanted:
        asset = ASSETS_BY_KEY.get(key)
        if asset is None:
            raise KeyError(f"Unknown asset {key!r}; known: {sorted(ASSETS_BY_KEY)}")
        if asset.present:
            skipped.append(key)
            continue
        on_progress(f"{asset.title}")
        FETCHERS[key](on_progress)
        fetched.append(key)
    return {"fetched": fetched, "already_present": skipped, **status()}


def auto() -> dict | None:
    """Fetch everything at startup when AUTO_BOOTSTRAP is set. Off by default:
    1.6 GB arriving unannounced on `compose up` would be a rude surprise."""
    if os.environ.get("AUTO_BOOTSTRAP", "").lower() not in ("1", "true", "yes"):
        return None
    return ensure()


def disk_free_mb(path: pathlib.Path = ROOT) -> int:
    return shutil.disk_usage(path).free // (1 << 20)
