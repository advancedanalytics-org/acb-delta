"""Dynamic PDF generator using PyMuPDF for internal documents and regulations."""

from __future__ import annotations

import html
import logging
import re
from pathlib import Path
from typing import Any

import pymupdf

logger = logging.getLogger(__name__)


def markdown_to_html(md_text: str) -> str:
    """Convert a markdown legal document into clean HTML for PyMuPDF Story rendering."""
    lines = md_text.splitlines()
    body_parts: list[str] = []
    in_table = False
    table_rows: list[list[str]] = []

    for line in lines:
        raw_line = line.strip()
        if not raw_line or raw_line.startswith("---"):
            if in_table and table_rows:
                body_parts.append(
                    '<table style="width:100%; border-collapse:collapse; margin:8pt 0;">'
                )
                for r in table_rows:
                    cells = "".join(
                        f'<td style="padding:4pt; border:1px solid #cbd5e1;">{c}</td>' for c in r
                    )
                    body_parts.append(f"<tr>{cells}</tr>")
                body_parts.append("</table>")
                in_table = False
                table_rows = []
            continue

        if raw_line.startswith(">"):
            esc = html.escape(raw_line[1:].strip())
            body_parts.append(
                '<p style="font-size:8.5pt; color:#64748b; font-style:italic; '
                f'background:#f1f5f9; padding:6pt; border-left:3px solid #94a3b8; margin:6pt 0;">'
                f"{esc}</p>"
            )
            continue

        if raw_line.startswith("|"):
            cells = [c.strip() for c in raw_line.split("|")[1:-1]]
            if all(set(c).issubset({"-", ":", " "}) for c in cells if c):
                continue
            formatted_cells = []
            for c in cells:
                ch = html.escape(c)
                ch = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", ch)
                ch = re.sub(r"\*(.+?)\*", r"<i>\1</i>", ch)
                formatted_cells.append(ch)
            if not in_table:
                in_table = True
                table_rows = []
            table_rows.append(formatted_cells)
            continue

        if in_table and table_rows:
            body_parts.append('<table style="width:100%; border-collapse:collapse; margin:8pt 0;">')
            for r in table_rows:
                cells = "".join(
                    f'<td style="padding:4pt; border:1px solid #cbd5e1;">{c}</td>' for c in r
                )
                body_parts.append(f"<tr>{cells}</tr>")
            body_parts.append("</table>")
            in_table = False
            table_rows = []

        if raw_line.startswith("# "):
            h1 = html.escape(raw_line[2:].strip())
            body_parts.append(
                f'<h1 style="font-size:15pt; font-weight:bold; text-align:center; '
                f'margin:16pt 0 6pt 0; color:#0f172a;">{h1}</h1>'
            )
        elif raw_line.startswith("## "):
            h2 = html.escape(raw_line[3:].strip())
            body_parts.append(
                f'<h2 style="font-size:12.5pt; font-weight:bold; margin:12pt 0 4pt 0; '
                f'color:#1e293b;">{h2}</h2>'
            )
        elif raw_line.startswith("### "):
            h3 = html.escape(raw_line[4:].strip())
            body_parts.append(
                f'<h3 style="font-size:11pt; font-weight:bold; margin:10pt 0 3pt 0; '
                f'color:#334155;">{h3}</h3>'
            )
        else:
            lh = html.escape(raw_line)
            lh = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", lh)
            lh = re.sub(r"\*(.+?)\*", r"<i>\1</i>", lh)
            body_parts.append(
                f'<p style="margin:0 0 6pt 0; font-size:10pt; line-height:1.45; '
                f'color:#1e293b;">{lh}</p>'
            )

    if in_table and table_rows:
        body_parts.append('<table style="width:100%; border-collapse:collapse; margin:8pt 0;">')
        for r in table_rows:
            cells = "".join(
                f'<td style="padding:4pt; border:1px solid #cbd5e1;">{c}</td>' for c in r
            )
            body_parts.append(f"<tr>{cells}</tr>")
        body_parts.append("</table>")

    return "<body>" + "".join(body_parts) + "</body>"


def clauses_to_html(
    doc_id: str,
    title: str,
    clauses: list[dict[str, Any]],
    owner: str | None = None,
    version: str | None = None,
    effective_date: str | None = None,
) -> str:
    """Format a list of database clauses into structured HTML."""
    dept = html.escape(owner or "Nội bộ")
    parts: list[str] = [
        '<div style="text-align:center; margin-bottom:16pt;">',
        f'<p style="font-size:9pt; color:#64748b; margin:0;">NGÂN HÀNG ACB · {dept}</p>',
        f'<h1 style="font-size:15pt; font-weight:bold; margin:8pt 0 4pt 0; color:#0f172a;">'
        f"{html.escape(title)}</h1>",
        f'<p style="font-size:9pt; color:#64748b; margin:0;">Mã tài liệu: {html.escape(doc_id)}'
        f"{f' · Phiên bản: {html.escape(version)}' if version else ''}"
        f"{f' · Hiệu lực từ: {html.escape(effective_date)}' if effective_date else ''}</p>",
        "</div>",
        '<hr style="border:none; border-top:1px solid #e2e8f0; margin:12pt 0;"/>',
    ]

    for c in clauses:
        level = c.get("level") or ""
        heading = c.get("heading")
        text = c.get("text", "")
        num = c.get("numbering", "")

        if level == "chapter":
            ch_text = html.escape(heading or text)
            parts.append(
                f'<h2 style="font-size:13pt; font-weight:bold; text-align:center; '
                f'margin:14pt 0 6pt 0; color:#0f172a;">{ch_text}</h2>'
            )
        elif level == "article":
            label = heading or f"Điều {num}. {text.splitlines()[0]}"
            parts.append(
                f'<h3 style="font-size:11.5pt; font-weight:bold; margin:12pt 0 4pt 0; '
                f'color:#1e293b;">{html.escape(label)}</h3>'
            )
            rem = text.split("\n", 1)
            if len(rem) > 1 and rem[1].strip():
                rem_text = html.escape(rem[1].strip())
                parts.append(
                    f'<p style="margin:0 0 6pt 0; font-size:10pt; line-height:1.45; '
                    f'color:#334155;">{rem_text}</p>'
                )
        else:
            escaped_text = html.escape(text)
            parts.append(
                f'<p style="margin:0 0 6pt 0; font-size:10pt; line-height:1.45; '
                f'color:#334155;">{escaped_text}</p>'
            )

    return "<body>" + "".join(parts) + "</body>"


def render_html_to_pdf_bytes(
    html_content: str,
    doc_id: str = "DOC",
    title: str = "Văn bản",
) -> bytes:
    """Render HTML content into a multi-page PDF using PyMuPDF Story."""
    import tempfile

    css = "body { font-family: sans-serif; color: #1e293b; }"
    story = pymupdf.Story(html=html_content, user_css=css)
    mediabox = pymupdf.paper_rect("a4")
    content_box = mediabox + (54, 54, -54, -54)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        temp_path = tf.name

    try:
        writer = pymupdf.DocumentWriter(temp_path)
        more = True
        while more:
            dev = writer.begin_page(mediabox)
            more, _ = story.place(content_box)
            story.draw(dev)
            writer.end_page()
        writer.close()

        doc = pymupdf.open(temp_path)
        total_pages = doc.page_count
        for page in doc:
            clean_title = title[:45] + ("..." if len(title) > 45 else "")
            footer = f"{doc_id} · {clean_title}    Trang {page.number + 1}/{total_pages}"
            page.insert_text(
                (54, page.rect.height - 30),
                footer,
                fontsize=8,
                color=(0.4, 0.45, 0.53),
            )
        doc.saveIncr()
        doc.close()

        pdf_bytes = Path(temp_path).read_bytes()
    finally:
        Path(temp_path).unlink(missing_ok=True)

    return pdf_bytes


def generate_pdf_for_document(
    doc_id: str,
    title: str | None = None,
    content_md: str | None = None,
    clauses: list[dict[str, Any]] | None = None,
    owner: str | None = None,
    version: str | None = None,
    effective_date: str | None = None,
    save_paths: list[Path] | None = None,
) -> bytes:
    """Render PDF from markdown or clauses, saves to disk if requested, and returns bytes."""
    doc_title = title or doc_id

    if content_md and content_md.strip():
        html_str = markdown_to_html(content_md)
    elif clauses:
        html_str = clauses_to_html(
            doc_id=doc_id,
            title=doc_title,
            clauses=clauses,
            owner=owner,
            version=version,
            effective_date=effective_date,
        )
    else:
        doc_id_esc = html.escape(doc_id)
        doc_t_esc = html.escape(doc_title)
        html_str = f"<body><h1>{doc_t_esc}</h1><p>Mã tài liệu: {doc_id_esc}</p></body>"

    pdf_bytes = render_html_to_pdf_bytes(html_content=html_str, doc_id=doc_id, title=doc_title)

    if save_paths:
        for p in save_paths:
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(pdf_bytes)
                logger.info("Saved generated PDF to %s", p)
            except Exception as exc:
                logger.warning("Could not save PDF to %s: %s", p, exc)

    return pdf_bytes
