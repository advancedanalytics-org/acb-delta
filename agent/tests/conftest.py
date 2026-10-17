import json

import pytest

from agent import llm, retriever
from agent.config import get_settings
from agent.schemas import Amendment, ChangeList, ImpactJudgement

CORPUS = {
    "documents": [
        {
            "id": "doc-cv",
            "articles": [
                {
                    "heading": "Điều 3. Thời hạn cho vay",
                    "paragraphs": ["Thời hạn cho vay tiêu dùng tối đa là 84 tháng."],
                },
                {
                    "heading": "Điều 4. Hạn mức",
                    "paragraphs": ["Hạn mức cho vay tín chấp tối đa là 500 triệu đồng."],
                },
            ],
        }
    ]
}


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(CORPUS, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("CORPUS_PATH", str(path))
    get_settings.cache_clear()
    retriever._load_corpus.cache_clear()
    yield path
    get_settings.cache_clear()


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace the LLM with canned replies keyed by output schema. Returns the call log."""
    replies = {
        ChangeList: {"changes": []},
        ImpactJudgement: lambda user: {
            # Only passages about loan terms ("thời hạn") are affected.
            "affected": "thời hạn" in user.lower().split("đoạn văn bản nội bộ")[1],
            "type": "conflict",
            "severity": "high",
            "reasoning": "Vượt mức trần mới.",
            "citation": "Khoản 2 Điều 9",
        },
        Amendment: {"suggested_text": "Thời hạn cho vay tiêu dùng tối đa là 60 tháng."},
    }
    calls: list[tuple[type, str]] = []

    def structured_call(schema, system, user):
        calls.append((schema, user))
        reply = replies[schema]
        return schema.model_validate(reply(user) if callable(reply) else reply)

    monkeypatch.setattr(llm, "structured_call", structured_call)
    return replies, calls
