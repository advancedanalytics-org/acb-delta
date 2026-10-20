import httpx
from fastapi.testclient import TestClient

from app import agent_client, routers
from app.main import create_app

client = TestClient(create_app())


def test_liveness():
    for path in ("/health", "/api/health"):
        assert client.get(path).json() == {"status": "ok"}


def test_readiness_reports_each_dependency(monkeypatch):
    monkeypatch.setattr(routers.health, "ping_database", lambda: None)
    monkeypatch.setattr(
        agent_client,
        "http_client",
        lambda: httpx.Client(
            base_url="http://agent",
            transport=httpx.MockTransport(lambda request: httpx.Response(503)),
        ),
    )

    response = client.get("/api/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["agent"].startswith("error")
