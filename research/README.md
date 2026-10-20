# research/

Mã nguồn tham khảo của các công trình mà RIA mượn ý tưởng. Không chạy trong stack: backend không
import gì từ đây, Docker không build thư mục này, CI và `ruff` của `backend/` / `agent/` không quét nó.

| Thư mục | Nguồn | License | RIA dùng ý tưởng gì |
|---|---|---|---|
| `DICE/` | DICE-Embedding (Document Inference via Chunk Evidence), xây trên [LLM2Vec](https://github.com/McGill-NLP/llm2vec) | MIT (`DICE/LICENSE`) | Gộp vector chunk thành vector tài liệu (`llm2vec/llm2vec.py`, `_aggregate_chunk_embeddings`) → view `article` của Engine 1 (`backend/app/ria/indexing.py`, `build_article_views`) |
| `SLeDoC/` | git submodule → [s-nlp/SLeDoC](https://github.com/s-nlp/SLeDoC) (paper LegDiff, Rykov et al., ACL SRW 2026; SLeDoC, SIGIR 2026) | repo gốc chưa có file LICENSE, nên chỉ trỏ tới, không chép | Prompt căn span `equivalent` / `contradiction` / `addition` + `anchor` (`prompts/llm_nli_system.en.md`) → `alignments` của Engine 2 (`backend/app/ria/compare.py`) |

Chi tiết cách RIA dùng: `docs/ria-ingest-analyze.md` (Engine 1 "Khớp cấp Điều", Engine 2 "Căn span").

## Lấy mã

```sh
git submodule update --init research/SLeDoC
```

## Dữ liệu không nằm trong git

Theo `AGENTS.md`, file dữ liệu lớn không commit. `DICE/` chỉ có code và config. Phần bị bỏ
(khoảng 100 MB) là dữ liệu sinh của ReasonAug: `ReasonAug/ReasonAug.jsonl`,
`ReasonAug/gen_*/**/*.jsonl` và `ReasonAug/gen_problem_solution/before_hard_negative_tmp.pkl`.
Chưa có link công khai cho bộ dữ liệu này. Cần thì hỏi Minh (bản gốc lưu ngoài repo).
