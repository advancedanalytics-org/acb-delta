from urllib.parse import unquote

from fastapi import Response

from app.routers.documents import pdf_content_disposition


def test_vietnamese_doc_id_builds_a_latin1_safe_header():
    doc_id = "QUY ĐỊNH VỀ PHÂN LOẠI DỮ LIỆU_V1"
    header = pdf_content_disposition(doc_id)

    header.encode("latin-1")  # would raise for the raw Vietnamese name
    assert header.startswith("inline; filename=")
    utf8_part = header.split("filename*=UTF-8''", 1)[1]
    assert unquote(utf8_part) == f"{doc_id}.pdf"

    response = Response(
        b"%PDF", media_type="application/pdf", headers={"Content-Disposition": header}
    )
    assert response.headers["content-disposition"] == header


def test_ascii_doc_id_keeps_its_plain_filename():
    assert pdf_content_disposition("DOC-102").startswith('inline; filename="DOC-102.pdf";')


def test_fully_non_ascii_doc_id_falls_back_to_a_generic_name():
    assert 'filename="document.pdf"' in pdf_content_disposition("Đỗ")
