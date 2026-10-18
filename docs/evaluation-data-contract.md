# Hợp đồng dữ liệu cho evaluate (KHOA-01 / KHOA-02)

> Đề xuất của Khoa, chưa phải kết luận. `PLAN.md` dòng 169-170 vẫn ghi hai luồng dữ liệu này là
> `_chưa chốt_`; mục 6 dưới đây soạn sẵn wording để dán vào **Quyết định đã thống nhất** sau khi họp.
>
> Mỗi yêu cầu trong mục 2 đều kèm lý do **"không khôi phục được ở phía sau"**. Thứ gì adapter phía
> evaluate hấp thụ được thì đã nằm ở mục 3 (không yêu cầu ai làm gì).

## 0. Tóm tắt

| Ai | Cần làm gì | Mức |
|---|---|---|
| Tài (`TAI-03`) | Ground truth dạng `DatasetItem`, mỗi impact kỳ vọng có `chunk_id` | Phải có |
| Tài (`TAI-01`) | Một đường để lấy `candidates` + thứ hạng ra khỏi agent | Phải có |
| Minh (`MINH-01`) | Trả lời: `chunk_id` có đổi sau re-index không | Phải có |
| Tài (`TAI-01`) | Mang `change.clause` (vị trí) đi kèm mỗi impact | Nên có |
| Huy (`HUY-01`) | Cho các leaf của `EvalMetrics` nhận `null` | Không chặn |

Lý do cần hợp đồng: đã có **ba chỗ lệch** trong code đã merge, mỗi chỗ chỉ cần một dòng spec là tránh
được — `ChangeKind` lệch giá trị, `ImpactOut` làm mất đường dẫn điều khoản, và `ImpactState` bỏ
`candidates` khiến Recall@k/MRR không tồn tại được.

## 1. Phía evaluate cung cấp gì

Schema đã nằm trên `main`: [`backend/app/evaluation/schema.py`](../backend/app/evaluation/schema.py).
Metric đã có test: `backend/tests/test_evaluation_metrics.py` (27 test, mỗi con số kỳ vọng tính tay
trong comment).

### `DatasetItem` — định dạng ground truth

Một file JSON là một mảng `DatasetItem`. Ví dụ hai item, cố ý khác loại nhau:

```json
[
  {
    "item_id": "tt-31-2026-khoan-2-dieu-9",
    "vbpl_id": "vbpl-tt-31-2026",
    "changes": [
      { "article_path": "Khoản 2 Điều 9", "kind": "amended" },
      { "article_path": "Điều 12", "kind": "added" }
    ],
    "impacts": [
      {
        "change_path": "Khoản 2 Điều 9",
        "document_id": "doc-cv-01",
        "chunk_id": "doc-cv-01:3:1",
        "type": "conflict",
        "severity": "high",
        "reference_amendment": "1. Thời hạn cho vay tiêu dùng tối đa là 60 tháng."
      }
    ]
  },
  {
    "item_id": "tt-31-2026-dieu-15-khong-anh-huong",
    "vbpl_id": "vbpl-tt-31-2026",
    "changes": [{ "article_path": "Điều 15", "kind": "added" }],
    "impacts": []
  }
]
```

Item thứ hai (`"impacts": []`) **quan trọng không kém item thứ nhất**: nó là cách duy nhất đo được
false positive. Nếu dataset chỉ có những thay đổi thật sự gây tác động, Precision luôn đẹp và con số
vô nghĩa. Đề nghị Tài sinh cả hai loại, tỉ lệ khoảng 70/30.

Ghi chú từng field:

| Field | Ý nghĩa |
|---|---|
| `item_id` | Khoá nối ground truth với output. Tự do, miễn là duy nhất |
| `article_path` / `change_path` | Vị trí điều khoản, viết **tự nhiên thế nào cũng được**: `"Khoản 2 Điều 9"`, `"Điều 9, khoản 2"`, `"điều 9 khoản 2"` đều chuẩn hoá về `9.2`. Không cần theo thứ tự nào |
| `kind` | `added` / `amended` / `repealed` — khớp `agent/agent/schemas.py:7` |
| `chunk_id` | Xem mục 2.3. Hiện là `doc_id:chỉ_số_điều:chỉ_số_đoạn` |
| `type` | `conflict` / `outdated_reference` / `new_obligation` |
| `severity` | `high` / `medium` / `low` |
| `reference_amendment` | Bản sửa đúng, dùng cho LLM-as-judge. Để `null` được, chỉ mất điểm `judgeScore` |

### `PipelineOutput` — thứ runner dựng từ output của agent

Đây là ranh giới adapter, **không phải yêu cầu với ai**: runner tự chuyển từ response của
`POST /invoke` sang dạng này.

```json
{
  "item_id": "tt-31-2026-khoan-2-dieu-9",
  "changes": [{ "article_path": "Khoản 2 Điều 9", "kind": "amended" }],
  "retrieval": [
    { "change_path": "Khoản 2 Điều 9", "chunk_ids": ["doc-cv-01:3:1", "doc-kyc-02:1:2"] }
  ],
  "impacts": [
    {
      "change_path": "Khoản 2 Điều 9",
      "document_id": "doc-cv-01",
      "chunk_id": "doc-cv-01:3:1",
      "type": "conflict",
      "severity": "high",
      "suggested_text": "1. Thời hạn cho vay tiêu dùng tối đa là 60 tháng."
    }
  ],
  "latency_seconds": 46.8,
  "cost_usd": null
}
```

Trường `retrieval` hiện **không điền được** — đó chính là yêu cầu 2.2.

### Một lỗi phía evaluate, tự sửa

`backend/app/evaluation/schema.py:19` đang là `Literal["new", "amended", "repealed"]`, lệch với
`agent/agent/schemas.py:7` (`"added"`). Đây là lỗi của Khoa, sẽ sửa trong PR `khoa-01-eval-runner`,
không cần ai làm gì.

## 2. Phía evaluate cần gì

### 2.1 Ground truth — Tài (`TAI-03`) · Phải có

Một file JSON như mục 1, cho các VBPL mẫu đã cài mâu thuẫn chủ ý.

**Vì sao không khôi phục được**: không có ground truth thì **không metric nào** tính được. Đây là
blocker nặng nhất của cả KHOA-01 và KHOA-02; mọi thứ khác trong doc này chỉ quyết định metric nào
đo được, còn cái này quyết định có đo được gì hay không.

Số lượng để demo có ý nghĩa: khoảng 30-50 item. Chưa cần đủ ngay — 5 item là đã chạy được end-to-end
và thấy số thật.

### 2.2 Đường ra cho `candidates` — Tài (`TAI-01`) · Phải có

**Vì sao không khôi phục được**: `agent/agent/state.py` không còn `candidates` (đã bỏ khi chuyển sang
fan-out). `impacts` trả về chỉ là **tập con** đã bị `judge_impact` cho là `affected` — không có top-k,
không có thứ hạng. Mà Recall@k và MRR **định nghĩa trên thứ hạng**, nên không có đường nào suy ra.

`retrieve_candidates(change, k)` ở `agent/agent/retriever.py:48` đã là hàm gọi trực tiếp được, nhưng
nó nằm trong package `agent`, còn metric nằm trong `backend`. Hai uv project riêng, không import chéo.

Hai phương án, **Khoa nghiêng phương án A**:

| | Phương án A — `POST /retrieve` trên agent | Phương án B — thêm `candidates` vào `InvokeResponse` |
|---|---|---|
| Cách làm | Endpoint mới nhận `Change` + `k`, trả `list[Candidate]` | Đưa `candidates` trở lại `ImpactState` và vào response |
| Ưu | Đo retrieval **độc lập với bước extract** — biết retriever tốt hay không dù extract sai; không làm response `/invoke` phình to | Một lời gọi, ít code hơn |
| Nhược | Thêm một endpoint | Payload to; và nếu extract bỏ sót change thì không đo được retrieval cho change đó |

Phương án A quan trọng hơn vẻ ngoài: khi Minh thay retriever bằng pgvector hybrid search, cần đo được
retriever mới **mà không bị nhiễu** bởi chất lượng của `extract_changes`.

### 2.3 Cam kết về `chunk_id` — Minh (`MINH-01`) · Phải có

Hiện tại `agent/agent/retriever.py:37` sinh `chunk_id = f"{doc['id']}:{a}:{p}"` — doc id, **chỉ số**
điều, **chỉ số** đoạn.

**Vì sao không khôi phục được**: ground truth trỏ tới chunk bằng `chunk_id`. Nếu id đổi, ground truth
mục rỗng toàn bộ và metric retrieval lẫn impact đều vô nghĩa — mà sẽ **không ai nhận ra**, vì metric
vẫn chạy và chỉ tụt điểm.

Ba câu hỏi cần Minh trả lời:

1. Khi thay bằng pgvector, `chunk_id` còn dẫn xuất từ cấu trúc văn bản, hay thành UUID của hàng DB?
   (Cần loại thứ nhất, hoặc ít nhất là một id ổn định được lưu kèm.)
2. Re-embed / re-index có đổi `chunk_id` không?
3. Vì id hiện tại dùng **chỉ số** đoạn, nên chèn thêm một đoạn vào giữa văn bản sẽ dịch id của mọi
   đoạn sau nó. Có thể khoá bằng số điều/khoản thật thay vì chỉ số thứ tự không?

Nếu câu 2 hoặc 3 là "có đổi", cần một thủ tục regenerate ground truth, và phải ghi vào `PLAN.md`.

### 2.4 Giữ lại `change.clause` trên impact — Tài (`TAI-01`) · Nên có

`agent/agent/nodes/analyze_change.py:27` gán `change_clause=change.text` — tức là **nội dung** điều
khoản, không phải **vị trí**. `Change` có cả `clause` (`'Khoản 2 Điều 9'`) và `text`, nhưng `ImpactOut`
chỉ mang `text`. `citation` thì do LLM sinh, không phải đường dẫn cấu trúc. `agent_client.py:52` lưu
đúng giá trị đó vào DB nên đọc `impacts.model_output` cũng không khôi phục được.

**Có workaround**: `/invoke` trả về cả `changes` và `impacts`, nên join `impact.change_clause ==
change.text` để lấy lại `clause`. Vì vậy đây là "nên có", không phải "phải có".

**Nhưng workaround mong manh**: hai change trùng `text` là join nhập nhằng, và nó biến một quan hệ
đáng ra là khoá ngoại thành so khớp chuỗi tự do.

Đề nghị: thêm một field mang `change.clause` bên cạnh `change_clause` hiện tại (đang mang `text`, và
UI đang dùng đúng như vậy nên **không nên đổi nghĩa field cũ**). Làm vậy thì `impacts.model_output`
trong DB trở nên tự đủ cho eval, không cần join.

## 3. Phía evaluate KHÔNG cần gì

Để danh sách trên ngắn và có sức nặng, đây là những thứ đã kiểm và **không yêu cầu ai làm**:

- **Token usage / chi phí.** Không cần Tài sửa `llm.py`. `agent/agent/llm.py:26` ghi rõ callback
  Langfuse truyền xuống qua graph config, nên Langfuse đã ghi token và cost từng generation. Khoa lấy
  qua Langfuse API — đúng như `PLAN.md:101` viết ("chi phí / văn bản (AgentBase Usage)").
- **Đổi tên field.** Agent gọi `Change.clause`, ground truth gọi `article_path`. Adapter phía Khoa
  hấp thụ.
- **Đổi `retrieve_k`.** `agent/agent/config.py:22` đã là `5`, khớp `DEFAULT_K` của metric và nhãn
  `"Recall@5"` hardcode trong `frontend/src/features/evaluation/evaluation-page.tsx`. Không cần làm gì.
- **Thay đổi bảng HITL.** `backend/app/models/hitl.py` đã đủ cho KHOA-02: `decisions` append-only,
  `undone_at` thay vì ghi đè, và `impacts.model_output` (JSONB) với comment sẵn *"Raw agent output for
  this impact, for evaluation (KHOA-01 / KHOA-02)"*. Không cần thêm gì.

## 4. Một bẫy đo lường phải ghi vào biên bản

`agent/agent/config.py:21`: `max_changes: int = 10`.

Đây là **trần cứng cho extraction Recall, do cấu hình chứ không do chất lượng model**. VBPL có 15 thay
đổi thật thì Recall tối đa là 10/15 = 0.67 kể cả khi model hoàn hảo. Hệ quả nguy hiểm: số liệu sẽ bị
đọc là "model bỏ sót" trong khi thật ra là "cấu hình chặn".

Hai việc phải chốt:

1. Mỗi lần eval ghi lại `max_changes` và `retrieve_k` cùng kết quả. Trước mắt nhét vào field `note`
   của `EvalRun`; nếu muốn thành field riêng thì cần Huy đổi `types.ts`.
2. Dataset không được có item nào số change kỳ vọng vượt `max_changes`, hoặc phải nâng `max_changes`
   trước khi chạy. Validator dataset phía Khoa sẽ kiểm và báo lỗi.

## 5. Một việc cho Huy — không chặn

`frontend/src/api/types.ts:108-114` khai mọi leaf của `EvalMetrics` là `number` bắt buộc, và
`evaluation-page.tsx` đọc thẳng `metric.read(m)` không kiểm null.

Nhưng `amendment.judgeScore` (`types.ts:112`) sẽ là `null` cho tới khi có LLM-as-judge, và
`hitlAcceptRate` là `null` khi chưa ai duyệt gì. Điền `0` thay thế là **sai** — `0` đọc như "đo được
và kém", còn `null` là "chưa đo". `AGENTS.md:115` cấm fake result.

Nên cho các leaf nhận `null` và màn hình hiển thị `—`. `EvalRun` thuộc KHOA-01 nên Khoa đề xuất thay
đổi, nhưng màn hình là của Huy.

## 6. Đề xuất wording để chốt vào `PLAN.md`

Nếu buổi họp đồng ý, hai dòng `_chưa chốt_` ở `PLAN.md:169-170` thay bằng:

> - **Luồng dữ liệu Evaluate + enrich test set** (KHOA-01): ground truth là file JSON mảng
>   `DatasetItem` (`backend/app/evaluation/schema.py`) do `TAI-03` sinh, gồm cả item không có impact
>   để đo false positive. Runner gọi agent, chuyển output sang `PipelineOutput`, tính điểm bằng
>   `app.evaluation.metrics`; mỗi lần chạy ghi lại `max_changes` + `retrieve_k`. Retrieval đo riêng
>   qua `POST /retrieve`. Chi phí và token lấy từ Langfuse, không từ `/invoke`. Enrich test set: mỗi
>   `reject` / `edit` trong bảng `decisions` thành một `DatasetItem` mới, `edited_text` thành
>   `reference_amendment`.
> - **Luồng dữ liệu feedback loop** (KHOA-02): đọc bảng `decisions` append-only của `TAI-02`; nhãn của
>   mỗi impact là quyết định mới nhất chưa `undone_at`. `accept` / `edit` = chosen, `reject` =
>   rejected. Vòng ngắn: few-shot động lấy từ chosen, ví dụ âm từ rejected. Vòng dài: cặp preference
>   DPO là (`edited_text`, `suggested_text`) cho `edit`, và (`affected_text`, `suggested_text`) cho
>   `reject` — bản bị từ chối luôn là `rejected`.

## Phụ lục — mọi dẫn chứng trong doc này

Kiểm lại bằng:

```sh
grep -n 'ChangeKind = ' agent/agent/schemas.py backend/app/evaluation/schema.py
grep -n 'max_changes\|retrieve_k' agent/agent/config.py
grep -n 'chunk_id=f' agent/agent/retriever.py
grep -n 'def retrieve_candidates' agent/agent/retriever.py
grep -n 'change_clause=' agent/agent/nodes/analyze_change.py
grep -n 'Callbacks (Langfuse)' agent/agent/llm.py
grep -n 'candidates' agent/agent/state.py          # không có kết quả: đó là vấn đề 2.2
grep -n -A 6 'interface EvalMetrics' frontend/src/api/types.ts
grep -n -B 1 'model_output' backend/app/models/hitl.py
```
