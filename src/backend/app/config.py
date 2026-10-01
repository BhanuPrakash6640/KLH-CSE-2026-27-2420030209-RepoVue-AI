"""Central configuration. Everything is env-driven so the same image runs
locally, in CI and in production without code changes."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- app ---
    ENV: Literal["development", "staging", "production"] = "development"
    LOG_LEVEL: str = "INFO"
    API_PREFIX: str = "/api/v1"
    API_KEYS: str = "dev-local-key"

    # --- database ---
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/repovue"
    DB_SSL: bool = False
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10

    # --- llm ---
    GEMINI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    LLM_PROVIDER: Literal["gemini", "anthropic"] = "gemini"
    LLM_MODEL: str = "gemini-2.5-flash"
    LLM_FAST_MODEL: str = "gemini-2.5-flash"
    LLM_MAX_TOKENS: int = 8000
    LLM_MAX_CONCURRENCY: int = 6

    # --- embeddings ---
    EMBEDDING_PROVIDER: Literal["voyage", "openai", "hash"] = "hash"
    EMBEDDING_MODEL: str = "voyage-code-3"
    EMBEDDING_DIM: int = 1024
    VOYAGE_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # --- github ---
    GITHUB_TOKEN: str = ""
    GITHUB_APP_ID: str = ""
    GITHUB_APP_PRIVATE_KEY: str = ""
    GITHUB_WEBHOOK_SECRET: str = ""
    GITHUB_BOT_NAME: str = "repovue[bot]"
    GITHUB_BOT_EMAIL: str = "repovue@users.noreply.github.com"

    # --- workspace ---
    WORKSPACE_DIR: str = "repovue-workspace"
    MAX_REPO_MB: int = 300
    MAX_FILE_KB: int = 400
    MAX_FILES_PER_ANALYSIS: int = 4000
    CLONE_TIMEOUT_SEC: int = 300

    # --- sandbox ---
    VALIDATION_ENABLED: bool = True
    SANDBOX_MEMORY_LIMIT: str = "2g"
    SANDBOX_CPU_LIMIT: float = 2.0
    SANDBOX_TIMEOUT_SEC: int = 900
    SANDBOX_NETWORK: str = "none"
    BENCHMARK_RUNS: int = 3
    PERF_REGRESSION_TOLERANCE: float = 0.05

    # --- jira ---
    JIRA_ENABLED: bool = False
    JIRA_BASE_URL: str = ""
    JIRA_EMAIL: str = ""
    JIRA_API_TOKEN: str = ""
    JIRA_PROJECT_KEY: str = "REPO"
    JIRA_ISSUE_TYPE: str = "Bug"
    JIRA_MIN_SEVERITY: str = "high"

    # --- worker ---
    RUN_WORKER_IN_API: bool = True
    WORKER_CONCURRENCY: int = 2
    WORKER_POLL_INTERVAL: int = 3

    api_key_set: set[str] = Field(default_factory=set, exclude=True)

    @field_validator("DATABASE_URL")
    @classmethod
    def _force_async_driver(cls, v: str) -> str:
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql+asyncpg://", 1)
        elif v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        # asyncpg rejects libpq-style query params that Neon hands you
        for junk in ("?sslmode=require", "&sslmode=require", "?channel_binding=require"):
            v = v.replace(junk, "")
        return v

    def model_post_init(self, __context) -> None:
        self.api_key_set = {k.strip() for k in self.API_KEYS.split(",") if k.strip()}

    @property
    def is_prod(self) -> bool:
        return self.ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
