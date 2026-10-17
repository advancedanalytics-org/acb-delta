/**
 * Demo data for the prototype. All content is fictional and labeled "Dữ liệu demo" in the UI.
 * Documents and impacts live in JSON so scripts/demo-data/generate_demo_pdfs.py can render the
 * PDFs and compute real highlight positions (highlights.json) from the same source.
 */
import type { BBox, Decision, EvalRun, Impact, InternalDocument, Reviewer, Vbpl } from '@/api/types'

import documentsJson from './demo-documents.json'
import impactsJson from './demo-impacts.json'
import highlightsJson from './highlights.json'

type VbplSeed = Omit<Vbpl, 'status' | 'impactCount' | 'pendingCount'> & { processing?: boolean }

export const vbplSeeds: VbplSeed[] = [
  {
    id: 'vbpl-tt-31-2026',
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
]
