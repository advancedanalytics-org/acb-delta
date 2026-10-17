"""Runtime settings. Every value comes from env vars so Phase 1 → Phase 2 needs no code change."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # OpenAI-compatible LLM endpoint (vLLM / LiteLLM in Phase 1, GreenNode MaaS in Phase 2).
    # Unused by the stub nodes; TAI-01 reads these when it adds LLM calls.
    openai_base_url: str = ""
    openai_api_key: str = ""
    llm_model: str = ""

    # Langfuse Cloud. Tracing is on only when both keys are set.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
