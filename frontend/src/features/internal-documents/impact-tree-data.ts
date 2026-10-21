import type { DocumentClause, InternalDocument } from '@/api/types'

export type TreeLevel = 1 | 2 | 3 | 4

export interface TreeNode {
  id: string
  label: string
  sublabel?: string
  level: TreeLevel
  /** Set on leaves that map to a real clause/article, so a click can open it in the detail tab. */
  clauseId?: string
  children?: TreeNode[]
}

type DocLike = Pick<InternalDocument, 'code' | 'id' | 'title'>

const ROOT_LABEL = 'Thông tư 31/2026/TT-NHNN'
const ROOT_SUBLABEL = 'Văn bản pháp lý mới'

function codeOf(doc: DocLike): string {
  return (doc.code || doc.id || 'QĐ').toUpperCase()
}

// ---- real clause structure (Chương / Điều) ---------------------------------------------

/** One article (Điều) with the clauses nested under it. Shared with the detail tab so node ids line up. */
export interface ArticleGroup {
  id: string
  numbering: string
  heading?: string | null
  page?: number | null
  chapterHeading?: string | null
  clauses: DocumentClause[]
  /** Added by the detail tab's search filter; not produced by `groupClauses`. */
  matchingClauses?: DocumentClause[]
}

/**
 * Group a flat clause list into Chương + Điều, exactly as the "Nội dung chi tiết" tab renders them.
 * Each article's `id` is the starting clause's `clause_id`, which the detail tab anchors with
 * `id="article-<clause_id>"` — so a tree leaf carrying that id can scroll straight to it.
 */
export function groupClauses(clauses: DocumentClause[]): {
  articleGroups: ArticleGroup[]
  chapters: { numbering: string; heading: string }[]
} {
  const groups: ArticleGroup[] = []
  const chapterList: { numbering: string; heading: string }[] = []
  let currentChapter: string | null = null
  let currentArticle: ArticleGroup | null = null

  for (const c of clauses) {
    if (c.level === 'chapter') {
      currentChapter = c.heading || `Chương ${c.numbering}`
      chapterList.push({ numbering: c.numbering, heading: currentChapter })
    } else if (c.level === 'article' || (!currentArticle && c.level !== 'part')) {
      currentArticle = {
        id: c.clause_id,
        numbering: c.numbering,
        heading: c.heading || (c.text.length < 80 ? c.text : `Điều ${c.numbering}`),
        page: c.page,
        chapterHeading: currentChapter,
        clauses: [c],
      }
      groups.push(currentArticle)
    } else if (currentArticle) {
      currentArticle.clauses.push(c)
    } else {
      currentArticle = {
        id: c.clause_id,
        numbering: c.numbering,
        heading: c.heading || `Mục ${c.numbering}`,
        page: c.page,
        chapterHeading: currentChapter,
        clauses: [c],
      }
      groups.push(currentArticle)
    }
  }

  return { articleGroups: groups, chapters: chapterList }
}

// ---- demo document-type branches (Quy trình → Biểu mẫu) ---------------------------------
//
// The impact graph shows how an external circular cascades through the bank's document types
// (Thông tư → Quy định → Quy trình → Biểu mẫu), not the legal clause structure (Chương/Điều).
// Internal documents are mock data for the hackathon, so these processes and forms are a fixed,
// realistic demo sample keyed by the document (by id or code). Unknown documents fall back to a
// generic two-process shape.

interface DemoBranch {
  process: string
  forms: string[]
}

/** Curated demo branches per known document, keyed by the uppercased id (and code where it differs). */
const DEMO_BRANCHES: Record<string, DemoBranch[]> = {
  'DOC-CV-01': [
    {
      process: 'Quy trình thẩm định và phê duyệt khoản vay',
      forms: ['Biểu mẫu đề nghị vay vốn', 'Biểu mẫu tờ trình thẩm định tín dụng'],
    },
    {
      process: 'Quy trình giải ngân và quản lý khoản vay',
      forms: ['Biểu mẫu khế ước nhận nợ', 'Biểu mẫu theo dõi thu hồi nợ'],
    },
  ],
  'DOC-KYC-02': [
    {
      process: 'Quy trình định danh khách hàng (KYC)',
      forms: ['Biểu mẫu thu thập thông tin khách hàng', 'Biểu mẫu đối chiếu giấy tờ định danh'],
    },
    {
      process: 'Quy trình rà soát rủi ro và báo cáo',
      forms: ['Biểu mẫu đánh giá rủi ro khách hàng', 'Biểu mẫu báo cáo giao dịch đáng ngờ'],
    },
  ],
  'DOC-THE-03': [
    {
      process: 'Quy trình phát hành và kích hoạt thẻ',
      forms: ['Biểu mẫu đăng ký mở thẻ tín dụng', 'Biểu mẫu xác nhận hạn mức thẻ'],
    },
    {
      process: 'Quy trình thu phí và tính lãi',
      forms: ['Biểu mẫu biểu phí dịch vụ thẻ', 'Biểu mẫu sao kê và tính lãi kỳ'],
    },
  ],
  'DOC-102': [
    {
      process: 'Quy trình rà soát hồ sơ định kỳ',
      forms: ['Biểu mẫu phiếu rà soát hồ sơ KH', 'Biểu mẫu báo cáo hồ sơ tồn đọng'],
    },
    {
      process: 'Quy trình cập nhật thông tin khách hàng',
      forms: ['Biểu mẫu đề nghị cập nhật thông tin', 'Biểu mẫu xử lý thông tin không phù hợp'],
    },
  ],
}

/** Fallback for a document without a curated sample: two generic processes, two forms each. */
const GENERIC_BRANCHES: DemoBranch[] = [
  {
    process: 'Quy trình nghiệp vụ chính',
    forms: ['Biểu mẫu hồ sơ đề nghị', 'Biểu mẫu phiếu kiểm soát'],
  },
  {
    process: 'Quy trình kiểm soát tuân thủ',
    forms: ['Biểu mẫu báo cáo rà soát', 'Biểu mẫu biên bản xử lý'],
  },
]

function branchesFor(doc: DocLike): DemoBranch[] {
  const keys = [doc.id, doc.code].filter(Boolean).map((k) => k!.toUpperCase())
  for (const key of keys) {
    if (DEMO_BRANCHES[key]) return DEMO_BRANCHES[key]
  }
  return GENERIC_BRANCHES
}

/** The Quy trình (level 3) → Biểu mẫu (level 4) children of a regulation, from its demo sample. */
function demoChildren(doc: DocLike): TreeNode[] {
  const code = codeOf(doc)
  return branchesFor(doc).map((branch, p) => ({
    id: `${code}-qt-${p + 1}`,
    label: branch.process,
    sublabel: 'Quy trình nghiệp vụ',
    level: 3,
    children: branch.forms.map((form, b) => ({
      id: `${code}-qt-${p + 1}-bm-${b + 1}`,
      label: form,
      sublabel: 'Biểu mẫu tài liệu',
      level: 4,
    })),
  }))
}

/** A regulation (level 2: the internal document) with its demo Quy trình/Biểu mẫu branches. */
function regulationNode(doc: DocLike): TreeNode {
  return {
    id: `qd-${codeOf(doc)}`,
    label: doc.code || doc.id,
    sublabel: doc.title,
    level: 2,
    children: demoChildren(doc),
  }
}

/**
 * The impact tree by document type: Thông tư → Quy định → Quy trình → Biểu mẫu.
 * Single-branch mode shows only the active document; `full` mode lists every internal document under
 * the circular, each with its own processes and forms, to show one circular's full reach.
 */
export function buildTree(doc: DocLike, options: { full: boolean; docs: DocLike[] }): TreeNode {
  const regulations = options.full && options.docs.length > 0 ? options.docs : [doc]
  return {
    id: 'root-thong-tu',
    label: ROOT_LABEL,
    sublabel: ROOT_SUBLABEL,
    level: 1,
    children: regulations.map((reg) => regulationNode(reg)),
  }
}
