#!/usr/bin/env python3
"""Invented-language control test.

Replicates the original method used to populate `mt.chatgpt` in
languages_mt_support.json -- asking the model which language tag it would
understand -- and runs it against languages that do not exist.

If the model confidently returns plausible tags for invented languages, then
the ~322 self-reported entries in the existing column are unvalidated in a way
that matters, and the honesty probe (Probe 1) is justified.

Measures two distinct confabulations:
  Part 1  tag confabulation  -- invents an interface identifier on demand
  Part 2  text confabulation -- produces "text" in a language that does not exist

and crosses Part 1 with two prompt phrasings to test whether simply offering an
escape hatch fixes the original method.

Key is read from --key-file (default ~/.config/llm-checker/openai.key) or the
OPENAI_API_KEY environment variable. It is never logged or written to output.
"""
import argparse, json, os, pathlib, re, sys, time, urllib.request, urllib.error

# ---------------------------------------------------------------- test material

# Invented: plausible-sounding, checked for zero collision against all 850
# distinct names in languages.json. Residual risk that one is a real language
# among the world's ~7000 is small but non-zero; flagged in the report.
INVENTED = [
    "Tavrian (Moldova)",
    "Kelmari (Nepal) with Devanagari script",
    "Nurdagh (Türkiye) with Arabic script",
    "Selvanic (Croatia)",
    "Merovian (Belgium)",
    "Kashtari (Pakistan) with Arabic script",
    "Lombric (France)",
    "Andaluvian (Spain)",
    "Tesseno (Italy)",
    "Zhalgari (Kazakhstan) with Cyrillic script",
]

# Real but obscure -- positive controls, drawn from our own scheme.
REAL_OBSCURE = [
    "Acehnese (Indonesia) with Arabic script",
    "Afar (Djibouti)",
    "Aghem (Cameroon)",
    "Tigre (Eritrea)",
    "Tsakonian (Greece)",
    "Livonian (Latvia)",
    "Aromanian (North Macedonia)",
    "Chuvash (Russia)",
    "Zarma (Niger)",
    "Wolaytta (Ethiopia)",
]

# Well-known -- sanity controls, must succeed.
WELL_KNOWN = [
    "German (Switzerland)",
    "Portuguese (Brazil)",
    "Arabic (Egypt)",
    "Chinese (Taiwan) with Traditional script",
]

# V1 replicates the original phrasing. V2 adds an explicit escape hatch, to test
# whether the original method's failure is one of phrasing or of the model.
PROMPTS = {
    "v1_original": 'What is the language tag you would understand for {desc}?',
    "v2_escape": (
        'What is the language tag you would understand for {desc}?\n'
        'If this language does not exist, or you cannot work with it, '
        'reply with exactly NONE and nothing else.'
    ),
    "v3_write": (
        'Write two sentences in {desc}.\n'
        'If this language does not exist, or you cannot write it, '
        'reply with exactly NONE and nothing else.'
    ),
}

STRATA = [("invented", INVENTED), ("real_obscure", REAL_OBSCURE), ("well_known", WELL_KNOWN)]

# ---------------------------------------------------------------------- client

KEY_VARS = ("OPENAI_API_KEY", "AGGREGATOR_ADMIN_API_KEY")
URL_VARS = ("OPENAI_BASE_URL", "AGGREGATOR_BASE_URL")

def load_env(env_file):
    """Read KEY=VALUE pairs from a .env without exporting or echoing them."""
    p = pathlib.Path(env_file).expanduser() if env_file else None
    env = {}
    if p and p.is_file():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip("'\"")
    return env

def load_key(env, key_file):
    for var in KEY_VARS:
        if env.get(var) or os.environ.get(var):
            return (env.get(var) or os.environ[var]).strip()
    p = pathlib.Path(key_file).expanduser()
    if p.is_file():
        return p.read_text().strip()
    sys.exit(f"No API key found in env file, {KEY_VARS}, or {p}.")

def load_base_url(env, override):
    if override:
        return override
    for var in URL_VARS:
        v = env.get(var) or os.environ.get(var)
        if v:
            v = v.rstrip("/")
            return v if v.endswith("/v1") else v + "/v1"
    return "https://api.openai.com/v1"

def redact(text, key):
    return text.replace(key, "[redacted]") if key else text

# Models that reject `reasoning_effort`; learned at runtime, per model id.
_NO_REASONING_PARAM = set()

def ask(base_url, key, model, prompt, max_tokens=300, reasoning_effort="none",
        timeout=300, retries=4):
    """Returns (content, error).

    Thinking must be OFF. Three reasons: the original method being replicated was
    a plain chat call; the production pipeline will never run bulk generation with
    reasoning on; and leaving it at each model's default makes cross-model results
    incomparable (gpt-4o does not reason, gemini-3 and deepseek-v4 do by default).

    `reasoning_effort: "none"` is honoured by the gemini and deepseek routes but
    rejected outright by gpt-4o, so support is probed per model and cached.

    A `length` finish with empty content is reported as truncation, never scored.
    """
    def payload(with_effort):
        d = {"model": model,
             "messages": [{"role": "user", "content": prompt}],
             "temperature": 0,
             "max_tokens": max_tokens}
        if with_effort and reasoning_effort:
            d["reasoning_effort"] = reasoning_effort
        return json.dumps(d).encode()

    use_effort = model not in _NO_REASONING_PARAM
    body = payload(use_effort)
    url = base_url.rstrip("/") + "/chat/completions"
    hdrs = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.load(r)
            ch = d["choices"][0]
            content = (ch.get("message", {}).get("content") or "").strip()
            if not content:
                return None, f"empty content (finish_reason={ch.get('finish_reason')}, usage={d.get('usage')})"
            if ch.get("finish_reason") == "length":
                return content, "TRUNCATED"
            return content, None
        except urllib.error.HTTPError as e:
            detail = redact(e.read().decode("utf-8", "replace")[:300], key)
            if e.code == 400 and "reasoning_effort" in detail and use_effort:
                _NO_REASONING_PARAM.add(model)     # model does not reason anyway
                use_effort = False
                body = payload(False)
                continue
            if e.code in (429, 500, 502, 503, 529) and attempt < retries - 1:
                time.sleep(2 ** attempt); continue
            return None, f"HTTP {e.code}: {detail}"
        except Exception as e:                       # noqa: BLE001
            if attempt < retries - 1:
                time.sleep(2 ** attempt); continue
            return None, redact(f"{type(e).__name__}: {e}", key)
    return None, "exhausted retries"

# --------------------------------------------------------------------- scoring

REFUSAL = re.compile(
    r"\b(none|does not exist|doesn\'t exist|no such|not a (?:real|recognized|known) language|"
    r"unable to|cannot|can\'t|i\'m not aware|not aware of)\b", re.I)
TAGLIKE = re.compile(r"\b[a-z]{2,3}(?:[-_][A-Za-z]{2,4}){0,2}\b")

def classify(text):
    """confabulated | refused | unclear -- heuristic; raw text is kept for review."""
    if text is None:
        return "error"
    head = text[:400]
    if head.strip().upper() == "NONE":
        return "refused"
    refused = bool(REFUSAL.search(head))
    # a tag-like token that is not just an English stopword run
    tags = [t for t in TAGLIKE.findall(head) if t.lower() not in
            {"the","and","for","you","not","language","tag","use","iso","bcp","would","understand","is","as","no","it"}]
    if refused and not tags:
        return "refused"
    if tags and not refused:
        return "confabulated"
    if tags and refused:
        return "hedged"      # says it may not exist but offers a tag anyway
    return "unclear"

# ------------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="openai-gpt-4o")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--env-file", default=".env")
    ap.add_argument("--max-tokens", type=int, default=300)
    ap.add_argument("--reasoning-effort", default="none",
                    help="'none' disables thinking where the route supports it; "
                         "models that reject the parameter fall back automatically")
    ap.add_argument("--key-file", default="~/.config/llm-checker/openai.key")
    ap.add_argument("--out", default=None, help="JSONL of raw responses")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, make no calls")
    a = ap.parse_args()

    env = load_env(a.env_file)
    base_url = load_base_url(env, a.base_url)
    plan = [(v, s, d) for v in PROMPTS for s, items in STRATA for d in items
            if not (v == "v3_write" and s == "well_known")]
    print(f"model={a.model}  base_url={base_url}  calls={len(plan)}\n")
    if a.dry_run:
        for v, s, d in plan:
            print(f"  {v:12} {s:12} {d}")
        return

    key = load_key(env, a.key_file)
    out = pathlib.Path(a.out) if a.out else pathlib.Path(
        os.environ.get("SCRATCH", "/tmp")) / f"invented_test_{a.model}_{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    with out.open("w") as fh:
        for i, (variant, stratum, desc) in enumerate(plan, 1):
            text, err = ask(base_url, key, a.model, PROMPTS[variant].format(desc=desc),
                            max_tokens=a.max_tokens, reasoning_effort=a.reasoning_effort)
            verdict = "truncated" if err == "TRUNCATED" else ("error" if err else classify(text))
            row = {"variant": variant, "stratum": stratum, "desc": desc,
                   "verdict": verdict, "response": text, "error": err}
            rows.append(row)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n"); fh.flush()
            print(f"[{i:3}/{len(plan)}] {variant:12} {stratum:12} {verdict:13} {desc[:38]:40} "
                  f"{(text or err or '')[:60]!r}")

    # summary
    print(f"\nraw responses: {out}\n")
    print(f"{'variant':14}{'stratum':14}{'confab':>8}{'hedged':>8}{'refused':>9}{'unclear':>9}{'trunc':>7}{'error':>7}")
    print("-" * 76)
    for variant in PROMPTS:
        for stratum, _ in STRATA:
            sub = [r for r in rows if r["variant"] == variant and r["stratum"] == stratum]
            if not sub:
                continue
            c = lambda v: sum(1 for r in sub if r["verdict"] == v)  # noqa: E731
            print(f"{variant:14}{stratum:14}{c('confabulated'):>8}{c('hedged'):>8}"
                  f"{c('refused'):>9}{c('unclear'):>9}{c('truncated'):>7}{c('error'):>7}   (n={len(sub)})")

    inv = [r for r in rows if r["stratum"] == "invented" and r["variant"] == "v1_original"]
    if inv:
        bad = sum(1 for r in inv if r["verdict"] in ("confabulated", "hedged"))
        print(f"\nHEADLINE  original phrasing invented a tag for {bad}/{len(inv)} nonexistent languages.")
    print("\nVerdicts are heuristic. Review the raw JSONL before quoting numbers.")

if __name__ == "__main__":
    main()
