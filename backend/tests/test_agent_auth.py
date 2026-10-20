"""IAM bearer auth for an agent running on a GreenNode AgentBase Runtime."""

import httpx
import pytest

from app import agent_client
from app.config import get_settings


class FakeIam:
    """Stands in for the GreenNode IAM token endpoint; hands out tok-1, tok-2, ..."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def post(self, url, auth, data, timeout):
        self.calls.append({"url": url, "auth": auth, "data": data})
        request = httpx.Request("POST", url)
        token = f"tok-{len(self.calls)}"
        body = {"access_token": token, "expires_in": 3600}
        return httpx.Response(200, json=body, request=request)


@pytest.fixture
def iam(monkeypatch) -> FakeIam:
    fake = FakeIam()
    monkeypatch.setattr(agent_client.httpx, "post", fake.post)
    return fake


def _client(auth: httpx.Auth | None, handler) -> httpx.Client:
    return httpx.Client(base_url="http://agent", auth=auth, transport=httpx.MockTransport(handler))


def test_no_credentials_means_no_auth(monkeypatch):
    monkeypatch.delenv("AGENTBASE_CLIENT_ID", raising=False)
    monkeypatch.delenv("AGENTBASE_CLIENT_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        assert agent_client.agent_auth() is None
    finally:
        get_settings.cache_clear()


def test_credentials_enable_iam_auth(monkeypatch):
    monkeypatch.setenv("AGENTBASE_CLIENT_ID", "client")
    monkeypatch.setenv("AGENTBASE_CLIENT_SECRET", "secret")
    get_settings.cache_clear()
    try:
        auth = agent_client.agent_auth()
        assert isinstance(auth, agent_client.AgentBaseAuth)
        assert auth.token_url == get_settings().agentbase_token_url
    finally:
        get_settings.cache_clear()


def test_token_is_fetched_once_and_sent_as_bearer(iam):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["Authorization"])
        return httpx.Response(200, json={})

    auth = agent_client.AgentBaseAuth("client", "secret", "https://iam.example/token")
    with _client(auth, handler) as client:
        client.post("/invoke", json={})
        client.post("/draft", json={})

    assert seen == ["Bearer tok-1", "Bearer tok-1"]
    assert iam.calls == [
        {
            "url": "https://iam.example/token",
            "auth": ("client", "secret"),
            "data": {"grant_type": "client_credentials"},
        }
    ]


def test_401_refreshes_the_token_once(iam):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["Authorization"])
        return httpx.Response(401 if len(seen) == 1 else 200, json={})

    auth = agent_client.AgentBaseAuth("client", "secret", "https://iam.example/token")
    with _client(auth, handler) as client:
        response = client.post("/invoke", json={"vbpl_text": "x"})

    assert response.status_code == 200
    assert seen == ["Bearer tok-1", "Bearer tok-2"]


def test_expired_token_is_replaced(iam, monkeypatch):
    auth = agent_client.AgentBaseAuth("client", "secret", "https://iam.example/token")
    assert auth.token() == "tok-1"
    monkeypatch.setattr(agent_client.time, "monotonic", lambda: auth._expires_at + 1)
    assert auth.token() == "tok-2"
