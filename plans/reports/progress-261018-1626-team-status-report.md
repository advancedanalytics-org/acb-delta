# Báo cáo tiến độ nhóm — 18/10/2026

Nguồn: `PLAN.md` và lịch sử nhánh `main` tại commit `0f11ff6` (sau khi gộp PR #28). Hiện không còn PR nào đang mở.

Ký hiệu: ✅ đã hoàn thành · 🟡 đang làm · ⬜ chưa bắt đầu / tạm hoãn.

## 1. Tóm tắt nhanh

| Người | Đã hoàn thành | Đang làm | Chưa làm |
|---|---|---|---|
| Tài | TAI-01, TAI-02, TAI-03, TAI-06 | — | TAI-04, TAI-05, TAI-07 (tạm hoãn) |
| Khoa | — | KHOA-01 | KHOA-02 |
| Huy | HUY-01, HUY-02 | — | — |
| Minh | MINH-02 | MINH-01 | — |

## 2. Trạng thái chi tiết theo người

### Tài

| Task | Trạng thái | Nội dung đã làm |
|---|---|---|
| TAI-01 – Agent gợi ý chỉnh sửa | ✅ Hoàn thành | Agent LangGraph gồm các bước tách thay đổi, chia nhánh theo từng thay đổi, đánh giá tác động, soạn bản sửa (PR #7). Engine A: endpoint `POST /draft` nhận một kết quả phân tích RIA và soạn bản sửa tối thiểu (thay / chèn / xoá), có bước kiểm tra độc lập (PR #21) |
| TAI-02 – Duyệt bởi con người (HITL) | ✅ Hoàn thành | Bảng lưu quyết định và API chấp nhận / sửa / từ chối / hoàn tác, lưu vết không ghi đè (PR #9). Chuyển kết quả RIA thành gói duyệt (PR #23). Giao diện duyệt đọc gói duyệt (PR #24). Thẻ duyệt hiện đề xuất của AI kèm nút chấp nhận / từ chối (PR #25). Đã chạy thử toàn luồng trên model thật của GCP |
| TAI-03 – VBPL mẫu và văn bản nội bộ giả lập | ✅ Hoàn thành | Thu thập VBPL mẫu (bản cũ và bản sửa đổi), sinh văn bản nội bộ giả lập dạng PDF (`scripts/demo-data/generate_demo_pdfs.py`, PR #2), cài sẵn các điểm mâu thuẫn làm đáp án chuẩn cho đánh giá |
| TAI-04 – Slide | ⬜ Chưa bắt đầu | |
| TAI-05 – Thuyết trình và kịch bản demo | ⬜ Chưa bắt đầu | |
| TAI-06 – Triển khai giai đoạn 1 | ✅ Hoàn thành | Dựng khung dự án và Docker Compose (PR #2), script `scripts/run.sh` (PR #3, #4). Máy ảo demo trên GCP tự triển khai mỗi khi có thay đổi trên `main` (PR #14, #17, #18, #26, #27): chat bằng Gemini 4 Argon, xếp hạng lại bằng Vertex, embedding bằng bge-m3 |
| TAI-07 – Chuyển sang GreenNode | ⬜ Tạm hoãn | Tạm thời demo trên máy ảo GCP, chỉ chuyển khi có tài khoản GreenNode |

### Khoa

| Task | Trạng thái | Nội dung |
|---|---|---|
| KHOA-01 – Quy trình đánh giá | 🟡 Đang làm | **Đã có:** phần tính chỉ số và cấu trúc bộ dữ liệu (PR #5), tài liệu hợp đồng dữ liệu `docs/evaluation-data-contract.md` (PR #11), API lưu và trả kết quả đánh giá `/api/eval/runs` (PR #16). Các chỉ số đã viết: độ chính xác / độ phủ khi tách thay đổi, Recall@k và MRR khi tìm kiếm, độ chính xác / độ phủ / F1 khi phát hiện tác động. **Chưa có:** bộ dữ liệu trên Langfuse, chấm bản sửa bằng LLM, đo độ trễ và chi phí, tự bổ sung bộ kiểm thử từ quyết định duyệt, lượt chạy đánh giá thật |
| KHOA-02 – Học từ phản hồi (RLHF) | ⬜ Chưa bắt đầu | Dữ liệu đầu vào `GET /api/feedback` đã sẵn sàng (từ TAI-02), luồng dữ liệu đã chốt |

### Huy

| Task | Trạng thái | Nội dung đã làm |
|---|---|---|
| HUY-01 – Giao diện | ✅ Hoàn thành | Đủ 5 màn hình, đã nối API thật, tải VBPL lên, xem PDF có tô sáng theo trạng thái, phím tắt A/E/R/J/K, thông báo có nút hoàn tác, cập nhật lạc quan, chọn người duyệt (PR #6, #10, #20, #22) |
| HUY-02 – Xử lý PDF của NHNN | ✅ Hoàn thành | Tách chữ từ PDF bằng PyMuPDF giữ số trang và toạ độ, chia đoạn theo Chương / Mục / Điều / Khoản / Điểm, tạo embedding lưu vào pgvector, lưu PDF gốc lên MinIO |

### Minh

| Task | Trạng thái | Nội dung |
|---|---|---|
| MINH-01 – Embedding, tìm kiếm, metadata trên pgvector | 🟡 Đang làm | **Đã có:** API nạp văn bản và phân tích tác động RIA (PR #12); tìm kiếm kết hợp vector và từ khoá; xếp hạng lại; lọc nghĩa vụ không áp dụng; gộp lời gọi LLM; bộ nhớ đệm LLM (PR #19). **Chưa có:** chốt model embedding trên GreenNode, chốt cấu trúc đoạn văn bản |
| MINH-02 – Định dạng tài liệu giả lập | ✅ Hoàn thành | Mẫu `db/DOC-102.md` → `db/DOC-102.parsed.json`, mô hình dữ liệu `db/data-model.md` |

## 3. Công việc đã hoàn thành theo thời gian

Có 28 PR đã gộp vào `main`, giờ ghi theo giờ Việt Nam. PR #8 trùng nội dung với PR #9.

### Ngày 17/10

| PR | Giờ | Người | Task | Công việc |
|---|---|---|---|---|
| #1 | 10:07 | Tài | — | Quy định chung cho các agent lập trình (`AGENTS.md`) và quy trình CI |
| #2 | 12:53 | Tài | TAI-06, TAI-03 | Khung dự án: backend FastAPI, agent, giao diện mẫu 5 màn hình, Docker Compose, dữ liệu demo |
| #3 | 13:00 | Tài | TAI-06 | Script `scripts/run.sh` để chạy và kiểm tra hệ thống trên máy |
| #4 | 13:03 | Tài | TAI-06 | Hướng dẫn agent dùng `run.sh` |
| #6 | 22:11 | Huy | HUY-01, HUY-02 | Giao diện và API nạp PDF, gợi ý AI; hộp thoại tải VBPL, xem PDF có tô sáng, trang lịch sử duyệt |
| #5 | 22:17 | Khoa | KHOA-01 | Phần tính chỉ số và cấu trúc bộ dữ liệu đánh giá |

### Ngày 18/10

| PR | Giờ | Người | Task | Công việc |
|---|---|---|---|---|
| #7 | 01:25 | Tài | TAI-01 | Agent LangGraph: tách thay đổi → đánh giá tác động → soạn bản sửa |
| #9 | 09:30 | Tài | TAI-02 | Bảng và API lưu quyết định duyệt |
| #10 | 10:05 | Huy | HUY-02 | Tăng giới hạn dung lượng file, cải thiện chia đoạn và lưu vector |
| #11 | 10:38 | Khoa | KHOA-01 | Tài liệu hợp đồng dữ liệu đánh giá |
| #12 | 10:39 | Minh | MINH-01 | API nạp văn bản và phân tích tác động RIA, mẫu tài liệu giả lập |
| #13 | 10:59 | Tài | TAI-02 | Sửa lỗi xem PDF khi tác động không có số trang |
| #14 | 11:15 | Tài | TAI-06 | Tự triển khai `main` lên máy ảo GCP |
| #15 | 11:27 | Tài | HUY-02 | Lưu ngày hiệu lực của PDF theo chuẩn ISO để giao diện đọc được |
| #16 | 11:46 | Khoa | KHOA-01 | API lưu và trả kết quả đánh giá |
| #17 | 13:04 | Tài | TAI-06 | Chạy Qwen trên Vertex AI và bge-m3 trên máy ảo GCP |
| #18 | 13:11 | Tài | TAI-06 | Mở endpoint `/v1` có khoá cho model trên máy ảo GCP |
| #19 | 14:10 | Minh | MINH-01 | Xếp hạng lại, lọc nghĩa vụ không áp dụng, gộp lời gọi LLM, bộ nhớ đệm |
| #20 | 14:31 | Huy | HUY-01 | Nối giao diện với backend thật |
| #21 | 14:31 | Tài | TAI-01 | Soạn bản sửa tối thiểu có kiểm tra cho từng kết quả RIA |
| #22 | 14:35 | Huy | HUY-02 | Sửa lỗi thiếu import logging |
| #23 | 15:00 | Tài | TAI-02 | Chuyển kết quả RIA thành gói duyệt |
| #24 | 15:24 | Tài | TAI-02 | Giao diện duyệt đọc gói duyệt |
| #25 | 16:02 | Tài | TAI-02 | Thẻ duyệt hiện đề xuất AI và nút chấp nhận / từ chối |
| #26 | 16:05 | Tài | TAI-06 | Chat bằng Gemini 4 Argon và xếp hạng lại bằng Vertex trên máy ảo GCP |
| #27 | 16:19 | Tài | TAI-06 | Triển khai GCP nạp lại cấu hình mới của litellm và caddy |
| #28 | 16:29 | Tài | — | Đồng bộ trạng thái task trong `PLAN.md` và thêm báo cáo này |

### Tổng kết theo người

| Người | Số PR đã gộp | Task đã hoàn thành |
|---|---|---|
| Tài | 19 | TAI-01, TAI-02, TAI-03, TAI-06 |
| Huy | 4 | HUY-01, HUY-02 |
| Khoa | 3 | Chưa có (KHOA-01 đang làm) |
| Minh | 2 | MINH-02 (MINH-01 đang làm) |

## 4. Quyết định đã chốt hôm nay

- Tài cập nhật trạng thái HUY-01, KHOA-01, MINH-02 trong `PLAN.md` thay cho người phụ trách (đã gộp ở PR #28).
- Tạm thời demo trên máy ảo GCP; TAI-07 (GreenNode) hoãn đến khi có tài khoản.

## 5. Việc cần làm tiếp để kịp demo

1. Khoa: chạy đánh giá thật trên luồng RIA; làm KHOA-02 để có số liệu trước / sau khi học từ phản hồi.
2. Huy: bảng đánh giá hiển thị kết quả thật từ `/api/eval/runs`.
3. Minh: chốt model embedding và cấu trúc đoạn văn bản, ghi vào `PLAN.md`.
4. Tài: TAI-04 làm slide, TAI-05 viết kịch bản demo.

## Câu hỏi chưa giải quyết

- Mục "Đóng gói hàm tìm kiếm cho agent" của MINH-01 còn cần không? Với Engine A, agent không tự tìm kiếm nữa.
- Có chốt chính thức bge-m3 (1024 chiều) làm model embedding không? Code và máy ảo GCP đang dùng, nhưng `PLAN.md` vẫn ghi chưa chốt.
