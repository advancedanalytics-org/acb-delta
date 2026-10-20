from app.ria import graph


def test_legal_refs_numbers_and_titles():
    refs = dict(
        graph.legal_refs(
            "Căn cứ Luật Phòng, chống rửa tiền số 14/2022/QH15 ngày 15 tháng 11 năm 2022; "
            "thực hiện theo Nghị định số 13/2023/NĐ-CP và Luật này."
        )
    )
    assert refs["no:14/2022/QH15"] == "14/2022/QH15"
    assert "no:13/2023/NĐ-CP" in refs
    assert "title:luật phòng chống rửa tiền" in refs
    assert not any(k.startswith("title:luật này") for k in refs)


def test_regulation_title_matches_citation_title():
    cited = dict(graph.legal_refs("Tuân thủ Luật Bảo vệ dữ liệu cá nhân và các văn bản hướng dẫn."))
    assert graph.title_key("LUẬT", "Bảo vệ dữ liệu cá nhân") in cited


def test_self_references_in_internal_documents():
    nums = {"5", "5.2", "5.5", "5.6", "5.6.a", "10"}
    assert graph.self_references("5.6", "Ngoài kỳ hạn tại khoản 2 và khoản 5 Điều này", nums) == [
        "5.2",
        "5.5",
    ]
    assert graph.self_references("12.2", "thời hạn tại Điều 5.", nums) == ["5"]
    assert graph.self_references("9.1", "theo điểm a khoản 6 Điều 5 Quy định này", nums) == [
        "5.6.a"
    ]
    assert graph.self_references("3.1", "theo Điều 22 của Luật này", nums) == []


def _link(doc: str, relation: str, via: str) -> dict:
    return {"document_id": doc, "clause_id": None, "relation": relation, "via": via}


def test_common_legal_basis_is_dropped_rare_one_kept():
    tctd = "Luật Các tổ chức tín dụng"
    links = [_link(f"DOC-{i}", "shared_legal_basis", tctd) for i in range(23)]
    links += [
        _link("DOC-0", "cites_regulation", "88/2026/TT-NHNN"),
        _link("DOC-1", "shared_legal_basis", "Nghị định 13/2023/NĐ-CP"),
    ]
    kept, common = graph.drop_common_bases(links, n_documents=37, max_share=0.2)
    assert common == [tctd]
    assert {(lk["document_id"], lk["relation"]) for lk in kept} == {
        ("DOC-0", "cites_regulation"),
        ("DOC-1", "shared_legal_basis"),
    }


def test_small_corpus_keeps_its_shared_legal_basis():
    # Two documents in scope: one citing the law is not "most of the corpus".
    links = [_link("DOC-102", "shared_legal_basis", "Luật Các tổ chức tín dụng")]
    kept, common = graph.drop_common_bases(links, n_documents=2, max_share=0.2)
    assert kept == links and common == []
