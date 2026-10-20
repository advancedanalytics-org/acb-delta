/**
 * Demo data for the prototype. All content is fictional and labeled "Dữ liệu demo" in the UI.
 * Documents and impacts live in JSON so scripts/demo-data/generate_demo_pdfs.py can render the
 * PDFs and compute real highlight positions (highlights.json) from the same source.
 */
import type { BBox, Decision, EvalRun, ExampleSet, Impact, InternalDocument, Reviewer, Vbpl } from '@/api/types'

import documentsJson from './demo-documents.json'
import impactsJson from './demo-impacts.json'
import highlightsJson from './highlights.json'

type VbplSeed = Omit<Vbpl, 'status' | 'impactCount' | 'pendingCount'> & { processing?: boolean }

export const vbplSeeds: VbplSeed[] = [
  {
    id: 'vbpl-tt-31-2026',
    sourceUrl: '/demo/doc-cv-01.pdf',
    number: '31/2026/TT-NHNN',
    title: 'Thông tư quy định về hoạt động cho vay và bảo vệ quyền lợi khách hàng vay',
    issuer: 'Ngân hàng Nhà nước Việt Nam',
    issuedDate: '2026-10-05',
    effectiveDate: '2027-01-01',
    receivedAt: '2026-10-14T08:12:00+07:00',
    summary:
      'Thay thế Thông tư 39/2016/TT-NHNN. Siết thời hạn và hạn mức cho vay tiêu dùng, bổ sung xác thực sinh trắc học, quy định lại thông báo lãi suất và nhắc nợ.',
  },
  {
    id: 'vbpl-qd-2045-2026',
    sourceUrl: '/demo/doc-kyc-02.pdf',
    number: '2045/QĐ-NHNN',
    title: 'Quyết định về tỷ lệ dự trữ bắt buộc đối với tổ chức tín dụng',
    issuer: 'Ngân hàng Nhà nước Việt Nam',
    issuedDate: '2026-10-15',
    effectiveDate: '2026-11-01',
    receivedAt: '2026-10-16T16:40:00+07:00',
    summary: 'Điều chỉnh tỷ lệ dự trữ bắt buộc đối với tiền gửi bằng đồng Việt Nam.',
    processing: true,
  },
  {
    id: 'vbpl-tt-27-2026',
    sourceUrl: '/demo/doc-the-03.pdf',
    number: '27/2026/TT-NHNN',
    title: 'Thông tư sửa đổi, bổ sung một số điều của Thông tư 18/2024/TT-NHNN về hoạt động thẻ ngân hàng',
    issuer: 'Ngân hàng Nhà nước Việt Nam',
    issuedDate: '2026-09-12',
    effectiveDate: '2026-12-01',
    receivedAt: '2026-09-15T09:05:00+07:00',
    summary: 'Hạ trần phí chậm thanh toán thẻ tín dụng và cập nhật căn cứ pháp lý.',
  },
]

export const reviewers: Reviewer[] = [
  { id: 'rv-anh', name: 'Nguyễn Minh Anh', role: 'Chuyên viên pháp chế' },
  { id: 'rv-bao', name: 'Trần Quốc Bảo', role: 'Trưởng phòng tuân thủ' },
]

const highlights = highlightsJson.highlights as Record<string, { page: number; bboxes: number[][] }>
const pageCounts = highlightsJson.pageCounts as Record<string, number>

export const documents: InternalDocument[] = documentsJson.documents.map((doc) => ({
  id: doc.id,
  code: doc.code,
  title: doc.title,
  department: doc.department,
  version: doc.version,
  effectiveDate: doc.effectiveDate,
  pdfUrl: `/demo/${doc.id}.pdf`,
  pageCount: pageCounts[doc.id] ?? 1,
}))

export const impactSeeds: Omit<Impact, 'status'>[] = impactsJson.impacts.map((impact) => ({
  ...(impact as Omit<Impact, 'status' | 'page' | 'bboxes'>),
  page: highlights[impact.id]?.page ?? 1,
  bboxes: (highlights[impact.id]?.bboxes ?? []) as BBox[],
}))

const [anh, bao] = reviewers

export const seedDecisions: Decision[] = [
  {
    id: 'dec-seed-1',
    impactId: 'imp-14',
    vbplId: 'vbpl-tt-27-2026',
    documentId: 'doc-the-03',
    action: 'accept',
    reasonTags: [],
    reviewer: anh,
    at: '2026-09-18T10:21:00+07:00',
  },
  {
    id: 'dec-seed-2',
    impactId: 'imp-15',
    vbplId: 'vbpl-tt-27-2026',
    documentId: 'doc-the-03',
    action: 'edit',
    editedText:
      'Phí chậm thanh toán bằng 4% số tiền thanh toán tối thiểu chưa thanh toán, tối thiểu 80.000 đồng.',
    reasonTags: ['Sai số liệu'],
    reviewer: bao,
    at: '2026-09-18T14:02:00+07:00',
  },
  {
    id: 'dec-seed-3',
    impactId: 'imp-01',
    vbplId: 'vbpl-tt-31-2026',
    documentId: 'doc-cv-01',
    action: 'accept',
    reasonTags: [],
    reviewer: anh,
    at: '2026-10-15T09:14:00+07:00',
  },
  {
    id: 'dec-seed-4',
    impactId: 'imp-09',
    vbplId: 'vbpl-tt-31-2026',
    documentId: 'doc-kyc-02',
    action: 'edit',
    editedText:
      'Hồ sơ nhận biết khách hàng được lưu trữ tối thiểu 10 năm kể từ ngày kết thúc giao dịch hoặc đóng tài khoản, theo Quy định lưu trữ hồ sơ của Ngân hàng.',
    reasonTags: ['Thiếu nội dung'],
    reviewer: anh,
    at: '2026-10-15T09:31:00+07:00',
  },
  {
    id: 'dec-seed-5',
    impactId: 'imp-10',
    vbplId: 'vbpl-tt-31-2026',
    documentId: 'doc-kyc-02',
    action: 'reject',
    reasonTags: ['Đã xử lý ở văn bản khác'],
    reviewer: bao,
    at: '2026-10-15T15:47:00+07:00',
  },
]

/** Illustrative numbers only: the real values come from KHOA-01 experiments. */
export const evalRuns: EvalRun[] = [
  {
    id: 'run-baseline',
    label: 'Baseline',
    createdAt: '2026-10-12T21:30:00+07:00',
    datasetSize: 48,
    note: 'Prompt gốc, chưa dùng phản hồi HITL.',
    metrics: {
      extraction: { precision: 0.874, recall: 0.812 },
      retrieval: { recallAtK: 0.781, k: 5, mrr: 0.643 },
      impact: { precision: 0.716, recall: 0.842, f1: 0.774 },
      amendment: { judgeScore: 3.41, hitlAcceptRate: 0.537 },
      system: { latencySeconds: 46.8, costUsdPerDocument: 0.214 },
    },
  },
  {
    id: 'run-feedback-1',
    label: 'Sau phản hồi vòng 1',
    createdAt: '2026-10-16T22:05:00+07:00',
    datasetSize: 61,
    note: 'Few-shot động từ 37 quyết định chấp nhận / sửa, 9 ví dụ âm từ quyết định từ chối.',
    metrics: {
      extraction: { precision: 0.889, recall: 0.826 },
      retrieval: { recallAtK: 0.794, k: 5, mrr: 0.668 },
      impact: { precision: 0.783, recall: 0.897, f1: 0.836 },
      amendment: { judgeScore: 3.87, hitlAcceptRate: 0.681 },
      system: { latencySeconds: 51.2, costUsdPerDocument: 0.238 },
    },
  },
  {
    id: 'run-feedback-2',
    label: 'Sau phản hồi vòng 2',
    createdAt: '2026-10-19T21:40:00+07:00',
    datasetSize: 73,
    note: 'DPO vòng 2 + few-shot mở rộng; thêm 24 quyết định sửa / từ chối.',
    metrics: {
      extraction: { precision: 0.903, recall: 0.858 },
      retrieval: { recallAtK: 0.832, k: 5, mrr: 0.701 },
      impact: { precision: 0.821, recall: 0.915, f1: 0.865 },
      amendment: { judgeScore: 4.12, hitlAcceptRate: 0.742 },
      system: { latencySeconds: 49.5, costUsdPerDocument: 0.231 },
    },
  },
]

/**
 * Illustrative few-shot examples only. The real set is built from HITL decisions by the backend
 * (`GET /api/eval/examples`); these mirror its shape so the panel can be previewed in mock mode.
 */
export const exampleSets: Record<'draft' | 'judge', ExampleSet> = {
  draft: {
    task: 'draft',
    positive: [
      {
        impactId: 'imp-15',
        category: 'conflict',
        reasonTags: ['Sai số liệu'],
        affectedText: 'Phí chậm thanh toán bằng 6% số tiền thanh toán tối thiểu chưa thanh toán.',
        chosen:
          'Phí chậm thanh toán bằng 4% số tiền thanh toán tối thiểu chưa thanh toán, tối thiểu 80.000 đồng.',
        rejected: 'Phí chậm thanh toán bằng 5% số tiền thanh toán tối thiểu chưa thanh toán.',
        rationale:
          'Thông tư 27/2026 hạ trần phí chậm thanh toán thẻ tín dụng; mức cũ 6% vượt trần mới.',
      },
      {
        impactId: 'imp-01',
        category: 'new_obligation',
        reasonTags: [],
        affectedText: 'Khách hàng vay tiêu dùng được định danh bằng giấy tờ tùy thân hợp lệ.',
        chosen:
          'Khách hàng vay tiêu dùng phải được định danh bằng giấy tờ tùy thân hợp lệ và xác thực sinh trắc học theo Thông tư 31/2026/TT-NHNN.',
        rejected: null,
        rationale: 'Thông tư 31/2026 bổ sung yêu cầu xác thực sinh trắc học với cho vay tiêu dùng.',
      },
    ],
    negative: [
      {
        impactId: 'imp-09',
        category: 'outdated_reference',
        reasonTags: ['Thiếu nội dung'],
        affectedText: 'Hồ sơ nhận biết khách hàng được lưu trữ tối thiểu 5 năm.',
        chosen:
          'Hồ sơ nhận biết khách hàng được lưu trữ tối thiểu 10 năm kể từ ngày kết thúc giao dịch hoặc đóng tài khoản.',
        rejected: 'Hồ sơ nhận biết khách hàng được lưu trữ tối thiểu 10 năm.',
        rationale: 'Thời hạn lưu trữ cần nêu rõ mốc tính và căn cứ quy định nội bộ.',
      },
    ],
    counts: { decisions_read: 11, positive_available: 2, negative_available: 1 },
  },
  judge: {
    task: 'judge',
    positive: [
      {
        impactId: 'imp-14',
        category: 'conflict',
        reasonTags: [],
        affectedText: 'Căn cứ Thông tư 18/2024/TT-NHNN về hoạt động thẻ ngân hàng.',
        chosen:
          'Căn cứ Thông tư 18/2024/TT-NHNN (được sửa đổi, bổ sung bởi Thông tư 27/2026/TT-NHNN) về hoạt động thẻ ngân hàng.',
        rejected: null,
        rationale: 'Văn bản dẫn chiếu đã được sửa đổi; cần cập nhật căn cứ pháp lý.',
      },
    ],
    negative: [
      {
        impactId: 'imp-10',
        category: 'outdated_reference',
        reasonTags: ['Đã xử lý ở văn bản khác'],
        affectedText: 'Quy định về hạn mức rút tiền mặt tại máy ATM.',
        chosen: null,
        rejected:
          'Đề xuất cập nhật hạn mức rút tiền mặt theo Thông tư 31/2026/TT-NHNN.',
        rationale:
          'RIA cho rằng điều khoản bị tác động, nhưng nội dung này đã được điều chỉnh ở một văn bản nội bộ khác — không phải tác động cần sửa ở đây.',
      },
    ],
    counts: { decisions_read: 11, positive_available: 1, negative_available: 1 },
  },
}
