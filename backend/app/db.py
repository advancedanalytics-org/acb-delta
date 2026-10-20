"""Database engine shared by all routers."""

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    # Generous pool size so background indexing does not starve web API requests.
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        pool_size=25,
        max_overflow=25,
        pool_timeout=30,
        connect_args={"connect_timeout": 5},
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


@lru_cache
def get_sessionmaker():
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    session_factory = get_sessionmaker()
    with session_factory() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]
