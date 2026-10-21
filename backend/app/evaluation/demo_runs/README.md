# demo_runs — số liệu đánh giá minh hoạ cho dashboard

Các file `*.json` ở đây là **số liệu demo minh hoạ** cho trang Đánh giá của bản demo
hackathon, **không phải số đo thật**. Chúng được `app.evaluation.demo_seed` nạp vào
`eval_runs` để dashboard có một câu chuyện cải thiện (Baseline → +Few-shot → +DPO)
thay vì trống hoặc chỉ một lượt.

Cố ý **không** để chữ "demo/mô phỏng" trong `label`/`note` vì dashboard hiển thị hai
trường đó; dấu hiệu demo nằm ở tên thư mục này, README này và docstring của
`demo_seed.py`.

Số đo **thật** vẫn đi theo đường cũ và không bị thay đổi:
`app.evaluation.ria_runner ... --save app/evaluation/baseline_run.json` →
`app.evaluation.seed` (xem `AGENTS.md`). Mỗi file giữ đúng shape `EvalRunCreate`
(`app/evaluation/schemas.py`); `f1` được tính từ `precision`/`recall`, `k` luôn = 5.
