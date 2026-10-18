"""Synthetic regulation PDFs for RIA tests. Wording is invented, not a real NHNN text."""

import io

import pymupdf

RIA_001_HTML = """
<p>NGÂN HÀNG NHÀ NƯỚC VIỆT NAM</p>
<p>CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM</p>
<p>Số: 99/2026/TT-NHNN</p>
<p>Hà Nội, ngày 01 tháng 6 năm 2026</p>
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
<p>a) Lưu trữ kết quả rà soát trên hệ thống;</p>
<p>b) Không được cung cấp dịch vụ khi chưa hoàn thành nhận biết khách hàng.</p>
<p>3. Ngân hàng Nhà nước hướng dẫn chi tiết khoản này.</p>
<p>Điều 3. Hiệu lực thi hành</p>
<p>Thông tư này có hiệu lực thi hành kể từ ngày 01 tháng 7 năm 2026.</p>
<p>Nơi nhận:</p>
<p>- Như Điều 3;</p>
"""


def html_pdf(html: str) -> bytes:
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    story = pymupdf.Story(html=html)
    more = True
    while more:
        device = writer.begin_page(pymupdf.paper_rect("a4"))
        more, _ = story.place(pymupdf.Rect(50, 50, 545, 790))
        story.draw(device)
        writer.end_page()
    writer.close()
    return buffer.getvalue()


def ria_001_pdf() -> bytes:
    return html_pdf(RIA_001_HTML)
