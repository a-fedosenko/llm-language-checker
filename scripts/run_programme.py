"""Run the cross-engine measurement programme through the running container.

Deliberately over HTTP rather than in-process: the point is to exercise the path
a person who cloned the repository would use, so that "clone, compose up, scan"
is tested by us before it is promised to anyone else. Nothing here touches the
working tree — it only calls the API the container serves.

One scan at a time (SQLite takes one writer), so engines run in sequence.

    .venv/bin/python scripts/run_programme.py --base http://localhost:8089
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

#: The comparison set. Panel members are deliberately absent — a model that is
#: also a back-translator gets dropped from its own panel and is then measured
#: through a different instrument from every other engine (docs/03, S8).
ENGINES = [
    "openai-gpt-4o",
    "gemini-gemini-3-8-flash",
    "deepseek-deepseek-v4-pro",
    "groq-qwen3-8-27b",
]


def api(base: str, path: str, body: dict | None = None, timeout: int = 60):
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json"} if data is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{path} -> HTTP {e.code}: {e.read().decode()[:300]}") from e


def target_tags() -> list[str]:
    """Every living language that has a back-translator control — the same set
    `llmlc scan --with-controls --living-only` produces."""
    from llmlc.bt import load_controls
    from llmlc.scheme import load_scheme
    have = set(load_controls())
    return [x.tag for x in load_scheme("default").languages.values()
            if x.type == "L" and x.tag in have]


def wait(base: str, job_id: int, poll: int = 30) -> dict:
    last = None
    while True:
        j = api(base, f"/jobs/{job_id}")
        if j.get("status") != "running":
            return j
        used = j.get("calls_used")
        if used != last:
            print(f"    job {job_id}: {used} calls", flush=True)
            last = used
        time.sleep(poll)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8089")
    ap.add_argument("--max-calls", type=int, default=5000)
    ap.add_argument("--engine", action="append", help="override the engine list")
    a = ap.parse_args()

    ready = api(a.base, "/readiness")
    if not ready["ready"]:
        raise SystemExit(f"instrument incomplete: {ready['missing']} — "
                         f"POST /bootstrap or run `llmlc bootstrap` first")

    tags = target_tags()
    engines = a.engine or ENGINES
    print(f"{len(tags)} tags, {len(engines)} engine(s), ceiling {a.max_calls} calls each\n")

    for engine in engines:
        plan = api(a.base, f"/scans/plan?engine={engine}&tags={','.join(tags)}")
        print(f"{engine}: {plan['classes']} classes, ~{plan['estimate_calls']} calls")
        started = api(a.base, "/scans", {"engine": engine, "tags": tags,
                                         "max_calls": a.max_calls})
        print(f"  job {started['job_id']} started", flush=True)
        done = wait(a.base, started["job_id"])
        print(f"  {done['status']}, {done.get('calls_used')} calls"
              f"{' — ' + done['error'] if done.get('error') else ''}\n", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
