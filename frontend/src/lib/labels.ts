import type { DecisionAction, ImpactStatus, ImpactType, Severity, VbplStatus } from '@/api/types'

export const vbplStatusLabel: Record<VbplStatus, string> = {
  processing: 'Đang xử lý',
  awaiting_review: 'Chờ duyệt',
  done: 'Hoàn tất',
}

export const impactStatusLabel: Record<ImpactStatus, string> = {
  pending: 'Chờ duyệt',
  accepted: 'Đã chấp nhận',
  rejected: 'Đã từ chối',
}

export const impactTypeLabel: Record<ImpactType, string> = {
  conflict: 'Mâu thuẫn',
  outdated_reference: 'Tham chiếu lỗi thời',
  new_obligation: 'Nghĩa vụ mới',
}

export const severityLabel: Record<Severity, string> = {
  high: 'Cao',
  medium: 'Trung bình',
  low: 'Thấp',
}

export const actionLabel: Record<DecisionAction, string> = {
  accept: 'Chấp nhận',
  edit: 'Sửa',
  reject: 'Từ chối',
}

/** Reason chips a reviewer can attach to a decision; they feed the KHOA-02 feedback loop. */
export const reasonTags = [
  'Sai trích dẫn',
  'Không liên quan',
  'Đã xử lý ở văn bản khác',
  'Mức độ chưa đúng',
  'Diễn đạt chưa chuẩn',
  'Thiếu nội dung',
  'Sai số liệu',
]
