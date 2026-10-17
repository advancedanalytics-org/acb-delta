import { FileText } from 'lucide-react'
import { useEffect, useRef } from 'react'

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

  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: 'nearest' })
  }, [selectedId])

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
        {groups.map(({ doc, items }) => (
          <section key={doc.id} aria-label={doc.title} className="border-b last:border-b-0">
            <header className="sticky top-0 z-10 flex items-start gap-2 bg-card/95 px-3 py-2 backdrop-blur-sm">
              <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
              <div className="min-w-0">
                <p className="text-xs font-medium text-muted-foreground">{doc.code}</p>
                <p className="truncate text-sm font-medium" title={doc.title}>
                  {doc.title}
                </p>
              </div>
              <span className="ml-auto text-xs text-muted-foreground">{items.length}</span>
            </header>
            <ul className="flex flex-col gap-1 px-2 pb-2">
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
          </section>
        ))}
      </div>
    </div>
  )
}
