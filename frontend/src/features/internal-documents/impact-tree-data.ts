import type { DocumentClause, InternalDocument } from '@/api/types'

export type TreeLevel = 1 | 2 | 3 | 4

export interface TreeNode {
  id: string
  label: string
  sublabel?: string
  level: TreeLevel
  /** Marked on nodes produced by the "AI gợi ý" action, for a subtle highlight. */
  isNew?: boolean
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

/** Build the real Chương → Điều children of a regulation from its extracted clauses. */
function realChildren(clauses: DocumentClause[]): TreeNode[] {
  const { articleGroups } = groupClauses(clauses)
  if (articleGroups.length === 0) return []

  const out: TreeNode[] = []
  let currentChapter: TreeNode | null = null
  let currentChapterName: string | null = null

  for (const ag of articleGroups) {
    const headingIsArticle = (ag.heading ?? '').trim().toLowerCase().startsWith('điều')
    const articleNode: TreeNode = {
      id: `art-${ag.id}`,
      label: `Điều ${ag.numbering}`,
      sublabel: ag.heading && !headingIsArticle ? ag.heading : undefined,
      level: 4,
      clauseId: ag.id,
    }
    const chapterName = ag.chapterHeading ?? null
    if (chapterName) {
      if (!currentChapter || currentChapterName !== chapterName) {
        currentChapter = { id: `chap-${out.length}-${ag.id}`, label: chapterName, level: 3, children: [] }
        currentChapterName = chapterName
        out.push(currentChapter)
      }
      currentChapter.children!.push(articleNode)
    } else {
      // No chapter above this article: attach it directly under the regulation (one level up).
      out.push({ ...articleNode, level: 3 })
      currentChapter = null
      currentChapterName = null
    }
  }

  return out
}

// ---- synthetic fallback (used when no clauses are available, e.g. mock) ------------------

/** Three business processes, each carrying two document templates. */
function syntheticChildren(doc: DocLike): TreeNode[] {
  const code = codeOf(doc)
  return [1, 2, 3].map((p) => ({
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
}

/** A regulation (level 2) with its real Chương/Điều, or the synthetic fallback when none exist. */
function regulationNode(doc: DocLike, clauses?: DocumentClause[]): TreeNode {
  let children = clauses && clauses.length > 0 ? realChildren(clauses) : []
  if (children.length === 0) children = syntheticChildren(doc)
  return {
    id: `qd-${codeOf(doc)}`,
    label: doc.code || doc.id,
    sublabel: doc.title,
    level: 2,
    children,
  }
}

/**
 * The impact tree: Thông tư → Quy định → Chương → Điều.
 * The active document expands to its real clause structure (`clauses`); in `full` mode every other
 * document is listed at level 2 without children (their clauses are not loaded here).
 */
export function buildTree(
  doc: DocLike,
  options: { full: boolean; docs: DocLike[]; activeDocId?: string; clauses: DocumentClause[] },
): TreeNode {
  const activeId = options.activeDocId ?? doc.id
  const regulations = options.full && options.docs.length > 0 ? options.docs : [doc]
  return {
    id: 'root-thong-tu',
    label: ROOT_LABEL,
    sublabel: ROOT_SUBLABEL,
    level: 1,
    children: regulations.map((reg) =>
      reg.id === activeId
        ? regulationNode(reg, options.clauses)
        : { id: `qd-${codeOf(reg)}`, label: reg.code || reg.id, sublabel: reg.title, level: 2 as TreeLevel },
    ),
  }
}

/**
 * Produce a restructured ("optimized") variant of the tree. Each regulation's children are
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
