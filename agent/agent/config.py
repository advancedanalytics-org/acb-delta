"""Runtime settings. Every value comes from env vars so Phase 1 → Phase 2 needs no code change."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # LLM Provider: "gemini" (langchain_google_genai) or "openai" (langchain_openai)
    llm_type: str = "openai"

    # OpenAI-compatible LLM endpoint (any provider now, GreenNode MaaS later). Read only in llm.py.
    openai_base_url: str = ""
    openai_api_key: str = ""
    llm_model: str = ""
    # "json_schema" or "function_calling", for providers that reject JSON-schema output.
    llm_structured_method: str = "json_schema"

    # Gemini settings (used when llm_type == "gemini")
    gemini_api_key: str = ""
    google_api_key: str = ""

    # Skeleton retriever corpus (demo-documents.json format). Empty = no candidates.
    corpus_path: str = ""
    # Caps LLM calls per run: changes kept from the VBPL, candidates judged per change.
    max_changes: int = 10
    retrieve_k: int = 5

    # Langfuse Cloud. Tracing is on only when both keys are set.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
