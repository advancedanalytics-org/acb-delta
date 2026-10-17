# Kế hoạch dự án – AI đánh giá tác động VBPL lên văn bản nội bộ

## Quy ước theo dõi

- `[ ]` chưa làm · `[~]` đang làm · `[x]` hoàn thành · `[!]` bị chặn (ghi lý do bên cạnh)
- Mỗi task có **ID** (vd. `TAI-01`). Ghi ID vào commit message / PR title để dễ truy vết, vd. `feat(HUY-02): chunking PDF NHNN`.
- Cập nhật trạng thái bằng cách sửa checkbox trong file này và commit cùng thay đổi liên quan.
- Task phụ thuộc nhau được ghi ở mục **Phụ thuộc**. Không bắt đầu task bị chặn khi task phụ thuộc chưa xong (hoặc chưa thống nhất).

---

## Tổng quan theo người phụ trách

| Người | Mảng chính | Số task |
|---|---|---|
| Tài | Gợi ý chỉnh sửa, HITL, dữ liệu, trình bày, deploy | 6 |
| Khoa | Evaluate, RLHF | 2 |
| Huy | UI, pipeline xử lý dữ liệu NHNN | 2 |
| Minh | Vector DB (embed + search + metadata), format tài liệu mock | 2 |

---

## Tài

- [ ] **TAI-01** – Gợi ý chỉnh sửa
- [ ] **TAI-02** – HITL (Human-in-the-loop)
- [ ] **TAI-03** – Tìm tài liệu VBPL & fake dữ liệu văn bản nội bộ
  - [ ] Thu thập tài liệu VBPL mẫu
  - [ ] Tạo dữ liệu văn bản nội bộ giả lập theo format đã thống nhất (xem `MINH-02`)
- [ ] **TAI-04** – Slide
- [ ] **TAI-05** – Thuyết trình
- [ ] **TAI-06** – Deploy

## Khoa

- [ ] **KHOA-01** – Luồng Evaluate
  - [ ] Họp với Minh + Tài thống nhất luồng dữ liệu cho evaluate
  - [ ] Thống nhất cơ chế enrich test set
  - [ ] Hiện thực luồng evaluate
- [ ] **KHOA-02** – Luồng RLHF
  - [ ] Họp với Tài thống nhất luồng dữ liệu cho RLHF
  - [ ] Hiện thực luồng RLHF

## Huy

- [ ] **HUY-01** – UI
- [ ] **HUY-02** – Luồng xử lý dữ liệu NHNN
  - [ ] PDF → text
  - [ ] text → chunk
  - [ ] chunk → embedding

## Minh

- [ ] **MINH-01** – Nghiên cứu luồng embed + search + metadata dữ liệu nội bộ trên vector DB
- [ ] **MINH-02** – Làm việc với Tài để thống nhất document format cho tài liệu mock

---

## Phụ thuộc & điểm đồng bộ

| Task | Phụ thuộc / cần phối hợp | Ghi chú |
|---|---|---|
| TAI-03 (fake dữ liệu nội bộ) | MINH-02 | Cần chốt format trước khi sinh dữ liệu mock |
| KHOA-01 | Minh, Tài | Thống nhất luồng dữ liệu evaluate + enrich test set |
| KHOA-02 | TAI-02 | Dữ liệu feedback từ HITL là đầu vào cho RLHF |
| MINH-01 | HUY-02 | Dùng chung chiến lược chunk/embedding và schema metadata |
| TAI-01 | MINH-01, HUY-02 | Gợi ý chỉnh sửa cần search được VBPL + văn bản nội bộ |
| TAI-04, TAI-05 | Các luồng chính chạy được end-to-end | Slide & demo |
| TAI-06 | HUY-01 + các luồng backend | Deploy bản tích hợp |

---

## Quyết định đã thống nhất

> Ghi lại kết quả các buổi thống nhất để cả nhóm tham chiếu.

- **Document format tài liệu mock** (MINH-02): _chưa chốt_
- **Luồng dữ liệu Evaluate + cơ chế enrich test set** (KHOA-01): _chưa chốt_
- **Luồng dữ liệu RLHF** (KHOA-02): _chưa chốt_
- **Schema metadata trên vector DB** (MINH-01): _chưa chốt_
