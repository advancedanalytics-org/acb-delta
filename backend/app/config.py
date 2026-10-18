"""Runtime settings. Every value comes from env vars so Phase 1 → Phase 2 needs no code change."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://acb:acb@localhost:5432/acb_delta"
    agent_url: str = "http://localhost:8080"
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "documents"
    s3_access_key: str = "acb"
    s3_secret_key: str = "acb"
    embedding_base_url: str = ""
    embedding_model: str = ""
    embedding_api_key: str = ""
    embedding_dim: int = 1024
    storage_local_dir: str = "/tmp/acb_delta/storage"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Where uploaded originals live: "s3" (MinIO / vStorage) or "local" (dev and tests).
    storage_backend: str = "local"
    max_upload_mb: int = 50
    # Background workers for parse / analyze jobs (in-process; no queue in Phase 1).
    job_workers: int = 2

    # Optional OpenAI-compatible LLM for impact judgement. Empty = rule-based comparison only.
    openai_base_url: str = ""
    openai_api_key: str = ""
    llm_model: str = ""
    # JSON merged into every chat request, e.g. {"reasoning": {"enabled": false}} on OpenRouter.
    llm_extra_body: str = ""
    llm_concurrency: int = 4


@lru_cache
def get_settings() -> Settings:
    return Settings()
