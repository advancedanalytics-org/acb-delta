# Báo cáo tiến độ nhóm — 18/10/2026

Nguồn: `PLAN.md` và lịch sử nhánh `main` tại commit `0f11ff6` (sau PR #28).

Ký hiệu: ✅ đã hoàn thành · 🟡 đang làm · ⬜ chưa bắt đầu / tạm hoãn.

## 1. Task

Dự án có **13 task**, đã hoàn thành **7/13**. Tính theo mục con trong `PLAN.md`: **39/63** mục đã xong.

### Tài

| Task | Nội dung | Trạng thái | Mục con xong |
|---|---|---|---|
| TAI-01 | Agent gợi ý chỉnh sửa | ✅ Hoàn thành | 6/6 |
| TAI-02 | Duyệt bởi con người (HITL) | ✅ Hoàn thành | 7/7 |
| TAI-03 | VBPL mẫu và văn bản nội bộ giả lập | ✅ Hoàn thành | 3/3 |
| TAI-04 | Slide (có slide lộ trình DPO / fine-tune) | ⬜ Chưa bắt đầu | — |
| TAI-05 | Thuyết trình và kịch bản demo | ⬜ Chưa bắt đầu | — |
| TAI-06 | Triển khai giai đoạn 1 | ✅ Hoàn thành | 3/3 |
| TAI-07 | Chuyển sang GreenNode | ⬜ Tạm hoãn (demo trên GCP đến khi có tài khoản) | 0/10 |

### Khoa

| Task | Nội dung | Trạng thái | Mục con xong |
|---|---|---|---|
| KHOA-01 | Quy trình đánh giá | 🟡 Đang làm | 3/10 |
| KHOA-02 | Học từ phản hồi (RLHF) | ⬜ Chưa bắt đầu | 0/4 |

### Huy

| Task | Nội dung | Trạng thái | Mục con xong |
|---|---|---|---|
| HUY-01 | Giao diện | ✅ Hoàn thành | 10/10 |
| HUY-02 | Xử lý PDF của NHNN | ✅ Hoàn thành | 5/5 |

### Minh

| Task | Nội dung | Trạng thái | Mục con xong |
|---|---|---|---|
| MINH-01 | Embedding, tìm kiếm, metadata trên pgvector | 🟡 Đang làm | 2/5 |
| MINH-02 | Định dạng tài liệu giả lập | ✅ Hoàn thành | — |

## 2. Công việc

Các đầu mục công việc của dự án, theo `PLAN.md`:

| Mảng | Đầu mục | Task |
|---|---|---|
| Dữ liệu | Thu thập VBPL mẫu; sinh văn bản nội bộ giả lập có cài sẵn mâu thuẫn làm đáp án chuẩn; chốt định dạng tài liệu giả lập | TAI-03, MINH-02 |
| Xử lý PDF | Tách chữ giữ số trang và toạ độ; chia đoạn theo Chương / Mục / Điều / Khoản / Điểm; tạo embedding vào pgvector; lưu PDF gốc | HUY-02 |
| Tìm kiếm và phân tích tác động | Chọn model embedding; chốt cấu trúc đoạn văn bản; tìm kiếm kết hợp vector và từ khoá; xếp hạng lại; đóng gói hàm tìm kiếm | MINH-01 |
| Agent | Tách thay đổi từ VBPL; đánh giá tác động; soạn bản sửa tối thiểu có kiểm tra | TAI-01 |
| Duyệt (HITL) | Lưu quyết định chấp nhận / sửa / từ chối / hoàn tác, lưu vết; gói duyệt từ kết quả RIA; dữ liệu phản hồi cho RLHF | TAI-02 |
| Giao diện | 5 màn hình: hộp thư VBPL, không gian duyệt, xem PDF có tô sáng, bảng đánh giá, lịch sử duyệt | HUY-01 |
| Đánh giá | Bộ dữ liệu đánh giá; chỉ số từng bước; chấm bản sửa bằng LLM; đo độ trễ / chi phí; tự bổ sung bộ kiểm thử; script chạy đánh giá | KHOA-01 |
| Học từ phản hồi | Ví dụ mẫu động từ quyết định duyệt; đo chỉ số trước / sau; xuất dữ liệu DPO | KHOA-02 |
| Triển khai | Môi trường giai đoạn 1 (local + GCP); chuyển sang GreenNode | TAI-06, TAI-07 |
| Trình bày | Slide; thuyết trình và kịch bản demo | TAI-04, TAI-05 |

## 3. Công việc đã hoàn thành

### Đầu mục đã hoàn thành

**Tài**
- TAI-01: agent LangGraph gồm tách thay đổi, đánh giá tác động, soạn bản sửa (PR #7); endpoint `POST /draft` soạn bản sửa tối thiểu (thay / chèn / xoá) có bước kiểm tra độc lập (PR #21).
- TAI-02: bảng và API lưu quyết định duyệt, lưu vết không ghi đè (PR #9); chuyển kết quả RIA thành gói duyệt (PR #23); giao diện duyệt đọc gói duyệt (PR #24); thẻ duyệt hiện đề xuất AI kèm nút chấp nhận / từ chối (PR #25); API `GET /api/feedback` cho KHOA-02; đã chạy thử toàn luồng trên model thật.
- TAI-03: VBPL mẫu, văn bản nội bộ giả lập dạng PDF (`scripts/demo-data/generate_demo_pdfs.py`, PR #2), đáp án chuẩn cho đánh giá.
- TAI-06: khung dự án và Docker Compose (PR #2); script `scripts/run.sh` (PR #3, #4); máy ảo demo trên GCP tự triển khai mỗi khi có thay đổi trên `main`, chạy Gemini 4 Argon, xếp hạng lại bằng Vertex, embedding bge-m3 (PR #14, #17, #18, #26, #27).
- Đồng bộ trạng thái task trong `PLAN.md` (PR #28).

**Huy**
- HUY-01: đủ 5 màn hình, nối API thật, tải VBPL lên, xem PDF có tô sáng theo trạng thái, phím tắt A/E/R/J/K, thông báo có nút hoàn tác, chọn người duyệt (PR #6, #20).
- HUY-02: tách chữ PDF bằng PyMuPDF giữ số trang và toạ độ, chia đoạn theo cấu trúc pháp lý, embedding vào pgvector, lưu PDF lên MinIO (PR #6, #10, #22).

**Khoa**
- KHOA-01 (một phần): phần tính chỉ số và cấu trúc bộ dữ liệu (PR #5); tài liệu `docs/evaluation-data-contract.md` (PR #11); API lưu và trả kết quả đánh giá `/api/eval/runs` (PR #16). Chỉ số đã có: tách thay đổi (độ chính xác / độ phủ), tìm kiếm (Recall@k, MRR), phát hiện tác động (độ chính xác / độ phủ / F1).

**Minh**
- MINH-01 (một phần): API nạp văn bản và phân tích tác động RIA (PR #12); tìm kiếm kết hợp vector và từ khoá; xếp hạng lại; lọc nghĩa vụ không áp dụng; gộp lời gọi LLM; bộ nhớ đệm LLM (PR #19).
- MINH-02: mẫu `db/DOC-102.md` → `db/DOC-102.parsed.json`, mô hình dữ liệu `db/data-model.md` (PR #12).

### Link demo

- Link: https://34-143-129-52.sslip.io (đã kiểm tra lúc 16:45 ngày 18/10: trang mở được, cơ sở dữ liệu và agent đều `ok`)
- User / pass: không ghi trong repo vì repo đang để công khai. Lấy bằng `./scripts/gcp.sh login` (cần `gcloud` đăng nhập vào project `acb-delta-demo-2340`) hoặc hỏi Tài.

## 4. Công việc còn cần hoàn thành

### Cần cho demo

| Người | Task | Việc |
|---|---|---|
| Tài | TAI-04 | Làm slide, gồm slide lộ trình DPO / fine-tune |
| Tài | TAI-05 | Thuyết trình và kịch bản demo |
| Khoa | KHOA-01 | Họp với Minh và Tài thống nhất luồng dữ liệu đánh giá |
| Khoa | KHOA-01 | Dựng bộ dữ liệu trên Langfuse từ đáp án chuẩn của TAI-03 |
| Khoa | KHOA-01 | Chấm bản sửa bằng LLM theo tiêu chí (đúng, sửa tối thiểu, nhất quán pháp lý) và tỉ lệ chấp nhận từ HITL |
| Khoa | KHOA-01 | Đo độ trễ và chi phí cho mỗi văn bản (đã có hàm tính, chưa có nguồn đo) |
| Khoa | KHOA-01 | Tự biến mỗi lần từ chối / sửa trong HITL thành mục mới trong bộ kiểm thử |
| Khoa | KHOA-01 | Script chạy đánh giá và xuất kết quả cho bảng đánh giá trên giao diện |
| Khoa | KHOA-02 | Xác nhận luồng dữ liệu với Tài (luồng đã chốt) |
| Khoa | KHOA-02 | Dùng quyết định chấp nhận / sửa làm ví dụ mẫu động cho bước đánh giá tác động và soạn bản sửa; từ chối làm ví dụ âm |
| Khoa | KHOA-02 | Đo chỉ số trước / sau khi học từ phản hồi (số liệu cho demo) |
| Minh | MINH-01 | Chọn và thử model embedding tiếng Việt (đang dùng bge-m3) |
| Minh | MINH-01 | Chốt cấu trúc đoạn văn bản |
| Minh | MINH-01 | Đóng gói hàm tìm kiếm cho agent (cần xác nhận còn cần không) |

### Sau demo

| Người | Task | Việc |
|---|---|---|
| Khoa | KHOA-02 | Xuất cặp ưu tiên (chọn / bỏ) thành bộ dữ liệu DPO |
| Tài | TAI-07 | Chuyển sang GreenNode khi có tài khoản: tài khoản dịch vụ IAM, endpoint LLM trên MaaS, script nạp và re-embed dữ liệu, đóng gói agent lên AgentBase, chuyển CSDL sang vDB, PDF sang vStorage, chạy frontend và FastAPI trên vServer, chạy lại đánh giá |

## Câu hỏi chưa giải quyết

- Mục "Đóng gói hàm tìm kiếm cho agent" của MINH-01 còn cần không? Với Engine A, agent không tự tìm kiếm nữa.
- Có chốt chính thức bge-m3 (1024 chiều) làm model embedding không? Code và máy ảo GCP đang dùng, nhưng `PLAN.md` vẫn ghi chưa chốt.
