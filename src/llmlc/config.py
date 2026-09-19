"""Runtime configuration. Secrets come from the user's own .env and are never persisted."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    scheme: str = "default"
    hardware_profile: str = "auto"

    aggregator_base_url: str | None = None
    aggregator_admin_api_key: str | None = None
    aggregator_model_list_url: str | None = None

    judge_model: str = "openai-gpt-4o-mini"
    bt_remote_model: str | None = None

    database_url: str = "sqlite+pysqlite:///data/llmlc.db"

    #: Who may start a scan over HTTP. A scan spends the user's own API budget,
    #: so the endpoint that starts one is gated rather than merely present.
    #:
    #: - ``off``       -- no trigger at all; scans stay a CLI action
    #: - ``loopback``  -- only requests whose peer address is 127.0.0.1 / ::1
    #: - ``any``       -- any client that can reach the port
    #:
    #: ``loopback`` is the default and is the right setting when uvicorn runs on
    #: the host. In Docker the peer address is the bridge gateway, never
    #: loopback, so a containerised UI needs ``any`` *and* a published port bound
    #: to 127.0.0.1 -- there the port binding is the control, and compose does
    #: that by default. The address is the socket peer; no forwarding header is
    #: trusted, because any client can send one.
    scan_trigger: str = "loopback"

    #: Hard ceiling on a scan started from the browser, whatever it asks for.
    #: The CLI has no ceiling: someone typing a command is already deliberate.
    scan_trigger_max_calls: int = 2000

    def redacted(self) -> dict:
        d = self.model_dump()
        for k in list(d):
            if "key" in k and d[k]:
                d[k] = "[redacted]"
        return d


settings = Settings()
