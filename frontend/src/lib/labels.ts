import type { DecisionAction, ImpactCategory, ImpactStatus, ImpactType, Severity, VbplStatus } from '@/api/types'

export const vbplStatusLabel: Record<VbplStatus, string> = {
  processing: 'Đang xử lý',
  awaiting_review: 'Chờ duyệt',
  done: 'Hoàn tất',
  failed: 'Lỗi phân tích',
  not_found: 'Không tìm thấy',
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

/** Short plain-language meaning of RIA's category, shown beside the impact type in review. */
export const categoryMeaning: Record<ImpactCategory, string> = {
  VALUE_CHANGE: 'Khác số liệu, hạn mức, thời hạn, số tiền',
  CONTRADICTION: 'Yêu cầu xung đột trong cùng phạm vi',
  ADDITION: 'Thêm yêu cầu mới nội bộ chưa có',
  SCOPE_CHANGE: 'Khác đối tượng, điều kiện hoặc ngoại lệ',
  INDIRECT_IMPACT: 'Liên quan gián tiếp, cần chuyên gia xác minh',
  EQUIVALENT: 'Nội bộ đã đáp ứng, không cần sửa',
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
