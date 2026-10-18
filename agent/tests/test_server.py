import pytest
from fastapi.testclient import TestClient

from agent import llm, server
from agent.config import get_settings
from agent.schemas import ChangeList


def test_health():
    assert TestClient(server.create_app()).get("/health").json() == {"status": "ok"}


@pytest.mark.usefixtures("corpus")
def test_invoke_returns_typed_impacts(fake_llm):
    replies, _ = fake_llm
    replies[ChangeList] = {
        "changes": [{"clause": "Điều 9", "kind": "amended", "text": "Thời hạn cho vay 60 tháng."}]
    }

    response = TestClient(server.create_app()).post("/invoke", json={"vbpl_text": "Điều 9."})

    assert response.status_code == 200
    body = response.json()
    assert body["changes"] == replies[ChangeList]["changes"]
    assert set(body["impacts"][0]) == {
        "chunk_id", "doc_id", "location", "page", "bboxes", "affected_text", "change_clause",
        "type", "severity", "reasoning", "citation", "suggested_text",
    }  # fmt: skip


def test_invoke_without_llm_config_is_503(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.setenv("LLM_MODEL", "")
    get_settings.cache_clear()

    response = TestClient(server.create_app()).post("/invoke", json={"vbpl_text": "Điều 1."})

    assert response.status_code == 503
    assert "OPENAI_BASE_URL" in response.json()["detail"]
    get_settings.cache_clear()


def test_structured_call_requires_llm_settings(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    get_settings.cache_clear()

    with pytest.raises(llm.LLMNotConfiguredError):
        llm.structured_call(ChangeList, "system", "user")
    get_settings.cache_clear()


@pytest.mark.usefixtures("fake_llm")
def test_session_header_becomes_thread_id(monkeypatch):
    seen: dict = {}
    real_build_graph = server.build_graph

    def recording_build_graph():
        graph = real_build_graph()
        real_invoke = graph.invoke

        def invoke(state, config):
            seen.update(config["configurable"])
            return real_invoke(state, config=config)

        graph.invoke = invoke
        return graph

    monkeypatch.setattr(server, "build_graph", recording_build_graph)

    TestClient(server.create_app()).post(
        "/invoke",
        json={"vbpl_text": "Điều 1."},
        headers={
            "X-GreenNode-AgentBase-User-Id": "user-1",
            "X-GreenNode-AgentBase-Session-Id": "session-1",
        },
    )

    assert seen == {"thread_id": "session-1", "user_id": "user-1"}
