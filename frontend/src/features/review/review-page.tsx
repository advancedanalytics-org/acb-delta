import { ChevronDown, ChevronUp, Download, Keyboard, Loader2 } from 'lucide-react'
import { useRef, useState } from 'react'
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
  const downloadEditedPdfRef = useRef<(() => void) | null>(null)

  const vbpls = useVbpls()
  const impacts = useImpacts(vbplId)
  const documents = useDocuments()
  const decide = useDecide()
  const undo = useUndoDecision()
  const { reviewer } = useCurrentUser()

  const vbpl = vbpls.data?.find((v) => v.id === vbplId)
  const all = impacts.data ?? []
  const docs = documents.data ?? []

  // Ensure any doc referenced in `all` is available in docs list
  const knownDocIds = new Set(docs.map((d) => d.id))
  const synthesizedDocs: InternalDocument[] = Array.from(
    new Set(all.map((imp) => imp.documentId)),
  )
    .filter((docId) => !knownDocIds.has(docId))
    .map((docId) => ({
      id: docId,
      code: docId,
      title: docId,
      department: 'Ban Pháp chế',
      version: 'v1.0',
      effectiveDate: new Date().toISOString().slice(0, 10),
      pageCount: 1,
      pdfUrl: `/api/documents/${encodeURIComponent(docId)}/pdf`,
    }))
  const allDocs = [...docs, ...synthesizedDocs]

  // Keep list order stable and grouped by document, keeping any remaining impacts at the end.
  const matchedFromDocs = allDocs.flatMap((doc) => all.filter((impact) => impact.documentId === doc.id))
  const remainingImpacts = all.filter((impact) => !allDocs.some((doc) => doc.id === impact.documentId))
  const ordered = [...matchedFromDocs, ...remainingImpacts]
  const visible = filter === 'all' ? ordered : ordered.filter((impact) => impact.status === filter)

  const requestedId = params.get('impact')
  const selected = requestedId ? ordered.find((impact) => impact.id === requestedId) : undefined
  const defaultDoc: InternalDocument | undefined =
    allDocs[0] ??
    (all[0]
      ? {
          id: all[0].documentId,
          code: all[0].documentId,
          title: all[0].documentId,
          department: 'Ban Pháp chế',
          version: 'v1.0',
          effectiveDate: new Date().toISOString().slice(0, 10),
          pageCount: 1,
          pdfUrl: `/api/documents/${encodeURIComponent(all[0].documentId)}/pdf`,
        }
      : undefined)
  const selectedDoc: InternalDocument | undefined =
    (selected ? allDocs.find((doc) => doc.id === selected.documentId) : undefined) ?? defaultDoc
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
    const index = selected ? visible.findIndex((impact) => impact.id === selected.id) : -1
    if (index === -1) {
      const next = offset > 0 ? visible[0] : visible[visible.length - 1]
      if (next) select(next.id)
      return
    }
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
    // No accept without an AI proposal (failed or skipped draft): edit or reject instead.
    a: () => {
      const target = requestedId ? ordered.find((i) => i.id === requestedId) : ordered[0]
      if (target && (target.finalText ?? target.suggestedText)) {
        if (!requestedId) select(target.id)
        onDecide(target, { action: 'accept', reasonTags: [] }, true)
      }
    },
    r: () => {
      const target = requestedId ? ordered.find((i) => i.id === requestedId) : ordered[0]
      if (target) {
        if (!requestedId) select(target.id)
        onDecide(target, { action: 'reject', reasonTags: [] }, true)
      }
    },
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

  if (vbpls.isPending || documents.isPending) return <ReviewSkeleton />

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
        <div className="flex items-center gap-1.5">
          {selectedDoc && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                if (downloadEditedPdfRef.current) {
                  downloadEditedPdfRef.current()
                } else {
                  toast.error('Đang chuẩn bị tệp PDF, vui lòng thử lại sau giây lát.')
                }
              }}
              className="h-8 gap-1.5 text-xs font-medium cursor-pointer"
              title={`Tải file PDF ${selectedDoc.code} kèm các đề xuất đã chỉnh sửa`}
            >
              <Download className="size-3.5" />
              <span>Tải PDF đã chỉnh sửa</span>
            </Button>
          )}
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
      {impacts.isPending ? (
        <div className="grid min-h-0 flex-1 max-lg:overflow-auto lg:grid-cols-[300px_minmax(0,1fr)] xl:grid-cols-[340px_minmax(0,1fr)]">
          <aside aria-label="Đang tải danh sách tác động" className="min-h-0 border-r bg-card p-3 space-y-3">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </aside>
          <section aria-label="Đang tải văn bản" className="min-h-0 flex items-center justify-center bg-muted/60">
            <div className="flex flex-col items-center gap-2 text-muted-foreground">
              <Loader2 className="size-6 animate-spin text-primary" />
              <span className="text-xs">Đang tải tác động và văn bản...</span>
            </div>
          </section>
        </div>
      ) : all.length === 0 ? (
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
              documents={allDocs}
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
                selectedId={requestedId ?? undefined}
                onSelect={select}
                onDecide={(impact, request) => onDecide(impact, request)}
                disabled={!reviewer || decide.isPending}
                onRegisterDownload={(fn) => {
                  downloadEditedPdfRef.current = fn
                }}
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
      <div className="flex items-center gap-4 border-b bg-card px-4 py-3">
        <Skeleton className="h-6 w-72" />
        <Skeleton className="h-6 w-24" />
        <div className="ml-auto w-48">
          <Skeleton className="h-4 w-full" />
        </div>
      </div>
      <div className="grid min-h-0 flex-1 lg:grid-cols-[300px_minmax(0,1fr)] xl:grid-cols-[340px_minmax(0,1fr)]">
        <div className="space-y-3 border-r bg-card p-3">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
        <div className="flex flex-col items-center justify-start bg-muted/60 p-4">
          <div className="aspect-[1/1.414] w-full max-w-[960px] bg-white shadow-sm" />
        </div>
      </div>
    </div>
  )
}
