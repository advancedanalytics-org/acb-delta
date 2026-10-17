---
phase: 3
title: "Frontend UI Prototype"
status: completed
priority: P1
effort: "1-1.5d"
dependencies: []
---

# Phase 3: Frontend UI Prototype

<!-- Updated: Validation Session 3 - scope raised from shell-only to full clickable prototype of all HUY-01 screens (owner is team lead, wants to show the idea before teammates build) -->

## Overview
A full, clickable, production-looking prototype of every screen in `PLAN.md` HUY-01, running on demo data through a typed mock API layer. Purpose: the lead shows the team the intended product; Huy (HUY-01) then switches screens from mock to live APIs without rebuilding them.

## Requirements

**Functional — screens (UI text in Vietnamese, code in English)**

| # | Screen | Route | Content |
|---|---|---|---|
| 1 | **Hộp thư VBPL** (Inbox) | `/` | Table of new VBPL: số hiệu, tiêu đề, cơ quan ban hành, ngày hiệu lực, trạng thái xử lý (Đang xử lý / Chờ duyệt / Hoàn tất), số impact chờ duyệt; search + status filter; row → Review. "Tải lên VBPL" button shown disabled with tooltip "Cần luồng xử lý HUY-02". |
| 2 | **Không gian duyệt** (Review workspace) — priority #1 | `/review/:vbplId` | 3 panes. **Left:** impacts grouped by internal document, severity badge (Cao/Trung bình/Thấp), status filter, progress "12/30 đã duyệt". **Middle:** PDF of the internal document with highlights at stored `page`+`bbox`, colored by status (pending amber / accepted green / rejected red); click card ↔ scroll to highlight. **Right:** new VBPL clause vs affected passage, impact type (Mâu thuẫn / Tham chiếu lỗi thời / Nghĩa vụ mới), reasoning, citation, word-level diff original → suggested; **Chấp nhận / Sửa / Từ chối** + reason chips; Sửa opens inline editor. Shortcuts `A` / `E` / `R`, `J` / `K` next/prev, `?` shows shortcut help. |
| 3 | **Đánh giá** (Evaluation dashboard) | `/evaluation` | Metric cards per pipeline step: tách thay đổi (P/R), retrieval (Recall@k, MRR), phát hiện tác động (P/R/F1), gợi ý chỉnh sửa (LLM-judge score, tỉ lệ chấp nhận HITL), hệ thống (độ trễ, chi phí/văn bản); before/after-feedback comparison chart; run selector. |
| 4 | **Nhật ký kiểm toán** (Audit trail) | `/audit` | Table of HITL decisions: thời gian, người duyệt, VBPL, văn bản nội bộ, hành động, lý do, nội dung đã sửa (expand to diff); filters by action/reviewer/date; export CSV. |
| 5 | **Trạng thái hệ thống** | `/system` | Live `/api/health/ready` checks (always real, never mocked). |

**Functional — shared**
- App shell: sidebar nav (5 routes), header with VBPL search, **user switcher** (demo reviewers: Chuyên viên pháp chế / Trưởng phòng tuân thủ), light/dark toggle.
- Decisions made in Review update Inbox counts, Review progress, highlight colors, Audit trail immediately (shared query cache + optimistic updates); toast with **Hoàn tác** (undo) for 5s.
- Every list has skeleton loading, empty state, and error state.
- Persistent **"Dữ liệu demo"** badge in header while `VITE_API_MODE=mock`.

**Non-functional**
- Stack: Vite + React 19 + TS + Tailwind v4 + shadcn/ui + TanStack Query + TanStack Table + React Router + Recharts + `react-diff-viewer-continued` + `sonner` (toasts); PDF via `react-pdf-highlighter-extended` (fallback below).
- Style "clean enterprise": slate neutrals, one bank-blue accent, semantic status tokens defined once in `index.css` (CSS variables, light + dark); font Be Vietnam Pro; dense but calm spacing. Load the installed frontend-design skill before building.
- Accessible: keyboard reachable, visible focus, ARIA labels on icon buttons, color never the only status signal (icon + text too).
- `npm run lint` + `tsc` clean; production build < ~1.5 MB gz excluding PDF worker.

## Architecture

```text
screens ──► hooks (TanStack Query) ──► api client interface (src/api/client.ts)
                                         ├─ mock impl  (src/api/mock/*, fixtures, in-memory store + localStorage, 200-600ms latency)
                                         └─ live impl  (src/api/live/*, fetch /api/...; only health real today)
selected by VITE_API_MODE=mock|live (default mock in this delivery)
```

- `src/api/types.ts` — proposed contracts: `Vbpl`, `InternalDocument`, `Impact { id, vbplId, documentId, changeClause, affectedText, page, bboxes[], type, severity, reasoning, citation, suggestedText, status }`, `Decision { impactId, action, editedText?, reasonTags[], reviewer, at }`, `EvalRun`, `HealthReport`. Header comment: **proposed; TAI-02 / MINH-01 / KHOA-01 own the final shapes.**
- `src/api/mock/fixtures/` — demo data: 2 VBPL (1 fully processed, 1 "Đang xử lý"), 3 internal documents, ~15 impacts across types/severities, 2 eval runs (before/after feedback), seeded audit entries. Content is fictional and labeled demo.
- Demo PDFs: `scripts/demo-data/generate_demo_pdfs.py` (PyMuPDF, run with `uv run --with pymupdf`) renders the 3 mock internal documents to PDF with a Vietnamese font (Be Vietnam Pro, OFL) and writes real `page`+`bbox` of each affected passage (via text search) to `fixtures/highlights.json`. Outputs committed to `frontend/public/demo/` so nobody needs Python to run the UI.
- Live mode: `/system` works now; other live calls throw a clear "Chưa có API (TAI-02)" error shown in the error state — no silent fallback to mock.

## Related Code Files
- Create: `frontend/` (Vite scaffold, `components.json`, `nginx.conf`, `Dockerfile`, `.dockerignore`, `.env.example` with `VITE_API_MODE`)
- Create: `frontend/src/{main.tsx,App.tsx,index.css,router.tsx}`, `src/api/{types,client}.ts`, `src/api/mock/{index.ts,store.ts,fixtures/*}`, `src/api/live/index.ts`, `src/hooks/*`, `src/components/layout/*`, `src/components/ui/*` (shadcn), `src/features/{inbox,review,evaluation,audit,system}/*`
- Create: `scripts/demo-data/generate_demo_pdfs.py`, `frontend/public/demo/*.pdf`

## Implementation Steps
1. Scaffold Vite React-TS; Tailwind v4 + `@/` alias; shadcn init + needed primitives (button, card, badge, table, tabs, dialog, dropdown-menu, tooltip, textarea, skeleton, separator, scroll-area, toggle-group, avatar).
2. Design tokens (status, severity, accent; light/dark) + font + app shell + router + user switcher + theme toggle.
3. API types + client interface + mock store/fixtures + live impl (health) + mode switch + demo badge.
4. Demo PDF script → PDFs + highlights fixture.
5. Screens in priority order: Review workspace → Inbox → Audit → Evaluation → System.
6. Cross-screen wiring: optimistic decisions, undo toast, shortcuts, skeleton/empty/error states.
7. Vite dev proxy `/api → localhost:8000`; Dockerfile `node:22-alpine` build → `nginx:alpine` (SPA fallback, `/api` proxy, PDF MIME).
8. Walkthrough in browser (light + dark, keyboard only), fix issues; screenshots for the PR.

## Success Criteria
- [x] All 5 routes render with demo data; no console errors
- [x] Review: accept/edit/reject updates highlight color, progress, Inbox count, Audit row; undo reverts all of them
- [x] Highlights sit on the correct passages in the PDFs (bbox from real text search)
- [x] Shortcuts A/E/R/J/K/? work; whole Review flow usable by keyboard
- [x] Light + dark both readable; "Dữ liệu demo" badge visible in mock mode
- [x] `/system` shows real backend health
- [x] `npm run lint` + `npm run build` pass; container serves at :3000

## Risk Assessment
- **Mock contracts invent API shapes** owned by TAI-02/MINH-01/KHOA-01. Mitigation: single `types.ts`, marked "proposed"; review with Tài/Minh/Khoa before they build. Signal: their agreed schema differs → change `types.ts` + fixtures, screens adapt via TS errors.
- **`react-pdf-highlighter-extended` vs React 19** peer-dep/runtime issues. Signal: install conflict or render errors → fall back to `react-pdf` + own absolutely-positioned highlight overlay (bbox × scale). Decide in step 5, note in PR.
- **Prototype mistaken for real results** (eval numbers, impacts). Mitigation: demo badge, fictional fixtures, PR + README state it.
- **Overlap with HUY-01:** this delivers HUY-01's screens on mock data. Huy's remaining scope: live API wiring, real PDFs from vStorage, polish. Update `PLAN.md` HUY-01 accordingly and tell Huy before merge.
- Scope size: largest phase. If time runs short, order of step 5 is the cut line (Review first).
