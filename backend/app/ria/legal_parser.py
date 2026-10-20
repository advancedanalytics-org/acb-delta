"""Structure-aware parsing of Vietnamese legal PDFs (design section 05).

PDF → lines with page + bbox → canonical text → Chương / Mục / Điều / Khoản / Điểm tree.
Every clause keeps char offsets into the canonical text, so `text[start:end] == clause.text`.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

import pymupdf

from app.ria.textutil import normalize

POINT_LETTERS = "abcdđeghiklmnopqrstuvxy"

# Browser "print to PDF" artefacts seen in the NHNN corpus, plus page counters.
_NOISE = [
    re.compile(r"^about:blank$"),
    re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}(\s*[AP]M)?$"),
    re.compile(r"^\d{1,3}\s*/\s*\d{1,3}$"),
    re.compile(r"^(Trang|Page)\s+\d+(\s*/\s*\d+)?$", re.IGNORECASE),
    re.compile(r"^https?://\S+$"),
]

RE_CHAPTER = re.compile(r"^Chương\s+([IVXLC]+|\d+)\b\.?\s*(.*)$", re.IGNORECASE)
RE_SECTION = re.compile(r"^Mục\s+(\d+|[IVXLC]+)\b\.?\s*(.*)$")
RE_ARTICLE = re.compile(r"^Điều\s+(\d+)\s*\.\s*(.*)$")
RE_CLAUSE = re.compile(r"^(\d{1,3})\.\s+(\S.*)$")
RE_POINT = re.compile(r"^([a-zđ])\)\s+(\S.*)$")
RE_APPENDIX = re.compile(r"^(PHỤ LỤC|Phụ lục)(\s+[IVXLC\d]+)?\s*$")
RE_CLOSING = re.compile(
    r"^(Nơi nhận\s*:|TM\.\s|KT\.\s|CHỦ TỊCH QUỐC HỘI$|(Luật|Nghị quyết) này (đã )?được Quốc hội)"
)

LEGAL_FORMS = (
    "VĂN BẢN HỢP NHẤT",
    "NGHỊ QUYẾT",
    "NGHỊ ĐỊNH",
    "THÔNG TƯ",
    "QUYẾT ĐỊNH",
    "PHÁP LỆNH",
    "CHỈ THỊ",
    "LUẬT",
)
RE_DOC_NUMBER = re.compile(r"\b(\d{1,4}/\d{4}/[A-ZĐ][A-ZĐ0-9]*(?:-[A-ZĐ0-9]+)*)")
RE_VN_DATE = re.compile(r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})")
RE_EFFECTIVE = re.compile(
    r"có hiệu lực(?:\s+thi hành)?(?:\s+kể)?\s+từ\s+"
    r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})",
    re.IGNORECASE,
)
RE_SUPERSEDES = re.compile(
    r"(?:hết hiệu lực|bãi bỏ|thay thế)[^.;]{0,200}?" + RE_DOC_NUMBER.pattern, re.IGNORECASE
)
RE_INTERNAL_REF = re.compile(
    r"(?:điểm\s+([a-zđ])\s+)?(?:khoản\s+(\d+)\s+)?Điều\s+(\d+)(?:\s+của)?\s+"
    r"(?:Luật|Nghị định|Thông tư|Quyết định|Quy định)\s+này"
    r"|(?:điểm\s+([a-zđ])\s+)?khoản\s+(\d+)\s+Điều\s+này",
    re.IGNORECASE,
)

FALLBACK_CHUNK_CHARS = 1500


class ParseError(ValueError):
    """The file cannot be parsed into a usable regulation (fail closed)."""


@dataclass
class Line:
    page: int  # 1-based
    text: str
    bbox: tuple[float, float, float, float]
    start: int = 0
    end: int = 0


@dataclass
class ParsedClause:
    numbering: str
    level: str
    parent: str | None
    start: int  # offset of the clause's own text (marker excluded)
    end: int = 0
    anchor: int = 0  # start of the line holding the marker; the previous clause ends here
    heading: str | None = None
    text: str = ""
    page: int | None = None
    bbox: list[list[float]] = field(default_factory=list)


@dataclass
class ParsedReference:
    source_numbering: str
    ref_text: str
    target_doc_number: str | None = None
    target_numbering: str | None = None


@dataclass
class ParsedRegulation:
    text: str
    page_count: int
    clauses: list[ParsedClause]
    references: list[ParsedReference]
    metadata: dict
    warnings: list[str]


# --- PDF → lines ---------------------------------------------------------------------------


def extract_lines(pdf_bytes: bytes) -> tuple[list[Line], int]:
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise ParseError(f"not a readable PDF: {exc}") from exc
    if doc.needs_pass:
        raise ParseError("PDF is password protected")

    raw: list[Line] = []
    heights: dict[int, float] = {}
    for pno, page in enumerate(doc, start=1):
        heights[pno] = page.rect.height
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                text = normalize("".join(span["text"] for span in line["spans"]))
                if text:
                    raw.append(Line(page=pno, text=text, bbox=tuple(line["bbox"])))
    page_count = len(doc)

    # Running headers/footers: same text at the page edge on at least half of the pages.
    edge_counts: Counter[str] = Counter()
    for line in raw:
        h = heights[line.page]
        if line.bbox[1] < 0.08 * h or line.bbox[3] > 0.92 * h:
            edge_counts[line.text] += 1
    running = {t for t, c in edge_counts.items() if page_count >= 3 and c >= page_count / 2}

    return [
        line
        for line in raw
        if line.text not in running and not any(p.match(line.text) for p in _NOISE)
    ], page_count


def build_canonical_text(lines: list[Line]) -> str:
    parts, offset = [], 0
    for line in lines:
        line.start, line.end = offset, offset + len(line.text)
        parts.append(line.text)
        offset = line.end + 1
    return "\n".join(parts)


# --- Lines → clause tree ---------------------------------------------------------------------


def _parse_date(d: str, m: str, y: str) -> str | None:
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


def extract_metadata(lines: list[Line], text: str) -> dict:
    head = lines[:40]
    meta: dict = {}
    for line in head:
        if "doc_number" not in meta and re.search(r"\bsố\b", line.text, re.IGNORECASE):
            m = RE_DOC_NUMBER.search(line.text)
            if m:
                meta["doc_number"] = m.group(1)
        if "issued_date" not in meta:
            m = RE_VN_DATE.search(line.text)
            if m:
                meta["issued_date"] = _parse_date(*m.groups())

    issuer_lines = []
    for line in head:
        if line.text.startswith("CỘNG HÒA") or not line.text.isupper():
            break
        if not re.fullmatch(r"[-_\s]+", line.text):
            issuer_lines.append(line.text)
    if issuer_lines:
        meta["issuer"] = " ".join(issuer_lines)

    for i, line in enumerate(head):
        if line.text in LEGAL_FORMS:
            meta["legal_form"] = line.text
            title_lines = []
            for nxt in head[i + 1 :]:
                if not nxt.text.isupper() or nxt.text.startswith("CĂN CỨ"):
                    break
                title_lines.append(nxt.text)
            if title_lines:
                meta["subject"] = " ".join(title_lines).capitalize()
            break

    m = RE_EFFECTIVE.search(text)
    if m:
        meta["valid_from"] = _parse_date(*m.groups())
    supersedes = sorted({m.group(1) for m in RE_SUPERSEDES.finditer(text)})
    supersedes = [n for n in supersedes if n != meta.get("doc_number")]
    if supersedes:
        meta["supersedes"] = supersedes
    return meta


def _next_letter(letter: str | None) -> str:
    if letter is None:
        return POINT_LETTERS[0]
    idx = POINT_LETTERS.find(letter)
    return POINT_LETTERS[idx + 1] if 0 <= idx < len(POINT_LETTERS) - 1 else ""


def parse_structure(lines: list[Line], text: str) -> tuple[list[ParsedClause], list[str]]:
    clauses: list[ParsedClause] = []
    warnings: list[str] = []
    chapter = section = article = khoan = None
    last_article = 0
    last_khoan = 0
    last_point: str | None = None
    appendix_count = 0
    mode = "body"  # body | appendix | closing

    has_attached = any(
        re.search(r"^(QUY ĐỊNH|QUY CHẾ|QUY TRÌNH)\b", ln.text, re.IGNORECASE) for ln in lines
    )
    is_decision = has_attached

    def open_clause(numbering, level, parent, line, marker_len, heading=None):
        # Do not strip or replace "Điều", "Chương", "Điểm", "Phụ lục", "Mục" at start of clause
        if level in ("article", "chapter", "section", "appendix", "point") or re.match(
            r"^(Điều|Chương|Điểm|Phụ lục|Mục|Mục lục)\b", line.text, re.IGNORECASE
        ):
            start = line.start
        else:
            start = line.start + marker_len
            # Skip whitespace between the marker and the text so offsets point at real content.
            while start < len(text) and text[start] in " \n":
                start += 1
        node = ParsedClause(numbering, level, parent, start, heading=heading, anchor=line.start)
        clauses.append(node)
        return node

    if lines:
        open_clause("PREAMBLE", "preamble", None, lines[0], 0)

    for line in lines:
        t = line.text

        if is_decision:
            if re.match(r"^(QUY ĐỊNH|QUY CHẾ|QUY TRÌNH)\b", t, re.IGNORECASE) or (
                article and RE_CHAPTER.match(t)
            ):
                is_decision = False
                chapter = section = article = khoan = None
                last_article = 0
                last_khoan = 0
                last_point = None
                mode = "body"
            elif (m := RE_ARTICLE.match(t)) and (
                int(m.group(1)) == last_article + 1 or (last_article == 0 and article is None)
            ):
                last_article = int(m.group(1))
                article = f"QD.{last_article}"
                open_clause(article, "article", "QD", line, m.start(2), heading=m.group(2) or None)
                continue
            elif RE_CLOSING.match(t):
                continue

        if mode != "appendix" and article and RE_APPENDIX.match(t):
            mode = "appendix"
        if mode == "appendix":
            if RE_APPENDIX.match(t):
                appendix_count += 1
                open_clause(f"PL-{appendix_count}", "appendix", None, line, 0, heading=t)
            elif m := RE_CLAUSE.match(t):
                open_clause(
                    f"PL-{appendix_count}.{m.group(1)}",
                    "clause",
                    f"PL-{appendix_count}",
                    line,
                    m.start(2),
                )
            continue
        if mode == "body" and article and RE_CLOSING.match(t):
            mode = "closing"
            open_clause("END", "closing", None, line, 0)
            continue
        if mode == "closing":
            if (
                re.match(r"^(QUY ĐỊNH|QUY CHẾ|QUY TRÌNH)\b", t, re.IGNORECASE)
                or RE_CHAPTER.match(t)
                or (RE_ARTICLE.match(t) and int(RE_ARTICLE.match(t).group(1)) == 1)
            ):
                mode = "body"
                chapter = section = article = khoan = None
                last_article = 0
                last_khoan = 0
                last_point = None
            else:
                continue

        if m := RE_CHAPTER.match(t):
            chapter = m.group(1).upper()
            section = None
            open_clause(chapter, "chapter", None, line, m.start(2) if m.group(2) else len(t))
            continue
        if chapter and (m := RE_SECTION.match(t)):
            section = f"{chapter}.M{m.group(1)}"
            open_clause(section, "section", chapter, line, m.start(2) if m.group(2) else len(t))
            continue
        if (m := RE_ARTICLE.match(t)) and (
            int(m.group(1)) == last_article + 1 or (last_article == 0 and article is None)
        ):
            last_article = int(m.group(1))
            article = str(last_article)
            khoan, last_khoan, last_point = None, 0, None
            heading = m.group(2) or None
            open_clause(article, "article", section or chapter, line, m.start(2), heading=heading)
            continue
        if article and (m := RE_CLAUSE.match(t)) and int(m.group(1)) == last_khoan + 1:
            last_khoan = int(m.group(1))
            khoan = f"{article}.{last_khoan}"
            last_point = None
            open_clause(khoan, "clause", article, line, m.start(2))
            continue
        if (
            article
            and (m := RE_POINT.match(t))
            and (m.group(1) == _next_letter(last_point) or last_point is None)
        ):
            last_point = m.group(1)
            parent = khoan or article
            open_clause(f"{parent}.{last_point}", "point", parent, line, m.start(2))
            continue

    if last_article == 0:
        warnings.append("no Điều structure recognised; fell back to fixed-size chunks")
        clauses = _fallback_chunks(lines)
    else:
        _split_appendices(clauses, lines, text)

    _close_spans(clauses, lines, text)
    return [c for c in clauses if c.text or c.level in ("chapter", "section", "article")], warnings


def _fallback_chunks(lines: list[Line]) -> list[ParsedClause]:
    chunks: list[ParsedClause] = []
    current: ParsedClause | None = None
    for line in lines:
        if current is None or line.end - current.start > FALLBACK_CHUNK_CHARS:
            current = ParsedClause(
                f"C{len(chunks) + 1}", "chunk", None, line.start, anchor=line.start
            )
            chunks.append(current)
    return chunks


def _split_appendices(clauses: list[ParsedClause], lines: list[Line], text: str) -> None:
    """Appendices (forms, tables) have no Điều structure: split each into L3 chunks."""
    appendices = [c for c in clauses if c.level == "appendix"]
    for i, app in enumerate(appendices):
        stop = appendices[i + 1].start if i + 1 < len(appendices) else len(text)
        current_start, n = None, 0
        for line in lines:
            if line.start <= app.start or line.start >= stop:
                continue
            if current_start is None or line.end - current_start > FALLBACK_CHUNK_CHARS:
                n += 1
                current_start = line.start
                numbering = f"{app.numbering}.c{n}"
                clauses.append(
                    ParsedClause(numbering, "chunk", app.numbering, line.start, anchor=line.start)
                )
    clauses.sort(key=lambda c: (c.anchor, c.start))


def _close_spans(clauses: list[ParsedClause], lines: list[Line], text: str) -> None:
    """A clause's own text runs until the next clause opens (children excluded)."""
    clauses.sort(key=lambda c: (c.anchor, c.start))
    for i, clause in enumerate(clauses):
        end = clauses[i + 1].anchor if i + 1 < len(clauses) else len(text)
        # Trailing whitespace before the next marker is not part of this clause.
        while end > clause.start and text[end - 1] in " \n":
            end -= 1
        clause.end = max(end, clause.start)
        clause.text = text[clause.start : clause.end]
        covered = [ln for ln in lines if ln.end > clause.start and ln.start < clause.end]
        if covered:
            clause.page = covered[0].page
            clause.bbox = [[ln.page, *[round(v, 1) for v in ln.bbox]] for ln in covered]


def extract_references(
    clauses: list[ParsedClause], self_number: str | None
) -> list[ParsedReference]:
    refs: list[ParsedReference] = []
    by_numbering = {c.numbering for c in clauses}
    for clause in clauses:
        if clause.level in ("preamble", "closing"):
            continue
        seen = set()
        for m in RE_DOC_NUMBER.finditer(clause.text):
            number = m.group(1)
            if number != self_number and number not in seen:
                seen.add(number)
                refs.append(ParsedReference(clause.numbering, number, target_doc_number=number))
        for m in RE_INTERNAL_REF.finditer(clause.text):
            if m.group(3):
                point, khoan, art = m.group(1), m.group(2), m.group(3)
            else:
                point, khoan = m.group(4), m.group(5)
                art = clause.numbering.split(".")[0]
            target = art + (f".{khoan}" if khoan else "") + (f".{point.lower()}" if point else "")
            refs.append(
                ParsedReference(
                    clause.numbering,
                    m.group(0),
                    target_numbering=target if target in by_numbering else None,
                )
            )
    return refs


def parse_pdf(pdf_bytes: bytes, min_chars_per_page: int = 200) -> ParsedRegulation:
    lines, page_count = extract_lines(pdf_bytes)
    text = build_canonical_text(lines)
    if page_count == 0 or len(text) < min_chars_per_page * max(1, page_count) / 4:
        # Scanned PDF without a text layer. OCR is not configured: fail closed.
        raise ParseError(
            f"too little text ({len(text)} chars over {page_count} pages); "
            "looks like a scanned PDF and OCR is not configured"
        )
    clauses, warnings = parse_structure(lines, text)
    metadata = extract_metadata(lines, text)
    references = extract_references(clauses, metadata.get("doc_number"))
    return ParsedRegulation(text, page_count, clauses, references, metadata, warnings)
