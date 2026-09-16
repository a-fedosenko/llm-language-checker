"""OpenAI-compatible chat client.

Two behaviours here are load-bearing, both established by the experiment in
docs/02:

1. **Reasoning must be off.** Left at each model's default, gemini-3 and
   deepseek-v4 deliberate while gpt-4o does not, which makes results
   incomparable; on one prompt deepseek spent 299 tokens reasoning and returned
   empty content. `reasoning_effort: "none"` fixes it where supported.
2. **"OpenAI-compatible" is not uniform.** gpt-4o rejects `reasoning_effort`
   outright. Support is probed per model and cached, never assumed.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

DEFAULT_TIMEOUT = 180
RETRY_CODES = {429, 500, 502, 503, 529}


@dataclass
class Completion:
    text: str | None
    error: str | None
    truncated: bool = False
    usage: dict = field(default_factory=dict)
    model: str = ""
    latency_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.text is not None and self.error is None


class OpenAICompatClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: int = DEFAULT_TIMEOUT,
                 retries: int = 4, reasoning_effort: str | None = "none") -> None:
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/v1"):
            self.base_url += "/v1"
        self._key = api_key
        self.timeout = timeout
        self.retries = retries
        self.reasoning_effort = reasoning_effort
        self._no_reasoning_param: set[str] = set()

    def _redact(self, text: str) -> str:
        return text.replace(self._key, "[redacted]") if self._key else text

    def complete(self, model: str, prompt: str, *, max_tokens: int = 400,
                 temperature: float = 0.0) -> Completion:
        def payload(with_effort: bool) -> bytes:
            body = {"model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": temperature,
                    "max_tokens": max_tokens}
            if with_effort and self.reasoning_effort:
                body["reasoning_effort"] = self.reasoning_effort
            return json.dumps(body).encode()

        use_effort = model not in self._no_reasoning_param
        body = payload(use_effort)
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        started = time.monotonic()

        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(url, data=body, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.load(r)
            except urllib.error.HTTPError as e:
                detail = self._redact(e.read().decode("utf-8", "replace")[:300])
                if e.code == 400 and "reasoning_effort" in detail and use_effort:
                    # Model does not accept the parameter; it does not reason anyway.
                    self._no_reasoning_param.add(model)
                    use_effort = False
                    body = payload(False)
                    continue
                if e.code in RETRY_CODES and attempt < self.retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return Completion(None, f"HTTP {e.code}: {detail}", model=model,
                                  latency_s=time.monotonic() - started)
            except Exception as e:  # noqa: BLE001 - network/JSON failures are all retryable
                if attempt < self.retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return Completion(None, self._redact(f"{type(e).__name__}: {e}"), model=model,
                                  latency_s=time.monotonic() - started)

            choice = data["choices"][0]
            text = (choice.get("message", {}).get("content") or "").strip()
            usage = data.get("usage", {}) or {}
            latency = time.monotonic() - started
            finish = choice.get("finish_reason")
            if not text:
                # A reasoning model can burn the whole budget before emitting
                # anything. That is truncation, never a refusal, and must not be scored.
                return Completion(None, f"empty content (finish_reason={finish}, usage={usage})",
                                  truncated=finish == "length", usage=usage, model=model,
                                  latency_s=latency)
            return Completion(text, None, truncated=finish == "length", usage=usage,
                              model=model, latency_s=latency)

        return Completion(None, "exhausted retries", model=model,
                          latency_s=time.monotonic() - started)
