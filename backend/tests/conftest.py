"""Postgres-backed fixtures. Tests use a separate `<POSTGRES_DB>_test` database, never dev data.

URL: TEST_DATABASE_URL, else built from the repo-root .env (the compose Postgres on 127.0.0.1).
Tests that need it skip with a message when that database is unreachable.
"""

import os
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app import agent_client
from app.config import get_settings
from app.db import get_engine, get_sessionmaker
from app.main import create_app

ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


def _test_database_url() -> str | None:
    if url := os.environ.get("TEST_DATABASE_URL"):
        return url
    if not ROOT_ENV.exists():
        return None
    env = {}
    for line in ROOT_ENV.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.startswith("#"):
            env[key.strip()] = value.strip()
    user, password = env.get("POSTGRES_USER"), env.get("POSTGRES_PASSWORD")
    if not user or not password or password == "CHANGEME":
        return None
    port = env.get("POSTGRES_PORT", "5432")
    return f"postgresql+psycopg://{user}:{password}@127.0.0.1:{port}/{env['POSTGRES_DB']}_test"


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _test_database_url()
    if url is None:
        pytest.skip("No test database: set TEST_DATABASE_URL or create .env, then start Postgres")
    target = make_url(url)
    # Create the test database through the server's default database if it does not exist yet.
    admin = create_engine(
        target.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 3},
    )
    try:
        with admin.connect() as conn:
            found = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database}
            ).scalar()
            if not found:
                conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    except Exception as exc:
        pytest.skip(f"Postgres unreachable ({exc.__class__.__name__}); run ./scripts/run.sh up")
    finally:
        admin.dispose()
    return url


class FakeAgent:
    """Stands in for the agent service. Set `impacts` or `status_code` before creating a VBPL."""

    def __init__(self) -> None:
        self.impacts: list[dict] = []
        self.status_code = 200
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status_code != 200:
            return httpx.Response(self.status_code, text="agent exploded")
        return httpx.Response(200, json={"changes": [], "impacts": self.impacts})


@pytest.fixture
def agent(monkeypatch) -> FakeAgent:
    fake = FakeAgent()
    monkeypatch.setattr(
        agent_client,
        "http_client",
        lambda: httpx.Client(base_url="http://agent", transport=httpx.MockTransport(fake.handle)),
    )
    return fake


@pytest.fixture
def client(database_url, monkeypatch, agent):
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    with TestClient(create_app()) as test_client:  # runs lifespan: create tables, seed reviewers
        yield test_client
    with get_engine().begin() as conn:
        conn.execute(text("TRUNCATE vbpls, impacts, decisions CASCADE"))
    get_engine().dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


def agent_impact(**overrides) -> dict:
    """One impact as the agent's POST /invoke returns it."""
    impact = {
        "chunk_id": "doc-cv-01:3:1",
        "doc_id": "doc-cv-01",
        "location": "Điều 3. Thời hạn cho vay",
        "page": None,
        "bboxes": [],
        "affected_text": "1. Thời hạn cho vay tiêu dùng tối đa là 84 tháng.",
        "change_clause": "Thời hạn cho vay tiêu dùng không vượt quá 60 tháng.",
        "type": "conflict",
        "severity": "high",
        "reasoning": "Vượt mức trần 60 tháng.",
        "citation": "Khoản 2 Điều 9, Thông tư 31/2026/TT-NHNN",
        "suggested_text": "1. Thời hạn cho vay tiêu dùng tối đa là 60 tháng.",
    }
    return impact | overrides


VBPL = {
    "number": "31/2026/TT-NHNN",
    "title": "Thông tư quy định về hoạt động cho vay",
    "issuer": "Ngân hàng Nhà nước Việt Nam",
    "issuedDate": "2026-10-05",
    "effectiveDate": "2027-01-01",
    "summary": "Thay thế Thông tư 39/2016/TT-NHNN.",
    "text": "Điều 9. Thời hạn cho vay tiêu dùng không vượt quá 60 tháng.",
}


@pytest.fixture
def create_vbpl(client, agent):
    """POST a VBPL; the background analysis runs before the call returns (TestClient)."""

    def create(impacts: list[dict] | None = None) -> dict:
        agent.impacts = impacts if impacts is not None else [agent_impact()]
        response = client.post("/api/vbpls", json=VBPL)
        assert response.status_code == 202, response.text
        return response.json()

    return create
