# demo_feedback — bộ phản hồi HITL minh hoạ cho mục RLHF

`corpus.json` ở đây là **dữ liệu demo minh hoạ** cho mục "Học từ phản hồi (RLHF)"
và các tab ví dụ trong trang Đánh giá của bản demo hackathon, **không phải lịch sử
duyệt thật**. Mục đó được dựng từ **quyết định HITL thật** (`GET /api/feedback` →
`app.routers.decisions.list_feedback`), nên khi chưa ai duyệt thì nó trống: vòng tiến
độ DPO ở 0, biểu đồ chấp nhận/sửa/từ chối rỗng và hai tab ví dụ báo "chưa có ca nào".

`app.evaluation.demo_feedback_seed` nạp corpus này thành các VBPL → impact đã được
duyệt (accept / edit / reject) để vòng tiến độ DPO, phân rã hành động và ví dụ few-shot
đều có dữ liệu. Mỗi dòng mang tiền tố id `demofb-` nên seeder tìm và xoá đúng dữ liệu
của chính nó; quyết định thật qua `POST /api/decisions` không bao giờ bị đụng tới.

Cố ý **không** để chữ "demo/mô phỏng" trong nội dung impact hay quyết định (UI hiển thị
các trường này); dấu hiệu demo nằm ở tên thư mục này, README này, tiền tố id `demofb-`
và docstring của `demo_feedback_seed.py`.

Corpus được cân để số **cặp preference dùng được** (quyết định `edit` + `reject` — chỉ
hai loại này mới tương phản hai đoạn văn bản) vượt ngưỡng mặc định `DPO_MIN_PAIRS`, nên
vòng tiến độ đọc là "sẵn sàng" mà không phải hạ ngưỡng. Các loại quyết định dạy bước nào
theo đúng `docs/amendment-review-contract.md` §4: `edit` dạy drafter, `reject` dạy judge.

Cách chạy (trong `backend/`):

```sh
uv run python -m app.evaluation.demo_feedback_seed            # chèn khi chưa có
uv run python -m app.evaluation.demo_feedback_seed --replace  # seed lại bộ demo
```
