"""PDF legal document chunking with PyMuPDF.

Extracts text preserving page numbers and line-level bounding boxes (bboxes).
Chunks documents hierarchically according to Vietnamese legal structure:
Phần / Chương / Mục / Điều / Khoản / Điểm.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

import pymupdf


@dataclass
class PDFChunk:
    chunk_id: str
    doc_id: str
    doc_type: str
    page: int
    bbox: list[list[float]]
    text: str
    article_path: str
    issuer: str | None = None
    effective_date: str | None = None
    chunk_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentMetadata:
    doc_id: str | None = None
    code: str | None = None
    title: str | None = None
    issuer: str | None = None
    effective_date: str | None = None
    version: str | None = None
    page_count: int = 0


RE_FOOTER_PATTERNS = [
    re.compile(r"Văn bản giả lập", re.IGNORECASE),
    re.compile(r"^Trang\s+\d+(\/\d+)?$", re.IGNORECASE),
]

RE_CHAPTER = re.compile(
    r"^(?:CHƯƠNG|Chương)\s+([IVXLCDM\d]+)[\.:\s\-]*(.*)$",
    re.IGNORECASE,
)
RE_SECTION = re.compile(
    r"^(?:MỤC|Mục)\s+(\d+|[IVXLCDM]+)[\.:\s\-]*(.*)$",
    re.IGNORECASE,
)
RE_ARTICLE = re.compile(
    r"^(?:ĐIỀU|Điều)\s+(\d+)[\.:\s\-]*(.*)$",
    re.IGNORECASE,
)
RE_CLAUSE = re.compile(r"^(\d+)\.\s+(.*)$")
RE_POINT = re.compile(r"^([a-zđ])\)\s+(.*)$", re.IGNORECASE)


def extract_metadata(doc: pymupdf.Document, default_doc_id: str | None = None) -> DocumentMetadata:
    """Extract metadata (code, title, issuer, effective date) from document text."""
    meta = DocumentMetadata(doc_id=default_doc_id, page_count=len(doc))
    if len(doc) == 0:
        return meta

    full_first_page_text = doc[0].get_text()

    # Match document code (support Vietnamese letters like Đ in QĐ-CV-01 and symbols)
    code_match = re.search(r"Số(?:\s*hiệu)?[:\s]+([a-zA-Z0-9\/\-\_\.ĐđÀ-ỹ]+)", full_first_page_text)
    if code_match:
        meta.code = code_match.group(1).strip()
        if not meta.doc_id:
            meta.doc_id = re.sub(r"[^a-zA-Z0-9_\-]+", "-", meta.code.lower()).strip("-")

    # Match version
    ver_match = re.search(r"Phiên bản\s*[:\s]*([0-9\.]+)", full_first_page_text)
    if ver_match:
        meta.version = ver_match.group(1).strip()

    # Match effective date
    date_match = re.search(r"Hiệu lực từ\s*[:\s]*([0-9\/]+)", full_first_page_text)
    if date_match:
        meta.effective_date = date_match.group(1).strip()
    else:
        # Check standard Vietnamese date: ngày DD tháng MM năm YYYY
        v_date = re.search(
            r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", full_first_page_text
        )
        if v_date:
            d, m, y = v_date.groups()
            meta.effective_date = f"{int(d):02d}/{int(m):02d}/{y}"

    # Match title and issuer from blocks on first page
    blocks = doc[0].get_text("dict").get("blocks", [])
    for b in blocks:
        if "lines" not in b:
            continue
        text = " ".join(
            "".join(s["text"] for s in line["spans"]).strip() for line in b["lines"]
        ).strip()
        if not text:
            continue
        if ("NGÂN HÀNG" in text.upper() or "NHNN" in text.upper()) and not meta.issuer:
            meta.issuer = text
        elif (
            any(kw in text.upper() for kw in ["QUY ĐỊNH", "THÔNG TƯ", "QUYẾT ĐỊNH"])
            and not meta.title
        ):
            meta.title = text

    return meta


def chunk_pdf(
    source: str | Path | bytes | BinaryIO,
    doc_id: str | None = None,
    doc_type: str = "internal",
    code: str | None = None,
    title: str | None = None,
    issuer: str | None = None,
    effective_date: str | None = None,
) -> tuple[DocumentMetadata, list[PDFChunk]]:
    """Parse a PDF document with PyMuPDF, extract legal chunks with bboxes, and return chunks."""
    if isinstance(source, (str, Path)):
        doc = pymupdf.open(str(source))
    elif isinstance(source, bytes):
        doc = pymupdf.open(stream=source, filetype="pdf")
    else:
        stream_bytes = source.read()
        doc = pymupdf.open(stream=stream_bytes, filetype="pdf")

    inferred_meta = extract_metadata(doc, default_doc_id=doc_id)
    if code:
        inferred_meta.code = code
    if title:
        inferred_meta.title = title
    if issuer:
        inferred_meta.issuer = issuer
    if effective_date:
        inferred_meta.effective_date = effective_date

    # Determine final doc_id
    if doc_id:
        final_doc_id = doc_id
    elif inferred_meta.code:
        final_doc_id = re.sub(r"[^a-zA-Z0-9_\-]+", "-", inferred_meta.code.lower()).strip("-")
    elif inferred_meta.doc_id:
        final_doc_id = inferred_meta.doc_id
    else:
        final_doc_id = "doc-unknown"

    inferred_meta.doc_id = final_doc_id
    final_issuer = inferred_meta.issuer
    final_effective_date = inferred_meta.effective_date

    chunks: list[PDFChunk] = []

    current_chapter: str | None = None
    current_section: str | None = None
    current_article_num: str | None = None
    current_article_heading: str | None = None
    current_clause_num: str | None = None
    current_point: str | None = None

    current_lines: list[dict[str, Any]] = []
    current_location = "Phần mở đầu"
    current_page = 1

    def flush(new_loc: str | None = None, new_page: int | None = None) -> None:
        nonlocal current_lines, current_location, current_page
        if not current_lines:
            if new_loc:
                current_location = new_loc
            if new_page:
                current_page = new_page
            return

        full_text = " ".join(item["text"] for item in current_lines).strip()
        all_bboxes = [item["bbox"] for item in current_lines]

        # Ignore banner / header-only text if it matches document title line
        is_doc_header = (
            "NGÂN HÀNG" in full_text
            and "Phiên bản" in full_text
            and current_location == "Phần mở đầu"
        )
        if full_text and not is_doc_header:
            chunk_num = len(chunks) + 1
            chunk = PDFChunk(
                chunk_id=f"{final_doc_id}_chunk_{chunk_num:03d}",
                doc_id=final_doc_id,
                doc_type=doc_type,
                page=current_page,
                bbox=all_bboxes,
                text=full_text,
                article_path=current_location,
                issuer=final_issuer,
                effective_date=final_effective_date,
                chunk_metadata={
                    "document_code": inferred_meta.code,
                    "document_title": inferred_meta.title,
                    "chapter": current_chapter,
                    "section": current_section,
                    "article_heading": current_article_heading,
                    "article_num": current_article_num,
                    "clause_num": current_clause_num,
                    "point": current_point,
                },
            )
            chunks.append(chunk)

        current_lines = []
        if new_loc:
            current_location = new_loc
        if new_page:
            current_page = new_page

    for page_idx, page in enumerate(doc):
        page_num = page_idx + 1
        blocks = page.get_text("dict").get("blocks", [])

        for b in blocks:
            if "lines" not in b:
                continue

            lines = b["lines"]
            block_text = " ".join(
                "".join(s["text"] for s in line["spans"]).strip() for line in lines
            ).strip()

            # Ignore footers
            if any(p.search(block_text) for p in RE_FOOTER_PATTERNS):
                continue

            # Check chapter header
            m_chap = RE_CHAPTER.match(block_text)
            if m_chap:
                flush(new_page=page_num)
                current_chapter = block_text
                current_section = None
                continue

            # Check section header
            m_sec = RE_SECTION.match(block_text)
            if m_sec:
                flush(new_page=page_num)
                current_section = block_text
                continue

            # Check article header
            m_art = RE_ARTICLE.match(block_text)
            if m_art:
                flush(new_page=page_num)
                current_article_num = m_art.group(1)
                current_article_heading = block_text
                current_clause_num = None
                current_point = None
                current_location = f"Điều {current_article_num}"
                continue

            # Process lines in block
            for line in lines:
                lt = "".join(s["text"] for s in line["spans"]).strip()
                if not lt:
                    continue
                lb = [round(v, 2) for v in line["bbox"]]

                # Check if line starts a clause
                m_clause = RE_CLAUSE.match(lt)
                if m_clause and current_article_num:
                    flush(new_page=page_num)
                    current_clause_num = m_clause.group(1)
                    current_point = None
                    current_location = f"Điều {current_article_num}, khoản {current_clause_num}"
                    current_lines.append({"text": lt, "bbox": lb, "page": page_num})
                    continue

                # Check if line starts a point
                m_point = RE_POINT.match(lt)
                if m_point and current_article_num and current_clause_num:
                    flush(new_page=page_num)
                    current_point = m_point.group(1).lower()
                    loc = (
                        f"Điều {current_article_num}, khoản {current_clause_num}, "
                        f"điểm {current_point}"
                    )
                    current_location = loc
                    current_lines.append({"text": lt, "bbox": lb, "page": page_num})
                    continue

                if not current_lines:
                    current_page = page_num
                current_lines.append({"text": lt, "bbox": lb, "page": page_num})

            # If inside an article without numbered clauses, flush paragraph
            if not current_clause_num and current_lines:
                flush(
                    new_loc=(
                        f"Điều {current_article_num}" if current_article_num else current_location
                    ),
                    new_page=page_num,
                )

    flush()
    doc.close()
    return inferred_meta, chunks
