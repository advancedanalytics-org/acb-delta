import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  ChevronUp,
  Download,
  Files,
  FileText,
  Keyboard,
  Loader2,
} from 'lucide-react'
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

  // Documents affected by this specific VBPL
  const affectedDocIds = new Set(all.map((imp) => imp.documentId))
  const affectedDocs = allDocs.filter((doc) => affectedDocIds.has(doc.id))

  // Keep list order stable and grouped by document, keeping any remaining impacts at the end.
  const matchedFromDocs = allDocs.flatMap((doc) => all.filter((impact) => impact.documentId === doc.id))
  const remainingImpacts = all.filter((impact) => !allDocs.some((doc) => doc.id === impact.documentId))
  const ordered = [...matchedFromDocs, ...remainingImpacts]

  const requestedDocId = params.get('doc')
  const requestedId = params.get('impact')

  // Find impact if requested in URL
  const selected = requestedId ? all.find((impact) => impact.id === requestedId) : undefined

  // Determine selected document
  const selectedDoc: InternalDocument | undefined = requestedDocId
    ? allDocs.find((doc) => doc.id === requestedDocId)
    : selected
      ? allDocs.find((doc) => doc.id === selected.documentId)
      : undefined

  // Filter impacts to the selected document if one is selected
  const docImpacts = selectedDoc ? all.filter((impact) => impact.documentId === selectedDoc.id) : []
  const docOrdered = selectedDoc
    ? ordered.filter((impact) => impact.documentId === selectedDoc.id)
    : ordered
  const visible = filter === 'all' ? docOrdered : docOrdered.filter((impact) => impact.status === filter)

  const reviewed = all.filter((impact) => impact.status !== 'pending').length
  const docReviewed = docImpacts.filter((impact) => impact.status !== 'pending').length

  const handleSelectDoc = (docId: string) => {
    setParams(
      (current) => {
        current.set('doc', docId)
        const docPending = all.find((i) => i.documentId === docId && i.status === 'pending')
        const docFirst = docPending ?? all.find((i) => i.documentId === docId)
        if (docFirst) {
          current.set('impact', docFirst.id)
        } else {
          current.delete('impact')
        }
        return current
      },
      { replace: true },
    )
  }

  const handleBackToSelectDoc = () => {
    setParams(
      (current) => {
        current.delete('doc')
        current.delete('impact')
        return current
      },
      { replace: true },
    )
  }

  const select = (impactId: string) =>
    setParams(
      (current) => {
        current.set('impact', impactId)
        const target = all.find((i) => i.id === impactId)
        if (target) {
          current.set('doc', target.documentId)
        }
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
    const index = docOrdered.findIndex((impact) => impact.id === current.id)
    const rest = [...docOrdered.slice(index + 1), ...docOrdered.slice(0, index)]
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
    j: () => {
      if (selectedDoc) step(1)
    },
    k: () => {
      if (selectedDoc) step(-1)
    },
    // No accept without an AI proposal (failed or skipped draft): edit or reject instead.
    a: () => {
      if (!selectedDoc) return
      const target = requestedId ? docOrdered.find((i) => i.id === requestedId) : docOrdered[0]
      if (target && (target.finalText ?? target.suggestedText)) {
        if (!requestedId) select(target.id)
        onDecide(target, { action: 'accept', reasonTags: [] }, true)
      }
    },
    r: () => {
      if (!selectedDoc) return
      const target = requestedId ? docOrdered.find((i) => i.id === requestedId) : docOrdered[0]
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
            {selectedDoc ? (
              <>
                <button
                  onClick={handleBackToSelectDoc}
                  className="hover:text-foreground hover:underline cursor-pointer"
                  title="Quay lại danh sách văn bản nội bộ"
                >
                  {vbpl.number}
                </button>
                <span aria-hidden>/</span>
                <span className="font-semibold text-foreground">{selectedDoc.code}</span>
              </>
            ) : (
              <span>{vbpl.number}</span>
            )}
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
            <span className="text-muted-foreground">
              {selectedDoc ? `Tiến độ (${selectedDoc.code})` : 'Tiến độ tổng thể'}
            </span>
            <span className="font-medium">
              {selectedDoc
                ? `${docReviewed}/${docImpacts.length} đã duyệt`
                : `${reviewed}/${all.length} đã duyệt`}
            </span>
          </div>
          <Progress
            value={
              selectedDoc
                ? docImpacts.length
                  ? (docReviewed / docImpacts.length) * 100
                  : 0
                : all.length
                  ? (reviewed / all.length) * 100
                  : 0
            }
            aria-label="Tiến độ duyệt"
          />
        </div>
        <div className="flex items-center gap-1.5">
          {selectedDoc && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={handleBackToSelectDoc}
                className="h-8 gap-1.5 text-xs font-medium cursor-pointer"
                title="Quay lại danh sách chọn văn bản nội bộ khác"
              >
                <ArrowLeft className="size-3.5" />
                <span>Đổi văn bản</span>
              </Button>

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
            </>
          )}
          {selectedDoc && (
            <>
              <Button variant="ghost" size="icon" onClick={() => step(-1)} aria-label="Tác động trước (K)">
                <ChevronUp aria-hidden />
              </Button>
              <Button variant="ghost" size="icon" onClick={() => step(1)} aria-label="Tác động tiếp theo (J)">
                <ChevronDown aria-hidden />
              </Button>
            </>
          )}
          <Button variant="ghost" size="icon" onClick={() => setHelpOpen(true)} aria-label="Phím tắt (?)">
            <Keyboard aria-hidden />
          </Button>
        </div>
      </div>

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
      ) : !selectedDoc ? (
        /* STEP 1: SELECT DOCUMENT STEP */
        <div className="flex-1 overflow-y-auto bg-muted/20 p-6 md:p-10">
          <div className="mx-auto max-w-4xl space-y-6">
            <div className="space-y-1.5">
              <div className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-primary">
                <Files className="size-4" />
                <span>Bước 1: Lựa chọn văn bản nội bộ</span>
              </div>
              <h2 className="text-2xl font-bold tracking-tight text-foreground">
                Chọn văn bản nội bộ cần duyệt
              </h2>
              <p className="text-sm text-muted-foreground">
                Văn bản quy phạm pháp luật <strong className="font-semibold text-foreground">{vbpl.number}</strong> ảnh hưởng đến{' '}
                <strong className="font-semibold text-foreground">{affectedDocs.length}</strong> văn bản nội bộ dưới đây. Vui lòng chọn văn bản để bắt đầu kiểm tra và phê duyệt các đề xuất chỉnh sửa của AI.
              </p>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              {affectedDocs.map((doc) => {
                const docImps = all.filter((i) => i.documentId === doc.id)
                const docPending = docImps.filter((i) => i.status === 'pending').length
                const docDone = docPending === 0 && docImps.length > 0
                const docDoneCount = docImps.length - docPending

                return (
                  <div
                    key={doc.id}
                    onClick={() => handleSelectDoc(doc.id)}
                    onKeyDown={(e) => e.key === 'Enter' && handleSelectDoc(doc.id)}
                    tabIndex={0}
                    role="button"
                    className="group relative flex flex-col justify-between rounded-xl border bg-card p-5 shadow-sm transition-all duration-200 hover:border-primary/60 hover:shadow-md cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-primary"
                  >
                    <div className="space-y-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-center gap-2.5">
                          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary group-hover:bg-primary group-hover:text-primary-foreground transition-colors">
                            <FileText className="size-5" />
                          </div>
                          <div>
                            <h3 className="font-bold text-base text-foreground group-hover:text-primary transition-colors">
                              {doc.code}
                            </h3>
                            <p className="text-xs text-muted-foreground">{doc.department}</p>
                          </div>
                        </div>
                        {docDone ? (
                          <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium bg-emerald-500/10 text-emerald-600 border border-emerald-500/20">
                            <Check className="size-3" />
                            Đã duyệt xong
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/30">
                            {docPending} chờ duyệt
                          </span>
                        )}
                      </div>

                      <div>
                        <p className="line-clamp-2 text-sm font-medium text-foreground" title={doc.title}>
                          {doc.title}
                        </p>
                        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                          <span>Phiên bản: <strong className="font-medium text-foreground">{doc.version}</strong></span>
                          <span>·</span>
                          <span>Hiệu lực: <strong className="font-medium text-foreground">{formatDate(doc.effectiveDate)}</strong></span>
                          {doc.pageCount ? (
                            <>
                              <span>·</span>
                              <span>{doc.pageCount} trang</span>
                            </>
                          ) : null}
                        </div>
                      </div>
                    </div>

                    <div className="mt-5 pt-4 border-t space-y-3">
                      <div className="space-y-1.5">
                        <div className="flex justify-between text-xs">
                          <span className="text-muted-foreground">Tiến độ xử lý</span>
                          <span className="font-medium">
                            {docDoneCount}/{docImps.length} tác động
                          </span>
                        </div>
                        <Progress
                          value={docImps.length > 0 ? (docDoneCount / docImps.length) * 100 : 0}
                          className="h-1.5"
                        />
                      </div>

                      <Button
                        variant={docDone ? 'outline' : 'default'}
                        size="sm"
                        className="w-full gap-2 cursor-pointer font-medium"
                      >
                        <span>{docDone ? 'Xem lại văn bản này' : 'Bắt đầu duyệt văn bản này'}</span>
                        <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" />
                      </Button>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      ) : (
        /* STEP 2: REVIEW WORKSPACE FOR SELECTED DOCUMENT */
        <div className="grid min-h-0 flex-1 max-lg:overflow-auto lg:grid-cols-[300px_minmax(0,1fr)] xl:grid-cols-[340px_minmax(0,1fr)] max-lg:[&>*]:h-[70dvh]">
          <aside aria-label="Danh sách tác động" className="min-h-0 border-r bg-card">
            <ImpactList
              impacts={visible}
              documents={[selectedDoc]}
              selectedId={selected?.id}
              onSelect={select}
              filter={filter}
              onFilterChange={setFilter}
            />
          </aside>
          <section aria-label="Văn bản nội bộ" className="min-h-0">
            <PdfViewer
              key={selectedDoc.id}
              document={selectedDoc}
              impacts={docImpacts}
              selectedId={requestedId ?? undefined}
              onSelect={select}
              onDecide={(impact, request) => onDecide(impact, request)}
              disabled={!reviewer || decide.isPending}
              onRegisterDownload={(fn) => {
                downloadEditedPdfRef.current = fn
              }}
            />
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
