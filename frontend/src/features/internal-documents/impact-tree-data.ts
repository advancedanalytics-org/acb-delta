import type { InternalDocument } from '@/api/types'

export type TreeLevel = 1 | 2 | 3 | 4

export interface TreeNode {
  id: string
  label: string
  sublabel?: string
  level: TreeLevel
  /** Marked on nodes produced by the "AI gợi ý" action, for a subtle highlight. */
  isNew?: boolean
  children?: TreeNode[]
}

type DocLike = Pick<InternalDocument, 'code' | 'id' | 'title'>

const ROOT_LABEL = 'Thông tư 31/2026/TT-NHNN'
const ROOT_SUBLABEL = 'Văn bản pháp lý mới'

function codeOf(doc: DocLike): string {
  return (doc.code || doc.id || 'QĐ').toUpperCase()
}

/** A regulation (level 2) with three business processes, each carrying two document templates. */
function regulationNode(doc: DocLike): TreeNode {
  const code = codeOf(doc)
  const processes: TreeNode[] = [1, 2, 3].map((p) => ({
    id: `${code}-qt-${p}`,
    label: `Quy trình ${code}-${p}`,
    sublabel: 'Quy trình nghiệp vụ',
    level: 3,
    children: [1, 2].map((b) => ({
      id: `${code}-qt-${p}-bm-${b}`,
      label: `Biểu mẫu ${code}-${p}-0${b}`,
      sublabel: 'Biểu mẫu tài liệu',
      level: 4,
    })),
  }))
  return {
    id: `qd-${code}`,
    label: doc.code || doc.id,
    sublabel: doc.title,
    level: 2,
    children: processes,
  }
}

/** The impact tree: Thông tư → Quy định → Quy trình → Biểu mẫu. `full` fans out every regulation. */
export function buildTree(doc: DocLike, options: { full: boolean; docs: DocLike[] }): TreeNode {
  const regulations = options.full && options.docs.length > 0 ? options.docs : [doc]
  return {
    id: 'root-thong-tu',
    label: ROOT_LABEL,
    sublabel: ROOT_SUBLABEL,
    level: 1,
    children: regulations.map(regulationNode),
  }
}

/**
 * Produce a restructured ("optimized") variant of the tree. Each regulation's processes are
 * consolidated into two streamlined processes, each with two forms, all flagged `isNew`.
 * Pure and client-side — no network, no model call.
 */
export function suggestTree(tree: TreeNode): TreeNode {
  const optimizeRegulation = (reg: TreeNode): TreeNode => {
    const code = reg.label.toUpperCase()
    const streams: { label: string; sublabel: string }[] = [
      { label: `Quy trình ${code}-Hợp nhất`, sublabel: 'Quy trình nghiệp vụ hợp nhất' },
      { label: `Quy trình ${code}-Kiểm soát`, sublabel: 'Quy trình kiểm soát tuân thủ' },
    ]
    const processes: TreeNode[] = streams.map((s, i) => ({
      id: `${reg.id}-ai-qt-${i + 1}`,
      label: s.label,
      sublabel: s.sublabel,
      level: 3,
      isNew: true,
      children: [1, 2].map((b) => ({
        id: `${reg.id}-ai-qt-${i + 1}-bm-${b}`,
        label: `Biểu mẫu ${code}-A${i + 1}-0${b}`,
        sublabel: 'Biểu mẫu tài liệu',
        level: 4,
        isNew: true,
      })),
    }))
    return { ...reg, children: processes }
  }
  return { ...tree, children: (tree.children ?? []).map(optimizeRegulation) }
}
