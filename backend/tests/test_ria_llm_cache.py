from app.config import get_settings
from app.ria import llm


def test_cache_key_tracks_prompt_and_payload():
    a = llm.cache_key("judge_group", "prompt v1", "payload")
    assert a == llm.cache_key("judge_group", "prompt v1", "payload")
    assert a != llm.cache_key("judge_group", "prompt v2", "payload")
    assert a != llm.cache_key("judge_group", "prompt v1", "payload 2")
    assert a != llm.cache_key("applicability", "prompt v1", "payload")


def test_chat_json_cached_hit_miss_and_refresh(monkeypatch):
    store: dict[str, dict] = {}
    asked = []
    monkeypatch.setattr(get_settings(), "llm_cache_enabled", True)
    monkeypatch.setattr(llm, "_cache_get", lambda k: store.get(k))
    monkeypatch.setattr(llm, "_cache_put", lambda k, kind, system, r: store.__setitem__(k, r))
    monkeypatch.setattr(llm, "chat_json", lambda s, u: asked.append(u) or {"n": len(asked)})

    assert llm.chat_json_cached("k", "sys", "u") == ({"n": 1}, False)
    assert llm.chat_json_cached("k", "sys", "u") == ({"n": 1}, True)
    assert llm.chat_json_cached("k", "sys", "u", refresh=True) == ({"n": 2}, False)
    assert llm.chat_json_cached("k", "sys", "u") == ({"n": 2}, True)
    assert len(asked) == 2


def test_cache_failure_falls_back_to_llm(monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_cache_enabled", True)

    def broken(*a):
        raise RuntimeError("db down")

    monkeypatch.setattr(llm, "_cache_get", broken)
    monkeypatch.setattr(llm, "_cache_put", broken)
    monkeypatch.setattr(llm, "chat_json", lambda s, u: {"ok": True})
    assert llm.chat_json_cached("k", "sys", "u") == ({"ok": True}, False)
