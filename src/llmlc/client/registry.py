"""Where a model's endpoint and key come from.

Two sources, in a fixed order, because they answer different needs:

1. **`CUSTOM_MODEL_LIST_PATH`** -- a JSON file listing models one by one, each
   with its own endpoint and its own key. This is the general case and the only
   one a public user needs: it reaches OpenAI, Anthropic-compatible gateways,
   a local vLLM and a colleague's proxy in the same scan, because nothing here
   assumes the models share a provider.
2. **`AGGREGATOR_BASE_URL` + `AGGREGATOR_ADMIN_API_KEY`** -- one endpoint and
   one key serving every model id. This is how the project was built and how its
   own measurements were taken, so it stays supported; it is simply the narrower
   case, and the JSON wins where both are present.

Neither configured is not an error state to paper over. `NotConfigured` carries
a message naming both routes, in the same spirit as the bootstrap check: when
the instrument is missing, say so rather than quietly answering worse.

The routing client exists so none of this reaches the pipeline. `scan`, the
ladder, the judge and the back-translators all take one `client` and call
`complete(model, ...)` on it with whatever model they need; `RoutingClient`
gives each model id its own configured transport behind that same call.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from llmlc.client.openai_compat import Completion, DEFAULT_TIMEOUT, OpenAICompatClient
from llmlc.config import settings


class NotConfigured(RuntimeError):
    """No model endpoint is configured at all."""


class ModelNotListed(RuntimeError):
    """A model was asked for that the custom list does not describe.

    Distinct from `NotConfigured` on purpose. An aggregator takes any model id it
    recognises, so a typo surfaces as an HTTP error from the gateway; a custom
    list is closed, and the honest answer is to say which models it holds rather
    than to send a request nobody has an endpoint for.
    """


NOT_CONFIGURED_MESSAGE = (
    "No model endpoint is configured.\n"
    "  Set CUSTOM_MODEL_LIST_PATH in .env to a JSON file listing your models,\n"
    "  one entry per model with its own endpoint and key -- see .models.json.example.\n"
    "  (AGGREGATOR_BASE_URL + AGGREGATOR_ADMIN_API_KEY also work, for a single\n"
    "  gateway that serves every model id.)"
)

REQUIRED_FIELDS = ("model_id", "api_key", "v1_endpoint")


@dataclass(frozen=True)
class ModelEntry:
    """One model, with everything needed to call it.

    `model_id` is the identity: it is what goes in the request body, what
    `--engine` names, and what is stored on every result row. `model_title` is
    for human display only and never reaches a payload or the database, so
    renaming it cannot strand existing measurements.
    """

    model_id: str
    api_key: str
    v1_endpoint: str
    model_title: str = ""

    @property
    def title(self) -> str:
        return self.model_title or self.model_id


def _fail(path: Path, detail: str) -> None:
    raise NotConfigured(f"CUSTOM_MODEL_LIST_PATH ({path}): {detail}")


def load_custom_models(path: str | Path) -> list[ModelEntry]:
    """Parse the custom model list, or say precisely what is wrong with it.

    Every failure here is a user editing a JSON file by hand, so each one names
    the file and the offending entry. A misconfigured list that silently yields
    zero models would present as "not configured", sending the reader to the
    wrong problem.
    """
    p = Path(path).expanduser()
    if not p.exists():
        # The container mounts ./data and nothing else, so a path outside it
        # resolves on the host and vanishes in Docker -- a failure that reads as
        # "my file is right there" unless the message says so.
        _fail(p, "file not found. Copy .models.json.example to data/models.json; "
                 "a path outside ./data is not visible inside the container")
    try:
        body = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _fail(p, f"could not be read as JSON -- {e}")

    if isinstance(body, dict):
        rows = body.get("models")
        if rows is None:
            _fail(p, 'the top-level object needs a "models" key holding the list')
    elif isinstance(body, list):
        # Tolerated: a bare array says the same thing with less ceremony.
        rows = body
    else:
        _fail(p, "expected a JSON object with a \"models\" list")

    if not isinstance(rows, list) or not rows:
        _fail(p, '"models" must be a non-empty list')

    entries: list[ModelEntry] = []
    seen: dict[str, int] = {}
    for i, row in enumerate(rows):
        where = f'entry {i + 1}'
        if not isinstance(row, dict):
            _fail(p, f"{where} is not an object")
        missing = [f for f in REQUIRED_FIELDS if not str(row.get(f) or "").strip()]
        if missing:
            _fail(p, f"{where} is missing {', '.join(missing)}")
        model_id = str(row["model_id"]).strip()
        if model_id in seen:
            _fail(p, f"{where} repeats model_id {model_id!r}, already used by "
                     f"entry {seen[model_id] + 1}")
        seen[model_id] = i
        entries.append(ModelEntry(
            model_id=model_id,
            api_key=str(row["api_key"]).strip(),
            v1_endpoint=str(row["v1_endpoint"]).strip(),
            model_title=str(row.get("model_title") or "").strip(),
        ))
    return entries


def custom_models() -> list[ModelEntry]:
    """The configured custom list, or an empty list when the variable is unset.

    An unset variable is not configured; a *set* variable pointing at a broken
    file is an error, and raises.
    """
    path = (settings.custom_model_list_path or "").strip()
    return load_custom_models(path) if path else []


def aggregator_configured() -> bool:
    return bool(settings.aggregator_base_url and settings.aggregator_admin_api_key)


class RoutingClient:
    """One `complete()` over many endpoints.

    Deliberately the same shape as `OpenAICompatClient` rather than a wrapper the
    pipeline has to know about. Each model id gets its own underlying client, so
    per-model state that matters -- chiefly which models reject
    `reasoning_effort` -- stays attached to the model it was learned about.
    """

    def __init__(self, entries: list[ModelEntry], *, timeout: int = DEFAULT_TIMEOUT,
                 retries: int = 4, reasoning_effort: str | None = "none") -> None:
        self._entries = {e.model_id: e for e in entries}
        self._by_title = {e.title: e for e in entries if e.title != e.model_id}
        self._opts = dict(timeout=timeout, retries=retries,
                          reasoning_effort=reasoning_effort)
        self._clients: dict[str, OpenAICompatClient] = {}

    @property
    def model_ids(self) -> list[str]:
        return sorted(self._entries)

    def entry_for(self, model: str) -> ModelEntry:
        if model in self._entries:
            return self._entries[model]
        if model in self._by_title:
            # A title resolves too, so a user who pastes the name they see in the
            # UI gets a measurement rather than a lecture about identifiers.
            return self._by_title[model]
        raise ModelNotListed(
            f"Model {model!r} is not in the custom model list. It holds: "
            f"{', '.join(self.model_ids)}. Add it to the file named by "
            f"CUSTOM_MODEL_LIST_PATH, or pick one of those.")

    def client_for(self, model: str) -> OpenAICompatClient:
        entry = self.entry_for(model)
        if entry.model_id not in self._clients:
            self._clients[entry.model_id] = OpenAICompatClient(
                entry.v1_endpoint, entry.api_key, **self._opts)
        return self._clients[entry.model_id]

    def complete(self, model: str, prompt: str, **kw) -> Completion:
        entry = self.entry_for(model)
        # Always send the id, never the title: the title is a label for people.
        # `**kw` carries `system` through unchanged -- the routing client must
        # not become a place where a message gets dropped.
        return self.client_for(model).complete(entry.model_id, prompt, **kw)


def build_client(**kw):
    """The client every caller should use. Custom list first, aggregator second.

    Raises `NotConfigured` when neither route is set up, with a message that
    names both. Callers print it and exit; they do not need to know which source
    was chosen, which is the point of resolving it in one place.
    """
    entries = custom_models()
    if entries:
        return RoutingClient(entries, **kw)
    if aggregator_configured():
        return OpenAICompatClient(settings.aggregator_base_url,
                                  settings.aggregator_admin_api_key, **kw)
    raise NotConfigured(NOT_CONFIGURED_MESSAGE)


def is_configured() -> bool:
    """Whether a scan could run at all. Never raises: a broken custom list is
    not configured *for this question*, and the detail belongs to the caller
    that actually tries to build a client."""
    try:
        if custom_models():
            return True
    except NotConfigured:
        return False
    return aggregator_configured()


def check_models(models: list[str]) -> list[str]:
    """Which of these models the current configuration cannot reach.

    Only a custom list can answer this: an aggregator accepts any id and reports
    its own unknowns at call time. Checking up front matters because the defaults
    -- the judge and the back-translator panel -- are this project's own model
    ids, and a public user's list will not contain them. Discovering that after
    the first paid call, one language at a time, is the bad version.
    """
    try:
        entries = custom_models()
    except NotConfigured:
        return []
    if not entries:
        return []
    known = {e.model_id for e in entries} | {e.title for e in entries}
    return [m for m in dict.fromkeys(models) if m and m not in known]
