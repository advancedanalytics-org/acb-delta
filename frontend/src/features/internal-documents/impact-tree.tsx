import {
  Check,
  FileText,
  type LucideIcon,
  Maximize2,
  Minimize2,
  Pencil,
  Plus,
  RotateCcw,
  Settings,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useState, type ReactNode } from 'react'

import type { InternalDocument } from '@/api/types'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { buildTree, suggestTree, type TreeLevel, type TreeNode } from './impact-tree-data'

const LEVEL: Record<TreeLevel, { card: string; badge: string; Icon: LucideIcon }> = {
  1: { card: 'border-blue-500/50 bg-blue-500/5', badge: 'bg-blue-500/10 text-blue-600 dark:text-blue-400', Icon: FileText },
  2: { card: 'border-emerald-500/50 bg-emerald-500/5', badge: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400', Icon: FileText },
  3: { card: 'border-amber-500/50 bg-amber-500/5', badge: 'bg-amber-500/10 text-amber-600 dark:text-amber-400', Icon: Settings },
  4: { card: 'border-rose-500/50 bg-rose-500/5', badge: 'bg-rose-500/10 text-rose-600 dark:text-rose-400', Icon: FileText },
}

// ---- immutable tree helpers ---------------------------------------------------------------
function mapTree(node: TreeNode, fn: (n: TreeNode) => TreeNode): TreeNode {
  const next = fn(node)
  return next.children ? { ...next, children: next.children.map((c) => mapTree(c, fn)) } : next
}
function renameNode(tree: TreeNode, id: string, label: string): TreeNode {
  return mapTree(tree, (n) => (n.id === id ? { ...n, label } : n))
}
function addChild(tree: TreeNode, parentId: string): TreeNode {
  return mapTree(tree, (n) => {
    if (n.id !== parentId) return n
    const level = Math.min(4, n.level + 1) as TreeLevel
    const child: TreeNode = {
      id: `${parentId}-n-${Date.now().toString(36)}`,
      label: level === 3 ? 'Quy trình mới' : level === 4 ? 'Biểu mẫu mới' : 'Nhánh mới',
      sublabel: level === 3 ? 'Quy trình nghiệp vụ' : level === 4 ? 'Biểu mẫu tài liệu' : undefined,
      level,
      isNew: true,
    }
    return { ...n, children: [...(n.children ?? []), child] }
  })
}
function removeNode(tree: TreeNode, id: string): TreeNode {
  const prune = (node: TreeNode): TreeNode =>
    node.children ? { ...node, children: node.children.filter((c) => c.id !== id).map(prune) } : node
  return prune(tree)
}

const storageKey = (docId: string) => `impact-tree:${docId}`

export function ImpactTree({ doc, docs }: { doc: InternalDocument; docs: InternalDocument[] }) {
  const [full, setFull] = useState(false)
  const [editing, setEditing] = useState(false)
  const [aiLoading, setAiLoading] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [tree, setTree] = useState<TreeNode>(() => buildTree(doc, { full: false, docs }))

  // Load the saved branch for this document (or a fresh one) when the selection changes.
  useEffect(() => {
    let saved: TreeNode | null = null
    try {
      const raw = localStorage.getItem(storageKey(doc.id))
      if (raw) saved = JSON.parse(raw) as TreeNode
    } catch {
      saved = null
    }
    setTree(saved ?? buildTree(doc, { full: false, docs }))
    setEditingId(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc.id])

  // Persist the focused branch as it is edited.
  useEffect(() => {
    try {
      localStorage.setItem(storageKey(doc.id), JSON.stringify(tree))
    } catch {
      // storage blocked; keep the in-memory tree
    }
  }, [tree, doc.id])

  const fullTree = useMemo(() => buildTree(doc, { full: true, docs }), [doc, docs])
  const shown = full ? fullTree : tree

  const resetBranch = () => {
    const fresh = buildTree(doc, { full: false, docs })
    setTree(fresh)
    setEditingId(null)
    try {
      localStorage.removeItem(storageKey(doc.id))
    } catch {
      // ignore
    }
  }

  const runAiSuggest = () => {
    if (aiLoading) return
    setAiLoading(true)
    window.setTimeout(() => {
      setTree((current) => suggestTree(current))
      setAiLoading(false)
    }, 1200)
  }

  const branchProps = {
    editing: editing && !full,
    editingId,
    setEditingId,
    onRename: (id: string, label: string) => setTree((t) => renameNode(t, id, label)),
    onAdd: (id: string) => setTree((t) => addChild(t, id)),
    onRemove: (id: string) => setTree((t) => removeNode(t, id)),
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <style>{TREE_CSS}</style>

      {/* toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/20 px-4 py-2 md:px-6">
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" className="h-8 gap-1.5 text-xs" onClick={() => setFull((f) => !f)}>
            {full ? <Minimize2 className="size-3.5" /> : <Maximize2 className="size-3.5" />}
            {full ? 'Chỉ nhánh này' : 'Xem toàn bộ cây'}
          </Button>
          <Button
            size="sm"
            className="h-8 gap-1.5 bg-gradient-to-r from-violet-600 to-indigo-600 text-xs text-white hover:brightness-110"
            onClick={runAiSuggest}
            disabled={aiLoading || full}
          >
            <Sparkles className={cn('size-3.5', aiLoading && 'animate-pulse')} />
            {aiLoading ? 'Đang phân tích…' : 'AI gợi ý'}
          </Button>
        </div>
        <div className="flex items-center gap-2">
          {!full && (
            <Button variant="ghost" size="sm" className="h-8 gap-1.5 text-xs" onClick={resetBranch} title="Khôi phục mặc định">
              <RotateCcw className="size-3.5" />
              Khôi phục
            </Button>
          )}
          <Button
            variant={editing && !full ? 'default' : 'outline'}
            size="sm"
            className="h-8 gap-1.5 text-xs"
            onClick={() => setEditing((e) => !e)}
            disabled={full}
          >
            <Pencil className="size-3.5" />
            {editing && !full ? 'Xong' : 'Chỉnh sửa'}
          </Button>
        </div>
      </div>

      {/* canvas */}
      <div className="min-h-0 flex-1 overflow-auto bg-muted/10 p-6">
        <ul className="ria-tree min-w-max">
          <Branch node={shown} {...branchProps} />
        </ul>
      </div>
    </div>
  )
}

interface BranchProps {
  node: TreeNode
  editing: boolean
  editingId: string | null
  setEditingId: (id: string | null) => void
  onRename: (id: string, label: string) => void
  onAdd: (id: string) => void
  onRemove: (id: string) => void
}

function Branch({ node, ...rest }: BranchProps) {
  return (
    <li>
      <NodeCard node={node} {...rest} />
      {node.children && node.children.length > 0 && (
        <ul>
          {node.children.map((child) => (
            <Branch key={child.id} node={child} {...rest} />
          ))}
        </ul>
      )}
    </li>
  )
}

function NodeCard({ node, editing, editingId, setEditingId, onRename, onAdd, onRemove }: BranchProps) {
  const { card, badge, Icon } = LEVEL[node.level]
  const isEditing = editingId === node.id
  const [draft, setDraft] = useState(node.label)

  useEffect(() => {
    if (isEditing) setDraft(node.label)
  }, [isEditing, node.label])

  const save = () => {
    const value = draft.trim()
    if (value) onRename(node.id, value)
    setEditingId(null)
  }

  return (
    <div
      className={cn(
        'relative z-10 w-44 rounded-xl border-2 p-3 text-center shadow-sm transition-colors',
        card,
        node.isNew && 'ring-2 ring-primary/40',
      )}
    >
      <div className="flex items-center justify-center gap-2">
        <span className={cn('flex size-6 shrink-0 items-center justify-center rounded-md', badge)}>
          <Icon className="size-3.5" aria-hidden />
        </span>
        {isEditing ? (
          <input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={save}
            onKeyDown={(e) => {
              if (e.key === 'Enter') save()
              if (e.key === 'Escape') setEditingId(null)
            }}
            className="w-full rounded border bg-background px-1 py-0.5 text-xs font-semibold outline-none focus:border-primary"
          />
        ) : (
          <span className="truncate text-xs font-semibold text-foreground" title={node.label}>
            {node.label}
          </span>
        )}
      </div>
      {node.sublabel && <p className="mt-1 line-clamp-2 text-[11px] text-muted-foreground">{node.sublabel}</p>}

      {editing && (
        <div className="mt-2 flex items-center justify-center gap-1 border-t pt-2">
          {isEditing ? (
            <>
              <IconBtn label="Lưu" onClick={save}>
                <Check className="size-3.5 text-emerald-600" />
              </IconBtn>
              <IconBtn label="Hủy" onClick={() => setEditingId(null)}>
                <X className="size-3.5" />
              </IconBtn>
            </>
          ) : (
            <>
              <IconBtn label="Đổi tên" onClick={() => setEditingId(node.id)}>
                <Pencil className="size-3.5" />
              </IconBtn>
              {node.level < 4 && (
                <IconBtn label="Thêm nhánh con" onClick={() => onAdd(node.id)}>
                  <Plus className="size-3.5" />
                </IconBtn>
              )}
              {node.level > 1 && (
                <IconBtn label="Xóa" onClick={() => onRemove(node.id)}>
                  <Trash2 className="size-3.5 text-rose-600" />
                </IconBtn>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

function IconBtn({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      className="inline-flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-1 focus-visible:outline-ring"
    >
      {children}
    </button>
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
