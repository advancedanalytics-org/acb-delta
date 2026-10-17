"""Database engine shared by all routers."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine, text

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    # Short connect timeout so /health/ready reports an unreachable DB instead of hanging.
    return create_engine(
        get_settings().database_url, pool_pre_ping=True, connect_args={"connect_timeout": 3}
    )


def ping_database() -> None:
    """Raise if Postgres is unreachable or the pgvector extension is missing."""
    with get_engine().connect() as conn:
        # Bound only this probe; other queries on the shared engine keep the server default.
        conn.execute(text("SET LOCAL statement_timeout = 3000"))
        conn.execute(text("SELECT 1"))
        has_vector = conn.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        ).scalar()
        if not has_vector:
            raise RuntimeError("pgvector extension is not installed")
