"""Runtime settings. Every value comes from env vars so Phase 1 → Phase 2 needs no code change."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://acb:acb@localhost:5432/acb_delta"
    agent_url: str = "http://localhost:8080"
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "documents"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
