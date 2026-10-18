"""Synthetic ground truth for the RIA evaluation path (KHOA-01).

The internal corpus is mock by design (`PLAN.md` → Phạm vi), and `TAI-03` defines ground truth as
planting the conflicts deliberately and recording them. This module does that: it writes a
synthetic regulation whose obligations are authored *against known clauses* of
`db/DOC-102.parsed.json`, so every label is correct by construction rather than guessed.

`build_dataset` re-reads the real clause text and fails if a planted span is not in it, so the
labels cannot drift away from the corpus without the generator saying so.

What this is not: real NHNN wording, real bank data, or a replacement for `TAI-03`'s own corpus.
It produces labels only -- never metric values, which come from running the pipeline.
"""

import argparse
import io
import json
from pathlib import Path

import pymupdf

from app.evaluation.schema import (
    ExpectedFinding,
    ExpectedObligation,
    ReferencePatch,
    RiaDatasetItem,
)

REGULATION_NUMBER = "88/2026/TT-NHNN"
# RIA derives the document id from the number on page 1 (docs/ria-ingest-analyze.md §1).
REGULATION_DOC_ID = "REG-88-2026-TT-NHNN"
REGULATION_VERSION = f"{REGULATION_DOC_ID}@v1"
INTERNAL_VERSION = "DOC-102@v4"

# Deliberately not 99/2026/TT-NHNN: that number belongs to backend/tests/ria_fixtures.py and would
# collide in a shared database.
REGULATION_HTML = f"""
<p>NGÂN HÀNG NHÀ NƯỚC VIỆT NAM</p>
<p>CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM</p>
<p>Số: {REGULATION_NUMBER}</p>
<p>Hà Nội, ngày 02 tháng 6 năm 2026</p>
<p>THÔNG TƯ</p>
<p>VỀ RÀ SOÁT HỒ SƠ NHẬN BIẾT KHÁCH HÀNG</p>
<p>Căn cứ Luật Các tổ chức tín dụng;</p>
<p>Chương I</p>
<p>QUY ĐỊNH CHUNG</p>
<p>Điều 1. Phạm vi điều chỉnh</p>
<p>Thông tư này quy định việc rà soát hồ sơ nhận biết khách hàng.</p>
<p>Chương II</p>
<p>RÀ SOÁT ĐỊNH KỲ</p>
<p>Điều 2. Rà soát hồ sơ khách hàng định kỳ</p>
<p>1. Tổ chức tín dụng phải rà soát, cập nhật hồ sơ nhận biết khách hàng
định kỳ tối đa 12 tháng một lần.</p>
<p>2. Tổ chức tín dụng có trách nhiệm sau đây:</p>
<p>a) Lưu trữ kết quả rà soát trên hệ thống và bảo đảm truy xuất được;</p>
<p>b) Không được thiết lập quan hệ với khách hàng trước khi hoàn thành
nhận biết khách hàng.</p>
<p>3. Tổ chức tín dụng phải báo cáo Ngân hàng Nhà nước kết quả rà soát
định kỳ hằng quý.</p>
<p>Điều 3. Hiệu lực thi hành</p>
<p>Thông tư này có hiệu lực thi hành kể từ ngày 01 tháng 8 năm 2026.</p>
<p>Nơi nhận:</p>
<p>- Như Điều 3;</p>
"""

_OBLIGATIONS = [
    ExpectedObligation(
        clause_id=f"{REGULATION_VERSION}#2.1",
        text=(
            "Tổ chức tín dụng phải rà soát, cập nhật hồ sơ nhận biết khách hàng "
            "định kỳ tối đa 12 tháng một lần."
        ),
        modality="must",
    ),
    ExpectedObligation(
        clause_id=f"{REGULATION_VERSION}#2.2.a",
        text="Lưu trữ kết quả rà soát trên hệ thống và bảo đảm truy xuất được.",
        modality="must",
    ),
    ExpectedObligation(
        clause_id=f"{REGULATION_VERSION}#2.2.b",
        text=(
            "Không được thiết lập quan hệ với khách hàng trước khi hoàn thành nhận biết khách hàng."
        ),
        modality="must_not",
    ),
    ExpectedObligation(
        clause_id=f"{REGULATION_VERSION}#2.3",
        text=("Tổ chức tín dụng phải báo cáo Ngân hàng Nhà nước kết quả rà soát định kỳ hằng quý."),
        modality="must",
    ),
]

# Every row names the internal clause and the exact span of its real text the label relies on.
# `build_dataset` checks each span against db/DOC-102.parsed.json, so a label that stops matching
# the corpus fails loudly instead of quietly scoring zero.
_FINDINGS = [
    # The internal review cycle is 24 months; the obligation caps it at 12.
    ExpectedFinding(
        obligation_clause_id=f"{REGULATION_VERSION}#2.1",
        internal_clause_id=f"{INTERNAL_VERSION}#5.2",
        category="VALUE_CHANGE",
        priority="high",
        target_span_text="24 tháng",
        reference_patch=ReferencePatch(
            operation="REPLACE", old_text="24 tháng", new_text="tối đa 12 tháng"
        ),
    ),
    # 5.3 restates the same 24-month period, so it has to move with 5.2.
    ExpectedFinding(
        obligation_clause_id=f"{REGULATION_VERSION}#2.1",
        internal_clause_id=f"{INTERNAL_VERSION}#5.3",
        category="VALUE_CHANGE",
        priority="medium",
        target_span_text="24 tháng",
        reference_patch=ReferencePatch(
            operation="REPLACE", old_text="24 tháng", new_text="12 tháng"
        ),
    ),
    # High-risk customers are already reviewed every 12 months: compliant, must not be reported.
    ExpectedFinding(
        obligation_clause_id=f"{REGULATION_VERSION}#2.1",
        internal_clause_id=f"{INTERNAL_VERSION}#5.5",
        category="EQUIVALENT",
        priority="low",
        target_span_text="12 tháng",
    ),
    # Storage and traceability are already required: compliant.
    ExpectedFinding(
        obligation_clause_id=f"{REGULATION_VERSION}#2.2.a",
        internal_clause_id=f"{INTERNAL_VERSION}#4.3",
        category="EQUIVALENT",
        priority="low",
        target_span_text="truy xuất được trên hệ thống",
    ),
    # The obligation forbids it outright; the internal rule keeps an exception. Modality clash.
    ExpectedFinding(
        obligation_clause_id=f"{REGULATION_VERSION}#2.2.b",
        internal_clause_id=f"{INTERNAL_VERSION}#4.1",
        category="CONTRADICTION",
        priority="high",
        target_span_text="trừ trường hợp pháp luật cho phép hoàn thiện sau",
        reference_patch=ReferencePatch(
            operation="DELETE",
            old_text=", trừ trường hợp pháp luật cho phép hoàn thiện sau",
            new_text="",
        ),
    ),
    # 4.2 already refuses service before completion: compliant.
    ExpectedFinding(
        obligation_clause_id=f"{REGULATION_VERSION}#2.2.b",
        internal_clause_id=f"{INTERNAL_VERSION}#4.2",
        category="EQUIVALENT",
        priority="low",
        target_span_text="không cung cấp sản phẩm, dịch vụ khi chưa hoàn thành",
    ),
    # Reporting goes to an internal division only; reporting to the central bank is new.
    ExpectedFinding(
        obligation_clause_id=f"{REGULATION_VERSION}#2.3",
        internal_clause_id=f"{INTERNAL_VERSION}#11.1",
        category="ADDITION",
        priority="medium",
        target_span_text="báo cáo Khối Tuân thủ",
        reference_patch=ReferencePatch(
            operation="INSERT",
            old_text="",
            new_text=" Đơn vị báo cáo Ngân hàng Nhà nước kết quả rà soát định kỳ hằng quý.",
        ),
    ),
]

NOTE = (
    "Dữ liệu tổng hợp cho KHOA-01. Thông tư là văn bản tự soạn, KHÔNG phải văn bản NHNN thật. "
    "Nhãn đúng do cấu trúc: mỗi nghĩa vụ được viết nhằm vào một điều khoản đã biết của "
    "db/DOC-102.parsed.json, và generator kiểm lại từng span trên văn bản thật. "
    "Đây không phải output của TAI-03. File này chỉ chứa nhãn, không chứa số liệu metric."
)


def _internal_texts(parsed_path: Path) -> dict[str, str]:
    parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
    return {clause["clause_id"]: clause["text"] for clause in parsed["clause"]}


def build_dataset(parsed_path: Path) -> RiaDatasetItem:
    """Assemble the labels, checking every planted span against the real internal text."""
    texts = _internal_texts(parsed_path)
    problems = []
    for finding in _FINDINGS:
        text = texts.get(finding.internal_clause_id)
        if text is None:
            problems.append(f"{finding.internal_clause_id}: clause not in {parsed_path.name}")
        elif finding.target_span_text and finding.target_span_text not in text:
            problems.append(
                f"{finding.internal_clause_id}: span {finding.target_span_text!r} not in its text"
            )
    if problems:
        joined = "\n  ".join(problems)
        raise ValueError(f"Ground-truth labels no longer match the corpus:\n  {joined}")

    return RiaDatasetItem(
        item_id="khoa01-doc102-kyc-review",
        regulation_number=REGULATION_NUMBER,
        regulation_pdf=f"{REGULATION_DOC_ID}.pdf",
        obligations=list(_OBLIGATIONS),
        findings=list(_FINDINGS),
    )


def regulation_pdf() -> bytes:
    """Render the synthetic regulation, same approach as backend/tests/ria_fixtures.py."""
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    story = pymupdf.Story(html=REGULATION_HTML)
    more = True
    while more:
        device = writer.begin_page(pymupdf.paper_rect("a4"))
        more, _ = story.place(pymupdf.Rect(50, 50, 545, 790))
        story.draw(device)
        writer.end_page()
    writer.close()
    return buffer.getvalue()


def write(out_dir: Path, parsed_path: Path) -> tuple[Path, Path]:
    """Write the dataset JSON and the regulation PDF. Returns both paths."""
    item = build_dataset(parsed_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    dataset_path = out_dir / "dataset.json"
    payload = {"note": NOTE, "items": [item.model_dump(mode="json")]}
    dataset_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    pdf_path = out_dir / item.regulation_pdf
    pdf_path.write_bytes(regulation_pdf())
    return dataset_path, pdf_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("../data/eval"))
    parser.add_argument("--parsed", type=Path, default=Path("../db/DOC-102.parsed.json"))
    args = parser.parse_args()

    dataset_path, pdf_path = write(args.out, args.parsed)
    item = build_dataset(args.parsed)
    positives = len(item.expected_findings)
    equivalents = len(item.findings) - positives
    print(f"dataset: {dataset_path}")
    print(f"regulation: {pdf_path}")
    print(
        f"{len(item.obligations)} obligations, {positives} findings to report, "
        f"{equivalents} equivalents (false-positive probes)"
    )


if __name__ == "__main__":
    main()
