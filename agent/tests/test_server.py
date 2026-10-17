from fastapi.testclient import TestClient

from agent import server

client = TestClient(server.create_app())


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_invoke_returns_result_schema():
    response = client.post("/invoke", json={"vbpl_text": "Điều 1."})

    assert response.status_code == 200
    assert response.json() == {"changes": [], "impacts": []}


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
