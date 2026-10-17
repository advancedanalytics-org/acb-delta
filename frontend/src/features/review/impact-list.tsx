import { ChevronDown, FileText } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import type { Impact, ImpactStatus, InternalDocument } from '@/api/types'
import { EmptyState } from '@/components/query-states'
import { ImpactStatusBadge, ImpactTypeLabel, SeverityBadge } from '@/components/status-badges'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { cn } from '@/lib/utils'

export type StatusFilter = 'all' | ImpactStatus

const filters: { value: StatusFilter; label: string }[] = [
  { value: 'all', label: 'Tất cả' },
  { value: 'pending', label: 'Chờ duyệt' },
  { value: 'accepted', label: 'Chấp nhận' },
  { value: 'rejected', label: 'Từ chối' },
]

interface ImpactListProps {
  impacts: Impact[]
  documents: InternalDocument[]
  selectedId: string | undefined
  onSelect: (impactId: string) => void
  filter: StatusFilter
  onFilterChange: (filter: StatusFilter) => void
}

export function ImpactList({ impacts, documents, selectedId, onSelect, filter, onFilterChange }: ImpactListProps) {
  const selectedRef = useRef<HTMLButtonElement>(null)
  const [collapsedDocIds, setCollapsedDocIds] = useState<Set<string>>(() => new Set())

  // Automatically expand document if the selected impact is inside it
  useEffect(() => {
    if (selectedId) {
      const parentDoc = documents.find((doc) =>
        impacts.some((i) => i.id === selectedId && i.documentId === doc.id),
      )
      if (parentDoc) {
        setCollapsedDocIds((prev) => {
          if (prev.has(parentDoc.id)) {
            const next = new Set(prev)
            next.delete(parentDoc.id)
            return next
          }
          return prev
        })
      }
    }
  }, [selectedId, documents, impacts])

  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: 'nearest' })
  }, [selectedId, collapsedDocIds])

  const toggleDoc = (docId: string) => {
    setCollapsedDocIds((prev) => {
      const next = new Set(prev)
      if (next.has(docId)) {
        next.delete(docId)
      } else {
        next.add(docId)
      }
      return next
    })
  }

  const groups = documents
    .map((doc) => ({ doc, items: impacts.filter((impact) => impact.documentId === doc.id) }))
    .filter((group) => group.items.length > 0)

  return (
    <div className="flex h-full flex-col">
      <div className="border-b px-3 py-2">
        <ToggleGroup
          type="single"
          value={filter}
          onValueChange={(value) => value && onFilterChange(value as StatusFilter)}
          variant="outline"
          size="sm"
          aria-label="Lọc theo trạng thái"
          className="w-full"
        >
          {filters.map(({ value, label }) => (
            <ToggleGroupItem key={value} value={value} className="flex-1 px-1 text-xs">
              {label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {groups.length === 0 && (
          <EmptyState title="Không có tác động phù hợp" description="Thử chọn bộ lọc trạng thái khác." />
        )}
        {groups.map(({ doc, items }) => {
          const isCollapsed = collapsedDocIds.has(doc.id)
          return (
            <section key={doc.id} aria-label={doc.title} className="border-b last:border-b-0">
              <header className="sticky top-0 z-10 bg-card/95 backdrop-blur-sm">
                <button
                  type="button"
                  onClick={() => toggleDoc(doc.id)}
                  aria-expanded={!isCollapsed}
                  title={isCollapsed ? 'Mở rộng danh sách tác động' : 'Thu gọn danh sách tác động'}
                  className="flex w-full cursor-pointer items-start gap-2 px-3 py-2 text-left transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-1">
                      <p className="text-xs font-medium text-muted-foreground">{doc.code}</p>
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono text-xs text-muted-foreground">{items.length}</span>
                        <ChevronDown
                          className={cn(
                            'size-3.5 text-muted-foreground transition-transform duration-200',
                            isCollapsed && '-rotate-90',
                          )}
                          aria-hidden
                        />
                      </div>
                    </div>
                    <p className="truncate text-sm font-medium" title={doc.title}>
                      {doc.title}
                    </p>
                  </div>
                </button>
              </header>
              {!isCollapsed && (
                <ul className="flex flex-col gap-1 px-2 pt-1 pb-2">
                  {items.map((impact) => {
                    const isSelected = impact.id === selectedId
                    return (
                      <li key={impact.id}>
                        <button
                          ref={isSelected ? selectedRef : undefined}
                          type="button"
                          onClick={() => onSelect(impact.id)}
                          aria-current={isSelected ? 'true' : undefined}
                          className={cn(
                            'flex w-full flex-col gap-2 rounded-md border border-transparent px-3 py-2 text-left transition-colors duration-150 outline-none focus-visible:ring-3 focus-visible:ring-ring/50',
                            isSelected ? 'border-primary/40 bg-accent' : 'hover:bg-muted',
                          )}
                        >
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium">{impact.location}</span>
                            <SeverityBadge severity={impact.severity} className="ml-auto" />
                          </div>
                          <p className="line-clamp-2 text-xs text-muted-foreground">{impact.affectedText}</p>
                          <div className="flex items-center justify-between gap-2">
                            <ImpactTypeLabel type={impact.type} />
                            <ImpactStatusBadge status={impact.status} />
                          </div>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </section>
          )
        })}
      </div>
    </div>
  )
}
