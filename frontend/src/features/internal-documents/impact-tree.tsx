import {
  ArrowUpRight,
  BookText,
  FileText,
  Landmark,
  type LucideIcon,
  Maximize2,
  Minimize2,
  Workflow,
} from 'lucide-react'
import { useMemo, useState } from 'react'

import type { InternalDocument } from '@/api/types'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { buildTree, type TreeLevel, type TreeNode } from './impact-tree-data'

// Thông tư → Quy định → Quy trình → Biểu mẫu, one colour + icon per level.
const LEVEL: Record<TreeLevel, { card: string; badge: string; Icon: LucideIcon }> = {
  1: { card: 'border-blue-500/50 bg-blue-500/5', badge: 'bg-blue-500/10 text-blue-600 dark:text-blue-400', Icon: Landmark },
  2: { card: 'border-emerald-500/50 bg-emerald-500/5', badge: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400', Icon: BookText },
  3: { card: 'border-amber-500/50 bg-amber-500/5', badge: 'bg-amber-500/10 text-amber-600 dark:text-amber-400', Icon: Workflow },
  4: { card: 'border-rose-500/50 bg-rose-500/5', badge: 'bg-rose-500/10 text-rose-600 dark:text-rose-400', Icon: FileText },
}

export function ImpactTree({
  doc,
  docs,
  onOpenClause,
}: {
  doc: InternalDocument
  docs: InternalDocument[]
  onOpenClause?: (clauseId: string) => void
}) {
  const [full, setFull] = useState(false)
  const tree = useMemo(() => buildTree(doc, { full, docs }), [doc, docs, full])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <style>{TREE_CSS}</style>

      {/* toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/20 px-4 py-2 md:px-6">
        <Button variant="outline" size="sm" className="h-8 gap-1.5 text-xs" onClick={() => setFull((f) => !f)}>
          {full ? <Minimize2 className="size-3.5" /> : <Maximize2 className="size-3.5" />}
          {full ? 'Chỉ nhánh này' : 'Xem toàn bộ cây'}
        </Button>
        <p className="text-[11px] font-medium text-muted-foreground">
          Thông tư → Quy định → Quy trình → Biểu mẫu
        </p>
      </div>

      {/* canvas */}
      <div className="min-h-0 flex-1 overflow-auto bg-muted/10 p-6">
        <ul className="ria-tree min-w-max">
          <Branch node={tree} onOpenClause={onOpenClause} />
        </ul>
      </div>
    </div>
  )
}

interface BranchProps {
  node: TreeNode
  onOpenClause?: (clauseId: string) => void
}

function Branch({ node, onOpenClause }: BranchProps) {
  return (
    <li>
      <NodeCard node={node} onOpenClause={onOpenClause} />
      {node.children && node.children.length > 0 && (
        <ul>
          {node.children.map((child) => (
            <Branch key={child.id} node={child} onOpenClause={onOpenClause} />
          ))}
        </ul>
      )}
    </li>
  )
}

function NodeCard({ node, onOpenClause }: BranchProps) {
  const { card, badge, Icon } = LEVEL[node.level]
  const canOpen = Boolean(node.clauseId && onOpenClause)
  const open = () => node.clauseId && onOpenClause?.(node.clauseId)

  return (
    <div
      className={cn(
        'relative z-10 w-44 rounded-xl border-2 p-3 text-center shadow-sm transition-all',
        card,
        canOpen && 'cursor-pointer hover:-translate-y-0.5 hover:shadow-md hover:ring-2 hover:ring-primary/50',
      )}
      onClick={canOpen ? open : undefined}
      role={canOpen ? 'button' : undefined}
      tabIndex={canOpen ? 0 : undefined}
      onKeyDown={
        canOpen
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                open()
              }
            }
          : undefined
      }
      title={canOpen ? 'Mở trong Nội dung chi tiết' : undefined}
    >
      {canOpen && <ArrowUpRight className="absolute right-1.5 top-1.5 size-3.5 text-muted-foreground" aria-hidden />}
      <div className="flex items-center justify-center gap-2">
        <span className={cn('flex size-6 shrink-0 items-center justify-center rounded-md', badge)}>
          <Icon className="size-3.5" aria-hidden />
        </span>
        <span className="truncate text-xs font-semibold text-foreground" title={node.label}>
          {node.label}
        </span>
      </div>
      {node.sublabel && <p className="mt-1 line-clamp-2 text-[11px] text-muted-foreground">{node.sublabel}</p>}
    </div>
  )
}

/** Classic CSS org-chart connectors, scoped to `.ria-tree`; colours follow the theme border token. */
const TREE_CSS = `
.ria-tree, .ria-tree ul { display: flex; margin: 0; padding: 0; list-style: none; }
.ria-tree { justify-content: center; }
.ria-tree ul { justify-content: center; position: relative; padding-top: 1.75rem; }
.ria-tree li { display: flex; flex-direction: column; align-items: center; position: relative; padding: 1.75rem 0.75rem 0; }
.ria-tree li::before, .ria-tree li::after {
  content: ''; position: absolute; top: 0; right: 50%; width: 50%; height: 1.75rem; border-top: 2px solid var(--border);
}
.ria-tree li::after { right: auto; left: 50%; border-left: 2px solid var(--border); }
.ria-tree li:only-child::before, .ria-tree li:only-child::after { display: none; }
.ria-tree li:first-child::before, .ria-tree li:last-child::after { border: 0 none; }
.ria-tree li:last-child::before { border-right: 2px solid var(--border); }
.ria-tree ul::before { content: ''; position: absolute; top: 0; left: 50%; height: 1.75rem; border-left: 2px solid var(--border); }
.ria-tree > li { padding-top: 0; }
.ria-tree > li::before, .ria-tree > li::after { display: none; }
`
