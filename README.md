# RIA: Regulatory Impact Analysis — Hướng dẫn sử dụng

Khi một văn bản pháp luật (VBPL) mới được ban hành, hệ thống tự động tìm những văn bản nội bộ của ngân hàng bị ảnh hưởng, đề xuất nội dung chỉnh sửa, để cán bộ thẩm định phê duyệt (có người trong vòng lặp), và theo dõi chất lượng theo thời gian.

Tài liệu này hướng dẫn sử dụng bản demo từ đầu đến cuối.

## 1. Mở bản demo và đăng nhập

- Bản demo trực tuyến: **https://59.153.246.193/** (hoặc địa chỉ do đội cung cấp).
- Thông tin đăng nhập:

| Trường | Giá trị |
|---|---|
| Tài khoản | `acb` |
| Mật khẩu | `acb@2026` |

> Nếu trình duyệt hiển thị cảnh báo chứng chỉ, hãy chọn tiếp tục. Nếu hạ tầng hỏi xác thực trước khi vào, dùng thông tin do đội cung cấp.

Sau khi đăng nhập, thanh điều hướng bên trái gồm 5 mục: **Hộp thư VBPL**, **Văn bản nội bộ**, **Đánh giá**, **Nhật ký kiểm toán**, **Trạng thái hệ thống**.

## 2. Các bước sử dụng

Ví dụ dưới đây dùng **Nghị định 165/2025/NĐ-CP — Quy định chi tiết một số điều và biện pháp thi hành Luật Dữ liệu** trong mục [Văn bản pháp luật đi kèm](#3-văn-bản-pháp-luật-đi-kèm).

### Bước 1 — Tải lên văn bản pháp luật mới
1. Vào **Hộp thư VBPL**.
2. Bấm **Tải lên VBPL**.
3. Kéo‑thả hoặc chọn tệp PDF `nghi-dinh-165-2025-nd-cp-quy-dinh-chi-tiet-luat-du-lieu.pdf`. Có thể nhập Số hiệu / Tiêu đề, hoặc để trống cho hệ thống tự nhận diện.
4. Bấm **Tải lên & Xử lý**. Hệ thống bóc tách văn bản, tách theo Chương/Điều/Khoản và phân tích tác động tới các văn bản nội bộ.

### Bước 2 — Thẩm định đề xuất (có người phê duyệt)
1. Trong **Hộp thư VBPL**, theo dõi trạng thái xử lý của văn bản vừa tải lên.
2. Khi phân tích xong, mở văn bản để vào màn **Thẩm định**.
3. Với mỗi điểm tác động, hệ thống nêu rõ: văn bản nội bộ bị ảnh hưởng, vị trí (Điều/Khoản), lý do, và nội dung chỉnh sửa đề xuất.
4. Chọn **Chấp nhận**, **Sửa** (chỉnh lại nội dung) hoặc **Từ chối** cho từng đề xuất.

### Bước 3 — Xem đồ thị tác động của văn bản nội bộ
1. Vào **Văn bản nội bộ**, chọn một quy định ở danh sách bên trái.
2. Mở tab **Đồ thị tác động**: cây 4 cấp Thông tư → Quy định → Chương → Điều.
3. Bấm vào một **Điều** để mở tab **Nội dung chi tiết** ngay tại điều khoản đó. Tab **Tài liệu gốc** hiển thị bản PDF.

### Bước 4 — Theo dõi chất lượng
- **Đánh giá**: bảng điều khiển chất lượng — độ chính xác trích xuất, truy xuất, phát hiện tác động, điểm đánh giá của mô hình giám khảo, và xu hướng cải thiện qua các lượt.
- **Nhật ký kiểm toán**: lịch sử các quyết định thẩm định.
- **Trạng thái hệ thống**: tình trạng các dịch vụ.

## 3. Văn bản pháp luật đi kèm

Có thể dùng ngay các văn bản trong thư mục [`docs/van-ban-phap-luat/`](docs/van-ban-phap-luat/):

| Văn bản | Nội dung | Tệp |
|---|---|---|
| Nghị định 165/2025/NĐ-CP (30/6/2025) | Quy định chi tiết một số điều và biện pháp thi hành Luật Dữ liệu | [nghi-dinh-165-2025-nd-cp-quy-dinh-chi-tiet-luat-du-lieu.pdf](docs/van-ban-phap-luat/nghi-dinh-165-2025-nd-cp-quy-dinh-chi-tiet-luat-du-lieu.pdf) |
| Luật 134/2025/QH15 (10/12/2025) | Trí tuệ nhân tạo | [luat-134-2025-qh15-tri-tue-nhan-tao.pdf](docs/van-ban-phap-luat/luat-134-2025-qh15-tri-tue-nhan-tao.pdf) |

Gợi ý: bắt đầu với **Nghị định 165/2025/NĐ-CP**, tải lên ở [Bước 1](#bước-1--tải-lên-văn-bản-pháp-luật-mới) để xem toàn bộ luồng từ tải lên đến thẩm định.

## Tài liệu kỹ thuật

Hướng dẫn chạy và phát triển hệ thống: xem [`AGENTS.md`](AGENTS.md).
