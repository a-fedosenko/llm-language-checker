#!/usr/bin/env python3
"""Build back-translator control texts from FLORES-200.

Thin wrapper. The logic lives in `llmlc.bootstrap` so that it also exists inside
the container -- the image copies `src/` and not `scripts/`, so anything only
implemented here cannot be run by someone who cloned and ran `docker compose up`.

Usage:  python scripts/build_controls.py [--items 4] [--refresh]
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from llmlc import bootstrap  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", type=int, default=4, help="control sentences per language")
    ap.add_argument("--refresh", action="store_true", help="re-download and rebuild")
    a = ap.parse_args()

    if a.refresh:
        for p in (bootstrap.FLORES_CONTROLS, bootstrap.FLORES_ARCHIVE):
            p.unlink(missing_ok=True)
    out = bootstrap.fetch_controls(n_items=a.items)
    print(f"wrote {out.relative_to(bootstrap.ROOT)}")


if __name__ == "__main__":
    main()
