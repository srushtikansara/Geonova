"""Application settings, loaded from environment variables / .env."""
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_name: str = "GEONOVA API"
    app_version: str = "0.1.0"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    database_url: str = ""  # secret-bearing: never returned by any endpoint
    test_database_url: str = ""  # used only by the test-suite; its database name must end with "_test"
    data_dir: str = "data"  # raw/ and processed/ live here (relative paths resolve against backend/)
    allow_synthetic_persist: bool = False  # keep OFF: synthetic fixtures must not enter the real database
    jobs_run_inline: bool = False  # tests only: run jobs synchronously instead of in the worker thread
    api_writes_enabled: bool | None = None  # None -> enabled only when APP_ENV=development

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


def writes_enabled(s: "Settings") -> bool:
    return s.api_writes_enabled if s.api_writes_enabled is not None else s.app_env.lower() == "development"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.app_env.lower() == "production" and "*" in s.cors_origins:
        raise ValueError("Wildcard CORS is not allowed when APP_ENV=production")
    return s
