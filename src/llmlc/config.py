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

    database_url: str = "postgresql+psycopg://llmlc:llmlc@localhost:5432/llmlc"

    def redacted(self) -> dict:
        d = self.model_dump()
        for k in list(d):
            if "key" in k and d[k]:
                d[k] = "[redacted]"
        return d


settings = Settings()
