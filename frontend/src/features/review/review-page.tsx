import { ChevronDown, ChevronUp, Keyboard } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import type { Impact, InternalDocument } from '@/api/types'
import { EmptyState, ErrorState } from '@/components/query-states'
import { VbplStatusBadge } from '@/components/status-badges'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { useDecide, useDocuments, useImpacts, useUndoDecision, useVbpls } from '@/hooks/queries'
import { useCurrentUser } from '@/hooks/use-current-user'
import { formatDate } from '@/lib/format'
import { actionLabel } from '@/lib/labels'

import type { DecisionRequest } from './impact-detail'
import { ImpactList, type StatusFilter } from './impact-list'
import { PdfViewer } from './pdf-viewer'
import { ShortcutHelpDialog } from './shortcut-help-dialog'
import { useReviewShortcuts } from './use-review-shortcuts'

export function ReviewPage() {
  const { vbplId } = useParams()
  const [params, setParams] = useSearchParams()
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [helpOpen, setHelpOpen] = useState(false)

  const vbpls = useVbpls()
  const impacts = useImpacts(vbplId)
  const documents = useDocuments()
  const decide = useDecide()
  const undo = useUndoDecision()
  const { reviewer } = useCurrentUser()

  const vbpl = vbpls.data?.find((v) => v.id === vbplId)
  const all = impacts.data ?? []
  const docs = documents.data ?? []
  // Keep list order stable and grouped by document, keeping any remaining impacts at the end.
  const matchedFromDocs = docs.flatMap((doc) => all.filter((impact) => impact.documentId === doc.id))
  const remainingImpacts = all.filter((impact) => !docs.some((doc) => doc.id === impact.documentId))
  const ordered = [...matchedFromDocs, ...remainingImpacts]
  const visible = filter === 'all' ? ordered : ordered.filter((impact) => impact.status === filter)

  const requestedId = params.get('impact')
  const selected = ordered.find((impact) => impact.id === requestedId) ?? visible[0] ?? ordered[0]
  const fallbackDoc: InternalDocument | undefined = selected
    ? {
        id: selected.documentId,
        code: selected.documentId,
        title: selected.documentId,
        department: 'Ban Pháp chế',
        version: 'v1.0',
        effectiveDate: new Date().toISOString().slice(0, 10),
        pageCount: 1,
        pdfUrl: `/api/documents/${encodeURIComponent(selected.documentId)}/pdf`,
      }
    : undefined
  const selectedDoc: InternalDocument | undefined =
    docs.find((doc) => doc.id === selected?.documentId) ?? fallbackDoc
  const reviewed = all.filter((impact) => impact.status !== 'pending').length

  const select = (impactId: string) =>
    setParams(
      (current) => {
        current.set('impact', impactId)
        return current
      },
      { replace: true },
    )

  const step = (offset: number) => {
    if (visible.length === 0) return
    const index = visible.findIndex((impact) => impact.id === selected?.id)
    const next = visible[Math.min(Math.max(index + offset, 0), visible.length - 1)]
    if (next) select(next.id)
  }

  /** After a decision, move to the next pending impact (wrapping), so review flows without the mouse. */
  const advanceFrom = (current: Impact) => {
    const index = ordered.findIndex((impact) => impact.id === current.id)
    const rest = [...ordered.slice(index + 1), ...ordered.slice(0, index)]
    const next = rest.find((impact) => impact.status === 'pending')
    if (next) select(next.id)
  }

  const onDecide = async (impact: Impact, request: DecisionRequest, autoAdvance = false) => {
    if (!reviewer) return
    if (autoAdvance) {
      advanceFrom(impact)
    } else {
      select(impact.id)
    }
    try {
      const decision = await decide.mutateAsync({
        input: { impactId: impact.id, reviewerId: reviewer.id, ...request },
        impact,
        reviewer,
      })
      toast.success(`${actionLabel[request.action]}: ${impact.location}`, {
        description: selectedDoc ? `${selectedDoc.code}` : undefined,
        duration: 3000,
        action: {
          label: 'Hoàn tác',
          onClick: () => {
            undo.mutate({ decision, previous: impact })
            select(impact.id)
          },
        },
      })
    } catch (error) {
      toast.error('Không lưu được quyết định', { description: error instanceof Error ? error.message : undefined })
    }
  }

  useReviewShortcuts({
    j: () => step(1),
    k: () => step(-1),
    a: () => selected && onDecide(selected, { action: 'accept', reasonTags: [] }),
    r: () => selected && onDecide(selected, { action: 'reject', reasonTags: [] }),
    '?': () => setHelpOpen(true),
  })

  const error = vbpls.error ?? impacts.error ?? documents.error
  if (error) {
    return (
      <ErrorState
        error={error}
        onRetry={() => {
          vbpls.refetch()
          impacts.refetch()
          documents.refetch()
        }}
      />
    )
  }

  if (vbpls.isPending || impacts.isPending || documents.isPending) return <ReviewSkeleton />

  if (!vbpl) {
    return (
      <EmptyState
        title="Không tìm thấy VBPL"
        description="Văn bản có thể đã bị gỡ hoặc đường dẫn không đúng."
        className="h-full justify-center"
      />
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b bg-card px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Link to="/" className="hover:text-foreground hover:underline">
              Hộp thư VBPL
            </Link>
            <span aria-hidden>/</span>
            <span>{vbpl.number}</span>
            <span aria-hidden>·</span>
            <span>Hiệu lực {formatDate(vbpl.effectiveDate)}</span>
          </div>
          <h1 className="truncate text-base font-semibold" title={vbpl.title}>
            {vbpl.title}
          </h1>
        </div>
        <VbplStatusBadge status={vbpl.status} />
        <div className="w-48">
          <div className="mb-1 flex justify-between text-xs">
            <span className="text-muted-foreground">Tiến độ duyệt</span>
            <span className="font-medium">
              {reviewed}/{all.length} đã duyệt
            </span>
          </div>
          <Progress value={all.length ? (reviewed / all.length) * 100 : 0} aria-label="Tiến độ duyệt" />
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" onClick={() => step(-1)} aria-label="Tác động trước (K)">
            <ChevronUp aria-hidden />
          </Button>
          <Button variant="ghost" size="icon" onClick={() => step(1)} aria-label="Tác động tiếp theo (J)">
            <ChevronDown aria-hidden />
          </Button>
          <Button variant="ghost" size="icon" onClick={() => setHelpOpen(true)} aria-label="Phím tắt (?)">
            <Keyboard aria-hidden />
          </Button>
        </div>
      </div>

      {/* Three panes from 1024px; below that they stack and the page scrolls. */}
      {all.length === 0 ? (
        <EmptyState
          title={vbpl.status === 'processing' ? 'VBPL đang được phân tích' : 'Không có tác động nào'}
          description={
            vbpl.status === 'processing'
              ? 'Kết quả sẽ xuất hiện ở đây khi luồng phân tích hoàn tất.'
              : 'AI không tìm thấy văn bản nội bộ nào bị ảnh hưởng.'
          }
          className="flex-1 justify-center"
        />
      ) : (
        <div className="grid min-h-0 flex-1 max-lg:overflow-auto lg:grid-cols-[300px_minmax(0,1fr)] xl:grid-cols-[340px_minmax(0,1fr)] max-lg:[&>*]:h-[70dvh]">
          <aside aria-label="Danh sách tác động" className="min-h-0 border-r bg-card">
            <ImpactList
              impacts={visible}
              documents={docs}
              selectedId={selected?.id}
              onSelect={select}
              filter={filter}
              onFilterChange={setFilter}
            />
          </aside>
          <section aria-label="Văn bản nội bộ" className="min-h-0">
            {selectedDoc && (
              <PdfViewer
                key={selectedDoc.id}
                document={selectedDoc}
                impacts={all.filter((impact) => impact.documentId === selectedDoc.id)}
                selectedId={selected?.id}
                onSelect={select}
                onDecide={(impact, request) => onDecide(impact, request)}
                disabled={!reviewer || decide.isPending}
              />
            )}
          </section>
        </div>
      )}

      <ShortcutHelpDialog open={helpOpen} onOpenChange={setHelpOpen} />
    </div>
  )
}

function ReviewSkeleton() {
  return (
    <div className="flex h-full flex-col" aria-busy="true" aria-label="Đang tải">
      <div className="flex items-center gap-4 border-b px-4 py-3">
        <Skeleton className="h-10 flex-1" />
        <Skeleton className="h-10 w-48" />
      </div>
      <div className="grid flex-1 grid-cols-[300px_1fr] gap-4 p-4">
        <div className="space-y-2">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
        <Skeleton className="h-full" />
      </div>
    </div>
  )
}
