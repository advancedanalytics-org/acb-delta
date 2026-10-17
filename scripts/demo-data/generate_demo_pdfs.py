"""Render the mock internal documents to PDF and record where each impact's passage sits.

Reads  frontend/src/api/mock/fixtures/demo-documents.json + demo-impacts.json
Writes frontend/public/demo/<doc-id>.pdf
       frontend/src/api/mock/fixtures/highlights.json  ({impact_id: {page, bboxes, ...}})

Positions come from searching the rendered PDF text, so highlights match the real layout.
Run from the repo root:  uv run --with pymupdf python scripts/demo-data/generate_demo_pdfs.py
"""

import html
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "frontend/src/api/mock/fixtures"
PDF_DIR = ROOT / "frontend/public/demo"

# Be Vietnam Pro (SIL OFL 1.1), downloaded at run time so no binary font lives in git.
FONT_URL = (
    "https://raw.githubusercontent.com/google/fonts/main/ofl/bevietnampro/BeVietnamPro-{}.ttf"
)
FONT_WEIGHTS = {"Regular": "normal", "SemiBold": "bold"}
DEMO_FOOTER = "Văn bản giả lập, chỉ dùng cho demo. Không phải văn bản thật của ngân hàng."

CSS = """
@font-face { font-family: bvp; src: url(BeVietnamPro-Regular.ttf); }
@font-face { font-family: bvp; src: url(BeVietnamPro-SemiBold.ttf); font-weight: bold; }
/* No line-height here: MuPDF Story mis-paginates with it. Spacing comes from margins. */
body { font-family: bvp; font-size: 11pt; color: #1e293b; }
.org { font-size: 9pt; color: #475569; }
h1 { font-size: 15pt; font-weight: bold; text-align: center; margin: 14pt 0 2pt 0; }
.meta { font-size: 9pt; color: #475569; text-align: center; margin-bottom: 14pt; }
h2 { font-size: 11.5pt; font-weight: bold; margin: 16pt 0 6pt 0; }
p { margin: 0 0 8pt 0; }
"""


def download_fonts(font_dir: Path) -> None:
    for weight in FONT_WEIGHTS:
        target = font_dir / f"BeVietnamPro-{weight}.ttf"
        with urllib.request.urlopen(FONT_URL.format(weight), timeout=30) as response:
            target.write_bytes(response.read())


def document_html(doc: dict) -> str:
    parts = [
        '<p class="org">NGÂN HÀNG TMCP (DEMO)<br/>' + html.escape(doc["department"]) + "</p>",
        f"<h1>{html.escape(doc['title'])}</h1>",
        f'<p class="meta">Số hiệu {html.escape(doc["code"])} · Phiên bản {doc["version"]}'
        f" · Hiệu lực từ {format_date(doc['effectiveDate'])}</p>",
    ]
    for article in doc["articles"]:
        parts.append(f"<h2>{html.escape(article['heading'])}</h2>")
        parts.extend(f"<p>{html.escape(text)}</p>" for text in article["paragraphs"])
    return "<body>" + "".join(parts) + "</body>"


def format_date(iso: str) -> str:
    year, month, day = iso.split("-")
    return f"{day}/{month}/{year}"


def render_pdf(doc: dict, font_dir: Path, target: Path) -> None:
    story = pymupdf.Story(
        html=document_html(doc), user_css=CSS, archive=pymupdf.Archive(str(font_dir))
    )
    mediabox = pymupdf.paper_rect("a4")
    content = mediabox + (64, 56, -64, -64)
    writer = pymupdf.DocumentWriter(str(target))
    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(content)
        story.draw(device)
        writer.end_page()
    writer.close()
    add_footers(target, font_dir / "BeVietnamPro-Regular.ttf")


def add_footers(path: Path, font_file: Path) -> None:
    pdf = pymupdf.open(path)
    for page in pdf:
        footer = f"{DEMO_FOOTER}    Trang {page.number + 1}/{pdf.page_count}"
        page.insert_text(
            (64, page.rect.height - 32),
            footer,
            fontname="bvp",
            fontfile=str(font_file),
            fontsize=8,
            color=(0.4, 0.45, 0.53),
        )
    # Embed only the glyphs used; keeps each PDF small enough to commit.
    pdf.subset_fonts()
    # No dates and no random file id, so regenerating unchanged content gives identical bytes.
    pdf.set_metadata({})
    data = pdf.tobytes(garbage=4, deflate=True, no_new_id=True)
    pdf.close()
    path.write_bytes(data)


def locate(pdf: pymupdf.Document, text: str) -> dict | None:
    """Find the passage in the rendered PDF; one bbox per text line it spans."""
    for page in pdf:
        rects = page.search_for(text)
        if rects:
            return {
                "page": page.number + 1,
                "pageWidth": round(page.rect.width, 2),
                "pageHeight": round(page.rect.height, 2),
                "bboxes": merge_lines(rects),
            }
    return None


def merge_lines(rects: list[pymupdf.Rect]) -> list[list[float]]:
    """search_for may return one rect per word; join rects on the same line."""
    lines: list[pymupdf.Rect] = []
    for rect in sorted(rects, key=lambda r: (round(r.y0), r.x0)):
        if lines and abs(lines[-1].y0 - rect.y0) < 2:
            lines[-1] |= rect
        else:
            lines.append(pymupdf.Rect(rect))
    return [[round(v, 2) for v in (r.x0, r.y0, r.x1, r.y1)] for r in lines]


def read_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def main() -> int:
    documents = read_json("demo-documents.json")["documents"]
    impacts = read_json("demo-impacts.json")["impacts"]
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    highlights: dict[str, dict] = {}
    page_counts: dict[str, int] = {}
    missing: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        font_dir = Path(tmp)
        download_fonts(font_dir)
        for doc in documents:
            target = PDF_DIR / f"{doc['id']}.pdf"
            render_pdf(doc, font_dir, target)
            with pymupdf.open(target) as pdf:
                page_counts[doc["id"]] = pdf.page_count
                for impact in impacts:
                    if impact["documentId"] != doc["id"]:
                        continue
                    found = locate(pdf, impact["affectedText"])
                    if found:
                        highlights[impact["id"]] = found
                    else:
                        missing.append(impact["id"])
            print(f"wrote {target.relative_to(ROOT)} ({page_counts[doc['id']]} pages)")

    output = {"pageCounts": page_counts, "highlights": highlights}
    text = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    (FIXTURES / "highlights.json").write_text(text, encoding="utf-8")
    print(f"located {len(highlights)}/{len(impacts)} passages")
    if missing:
        print("passage not found in PDF text for: " + ", ".join(missing), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
