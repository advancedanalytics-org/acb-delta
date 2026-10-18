"""Runtime settings. Every value comes from env vars so Phase 1 → Phase 2 needs no code change."""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = ""
    postgres_user: str = "acb"
    postgres_password: str = "acb"
    postgres_db: str = "acb_delta"
    postgres_port: int = 5432

    minio_root_user: str = ""
    minio_root_password: str = ""

    @model_validator(mode="after")
    def assemble_database_url(self) -> "Settings":
        if not self.database_url or "acb:acb@localhost" in self.database_url:
            self.database_url = (
                f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
                f"@127.0.0.1:{self.postgres_port}/{self.postgres_db}"
            )
        if self.minio_root_user and (not self.s3_access_key or self.s3_access_key == "acb"):
            self.s3_access_key = self.minio_root_user
        if self.minio_root_password and (not self.s3_secret_key or self.s3_secret_key == "acb"):
            self.s3_secret_key = self.minio_root_password
        return self

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

    # Optional LLM for impact judgement (gemini or openai). Empty = rule-based comparison only.
    llm_type: str = "openai"
    gemini_api_key: str = ""
    google_api_key: str = ""
    openai_base_url: str = ""
    openai_api_key: str = ""
    llm_model: str = ""
    # JSON merged into every chat request, e.g. {"reasoning": {"enabled": false}} on OpenRouter.
    llm_extra_body: str = ""
    llm_concurrency: int = 4
    # Parallel agent POST /draft calls while building one RIA review package.
    review_draft_concurrency: int = 4
    # Build the review package as soon as an analyze job finishes (on in docker-compose).
    review_auto_start: bool = False
    # Reuse identical LLM answers across runs (table llm_cache).
    llm_cache_enabled: bool = True
    # FalkorDB knowledge graph (redis://host:6379). Empty = Engine 1 runs without graph expansion.
    falkordb_url: str = ""
    falkordb_graph: str = "ria"
    # Engine 2 NLP span detection (underthesea word segmentation + POS, difflib alignment).
    span_detection_enabled: bool = True

    # Optional TypeSafe Jev decisions model (OpenRouter Decisions API): the Engine 1 reranker
    # when RERANK_BACKEND=jev, and the independent verifier of Engine 3. Empty = not used.
    jev_base_url: str = ""
    jev_model: str = ""
    jev_api_key: str = ""

    # Reranker backend: "jev" (JEV_* above) or "rerank" (Cohere/Jina-style POST {base}/rerank).
    # Not configured = Engine 1 keeps its lexical/dense relevance gate.
    rerank_backend: str = "rerank"
    rerank_base_url: str = ""
    rerank_model: str = ""
    rerank_api_key: str = ""
    rerank_concurrency: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
