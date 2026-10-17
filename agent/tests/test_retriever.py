import pytest

from agent import retriever
from agent.config import get_settings
from agent.schemas import Change


@pytest.mark.usefixtures("corpus")
def test_ranks_overlapping_passages_first():
    change = Change(clause="Điều 9", kind="amended", text="Thời hạn cho vay tiêu dùng 60 tháng")

    candidates = retriever.retrieve_candidates(change, k=5)

    assert [c.chunk_id for c in candidates] == ["doc-cv:1:1", "doc-cv:2:1"]
    assert candidates[0].location == "Điều 3. Thời hạn cho vay"
    assert retriever.retrieve_candidates(change, k=1) == candidates[:1]


def test_empty_corpus_path_returns_nothing(monkeypatch):
    monkeypatch.setenv("CORPUS_PATH", "")
    get_settings.cache_clear()

    assert retriever.retrieve_candidates(Change(clause="x", kind="added", text="y"), k=5) == []
    get_settings.cache_clear()
