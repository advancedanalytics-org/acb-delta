import { Check, FileText, Loader2, PencilLine, Scale, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'

import type { Impact, InternalDocument } from '@/api/types'
import { ImpactStatusBadge, ImpactTypeLabel, SeverityBadge } from '@/components/status-badges'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { reasonTags } from '@/lib/labels'
import { cn } from '@/lib/utils'
import type { DecisionRequest } from './impact-detail'

// react-pdf + our own overlay instead of react-pdf-highlighter-extended, which does not support React 19.
pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString()

const highlightStyle: Record<Impact['status'], string> = {
  pending: 'bg-amber-400/40 hover:bg-amber-400/55',
  accepted: 'bg-emerald-500/45 hover:bg-emerald-500/60',
  rejected: 'bg-rose-500/30 line-through opacity-70 hover:bg-rose-500/45',
}

// Horizontal breathing room around pages; vertical gap is the gap-4 on the page column.
const PAGE_GAP = 16
const MAX_PAGE_WIDTH = 960

function useContainerWidth() {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const element = ref.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  return { ref, width }
}

interface HoveredInfo {
  impact: Impact
  pageNumber: number
  top: number
  left: number
  width: number
  height: number
}

interface PdfViewerProps {
  document: InternalDocument
  impacts: Impact[]
  selectedId: string | undefined
  onSelect: (impactId: string) => void
  onDecide?: (impact: Impact, request: DecisionRequest) => void
  disabled?: boolean
}

function getImpactBoundingBox(bboxes: [number, number, number, number][]) {
  if (!bboxes || bboxes.length === 0) {
    return { x0: 0, y0: 0, x1: 0, y1: 0 }
  }
  let x0 = bboxes[0][0]
  let y0 = bboxes[0][1]
  let x1 = bboxes[0][2]
  let y1 = bboxes[0][3]
  for (let i = 1; i < bboxes.length; i++) {
    x0 = Math.min(x0, bboxes[i][0])
    y0 = Math.min(y0, bboxes[i][1])
    x1 = Math.max(x1, bboxes[i][2])
    y1 = Math.max(y1, bboxes[i][3])
  }
  return { x0, y0, x1, y1 }
}

/** Mount with key={document.id}: page measurements are per document. */
export function PdfViewer({ document, impacts, selectedId, onSelect, onDecide, disabled }: PdfViewerProps) {
  const { ref, width } = useContainerWidth()
  const [numPages, setNumPages] = useState(0)
  // Original page width in PDF points, per page, to convert bbox points to pixels.
  const [pointWidths, setPointWidths] = useState<Record<number, number>>({})
  const selectedRef = useRef<HTMLDivElement>(null)
  const [hoveredInfo, setHoveredInfo] = useState<HoveredInfo | null>(null)
  const hoveredImpactIdRef = useRef<string | null>(null)
  const hoverTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const isEditingRef = useRef(false)

  const clearHoverTimeout = () => {
    if (hoverTimeoutRef.current) {
      clearTimeout(hoverTimeoutRef.current)
      hoverTimeoutRef.current = null
    }
  }

  const handleMouseEnter = (
    impact: Impact,
    pageNumber: number,
    scale: number,
  ) => {
    clearHoverTimeout()
    // If the card is already being shown for this exact impact, KEEP IT FIXED!
    if (hoveredImpactIdRef.current === impact.id) {
      return
    }
    if (isEditingRef.current) {
      return
    }
    hoveredImpactIdRef.current = impact.id
    const bbox = getImpactBoundingBox(impact.bboxes)
    setHoveredInfo({
      impact,
      pageNumber,
      top: bbox.y0 * scale,
      left: bbox.x0 * scale,
      width: (bbox.x1 - bbox.x0) * scale,
      height: (bbox.y1 - bbox.y0) * scale,
    })
  }

  const handleMouseLeave = () => {
    clearHoverTimeout()
    if (isEditingRef.current) return
    hoverTimeoutRef.current = setTimeout(() => {
      hoveredImpactIdRef.current = null
      setHoveredInfo(null)
    }, 250)
  }

  const pageWidth = Math.min(Math.max(width - 2 * PAGE_GAP, 0), MAX_PAGE_WIDTH)
  const selected = impacts.find((impact) => impact.id === selectedId)
  // Clauses without a PDF location (seeded from text) open their card at the top of page 1.
  const selectedPage = selected ? (selected.page ?? 1) : null
  const selectedPageReady = selectedPage != null ? Boolean(pointWidths[selectedPage]) : false

  useEffect(() => {
    if (!selectedPageReady) return
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    selectedRef.current?.scrollIntoView({ block: 'center', behavior: reduceMotion ? 'auto' : 'smooth' })
  }, [selectedId, selectedPageReady, pageWidth])

  // When selection changes, anchor hover card to the selected impact
  useEffect(() => {
    if (!selected || selectedPage == null || !selectedPageReady) return
    const pageNumber = selectedPage
    if (hoveredImpactIdRef.current === selected.id) return
    const scale = pointWidths[pageNumber] ? pageWidth / pointWidths[pageNumber] : 0
    if (scale > 0) {
      hoveredImpactIdRef.current = selected.id
      const bbox = getImpactBoundingBox(selected.bboxes)
      setHoveredInfo({
        impact: selected,
        pageNumber,
        top: bbox.y0 * scale,
        left: bbox.x0 * scale,
        width: (bbox.x1 - bbox.x0) * scale,
        height: (bbox.y1 - bbox.y0) * scale,
      })
    }
  }, [selectedId, selectedPageReady, pageWidth])

  return (
    <div ref={ref} className="h-full overflow-auto bg-muted/60 py-4">
      {pageWidth > 0 && (
        <Document
          file={document.pdfUrl}
          onLoadSuccess={({ numPages }) => setNumPages(numPages)}
          loading={<PageSkeleton width={pageWidth} />}
          error={<p className="p-6 text-center text-sm text-destructive">Không mở được tệp PDF {document.code}.</p>}
          className="flex flex-col items-center gap-4"
        >
          {Array.from({ length: numPages }, (_, index) => {
            const pageNumber = index + 1
            const scale = pointWidths[pageNumber] ? pageWidth / pointWidths[pageNumber] : 0
            return (
              <div
                key={pageNumber}
                className="relative bg-white shadow-[0_1px_2px_oklch(0.3_0.03_258/0.08),0_4px_12px_oklch(0.3_0.03_258/0.08)]"
                style={{ width: pageWidth }}
              >
                <Page
                  pageNumber={pageNumber}
                  width={pageWidth}
                  renderTextLayer={false}
                  renderAnnotationLayer={false}
                  loading={<PageSkeleton width={pageWidth} />}
                  onLoadSuccess={(page) =>
                    setPointWidths((current) => ({ ...current, [pageNumber]: page.originalWidth }))
                  }
                />
                {scale > 0 &&
                  impacts
                    .filter((impact) => impact.page === pageNumber)
                    .map((impact) =>
                      impact.bboxes.map(([x0, y0, x1, y1], boxIndex) => {
                        const isSelected = impact.id === selectedId
                        return (
                          <div
                            key={`${impact.id}-${boxIndex}`}
                            ref={isSelected && boxIndex === 0 ? selectedRef : undefined}
                            onClick={() => {
                              onSelect(impact.id)
                              handleMouseEnter(impact, pageNumber, scale)
                            }}
                            onMouseEnter={() => handleMouseEnter(impact, pageNumber, scale)}
                            onMouseLeave={handleMouseLeave}
                            aria-hidden
                            className={cn(
                              'absolute cursor-pointer mix-blend-multiply transition-colors duration-200',
                              highlightStyle[impact.status],
                              isSelected && (
                                impact.status === 'accepted'
                                  ? 'bg-emerald-500/65 z-10'
                                  : impact.status === 'rejected'
                                    ? 'bg-rose-500/50 z-10'
                                    : 'bg-amber-400/65 z-10'
                              ),
                            )}
                            style={{
                              left: x0 * scale,
                              top: y0 * scale,
                              width: (x1 - x0) * scale,
                              height: (y1 - y0) * scale,
                            }}
                          />
                        )
                      }),
                    )}

                {/* Floating hover card showing the new legal regulation text */}
                {hoveredInfo && hoveredInfo.pageNumber === pageNumber && (
                  <HoverLegalCard
                    key={hoveredInfo.impact.id}
                    impact={hoveredInfo.impact}
                    bbox={{
                      top: hoveredInfo.top,
                      left: hoveredInfo.left,
                      width: hoveredInfo.width,
                      height: hoveredInfo.height,
                    }}
                    pageWidth={pageWidth}
                    onMouseEnter={clearHoverTimeout}
                    onMouseLeave={handleMouseLeave}
                    onEditingChange={(editing) => {
                      isEditingRef.current = editing
                    }}
                    onClose={() => {
                      isEditingRef.current = false
                      hoveredImpactIdRef.current = null
                      setHoveredInfo(null)
                    }}
                    onDecide={
                      onDecide
                        ? (request) => {
                            isEditingRef.current = false
                            const approvedText =
                              request.action === 'edit'
                                ? request.editedText
                                : (hoveredInfo.impact.finalText ?? hoveredInfo.impact.suggestedText)
                            const updatedImpact: Impact = {
                              ...hoveredInfo.impact,
                              status: request.action === 'reject' ? 'rejected' : 'accepted',
                              finalText: request.action === 'reject' ? undefined : approvedText,
                            }
                            onDecide(hoveredInfo.impact, request)
                            setHoveredInfo((prev) => (prev ? { ...prev, impact: updatedImpact } : null))
                          }
                        : undefined
                    }
                    onSelect={onSelect}
                    disabled={disabled}
                  />
                )}

                <span className="absolute right-2 bottom-1 text-[11px] text-slate-400">
                  {pageNumber}/{numPages}
                </span>
              </div>
            )
          })}
        </Document>
      )}
    </div>
  )
}

interface HoverLegalCardProps {
  impact: Impact
  bbox: { top: number; left: number; width: number; height: number }
  pageWidth: number
  onMouseEnter: () => void
  onMouseLeave: () => void
  onClose: () => void
  onSelect?: (impactId: string) => void
  onEditingChange?: (isEditing: boolean) => void
  onDecide?: (request: DecisionRequest) => void
  disabled?: boolean
}

type CardMode = 'view' | 'edit' | 'reject_feedback'

function HoverLegalCard({
  impact,
  bbox,
  pageWidth,
  onMouseEnter,
  onMouseLeave,
  onClose,
  onSelect,
  onEditingChange,
  onDecide,
  disabled,
}: HoverLegalCardProps) {
  const [mode, setMode] = useState<CardMode>('view')
  const [draft, setDraft] = useState(impact.finalText ?? impact.suggestedText ?? '')
  const [feedback, setFeedback] = useState('')
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [isLoadingAi, setIsLoadingAi] = useState(false)

  // Keep draft updated in real-time when impact changes while in view mode
  useEffect(() => {
    if (mode === 'view') {
      setDraft(impact.finalText ?? impact.suggestedText ?? '')
    }
  }, [impact.finalText, impact.suggestedText, mode])

  // Notify parent when in editing or feedback mode so mouse leave doesn't close the card
  useEffect(() => {
    onEditingChange?.(mode !== 'view')
  }, [mode, onEditingChange])

  const handleRequestAiSuggestion = async () => {
    onSelect?.(impact.id)
    // The review package already holds the agent's verified patch; ask for a fresh rewrite only
    // when there is no draft (failed or skipped).
    const proposal = impact.finalText || impact.suggestedText
    if (proposal) {
      setDraft(proposal)
      setMode('edit')
      return
    }
    setIsLoadingAi(true)
    try {
      const response = await fetch('/api/ai/suggest-edit', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          impact_id: impact.id,
          affected_text: impact.affectedText,
          change_clause: impact.changeClause,
          citation: impact.citation,
          location: impact.location,
        }),
      })

      if (response.ok) {
        const data = (await response.json()) as { suggested_text?: string }
        if (data.suggested_text) {
          setDraft(data.suggested_text)
          setMode('edit')
          return
        }
      }
    } catch {
      // Fallback gracefully to existing text if API is unreachable
    } finally {
      setIsLoadingAi(false)
    }

    setDraft(impact.finalText ?? impact.suggestedText ?? impact.affectedText)
    setMode('edit')
  }

  const toggleTag = (tag: string) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    )
  }

  const handleAccept = () => {
    onSelect?.(impact.id)
    const text = draft.trim()
    if (!text) return
    const isEdited = text !== (impact.finalText ?? impact.suggestedText)
    onDecide?.({
      action: isEdited ? 'edit' : 'accept',
      editedText: isEdited ? text : undefined,
      reasonTags: [],
    })
    setMode('view')
  }

  const handleConfirmReject = () => {
    onSelect?.(impact.id)
    const tags = [...selectedTags]
    if (feedback.trim()) {
      tags.push(feedback.trim())
    }
    onDecide?.({
      action: 'reject',
      reasonTags: tags,
    })
    setMode('view')
  }

  const cardWidth = Math.min(460, Math.max(340, pageWidth - 32))
  const center = bbox.left + bbox.width / 2
  const left = Math.max(16, Math.min(center - cardWidth / 2, pageWidth - cardWidth - 16))
  const isAbove = bbox.top > 260
  const arrowLeft = Math.max(16, Math.min(center - left - 6, cardWidth - 28))

  return (
    <div
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      className={cn(
        'pointer-events-auto absolute z-40 rounded-xl border border-border/80 bg-popover/98 p-4 text-popover-foreground shadow-2xl backdrop-blur-md animate-in fade-in-0 zoom-in-95',
        isAbove && '-translate-y-full',
      )}
      style={{
        left,
        top: isAbove ? bbox.top - 10 : bbox.top + bbox.height + 10,
        width: cardWidth,
      }}
    >
      {/* Arrow pointer */}
      <div
        className={cn(
          'absolute size-3 rotate-45 border-border bg-popover',
          isAbove ? '-bottom-1.5 border-r border-b' : '-top-1.5 border-l border-t',
        )}
        style={{ left: arrowLeft }}
      />

      {/* Header with location, badges, and close button */}
      <div className="flex items-center justify-between gap-2 border-b pb-2">
        <div className="flex min-w-0 items-center gap-2">
          <FileText className="size-4 shrink-0 text-primary" />
          <span className="truncate text-sm font-semibold">{impact.location}</span>
          <SeverityBadge severity={impact.severity} />
          {mode === 'edit' && (
            <span className="rounded bg-primary/15 px-1.5 py-0.5 text-[10px] font-medium text-primary">
              Chỉnh sửa đề xuất
            </span>
          )}
          {mode === 'reject_feedback' && (
            <span className="rounded bg-destructive/15 px-1.5 py-0.5 text-[10px] font-medium text-destructive">
              Phản hồi từ chối
            </span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <ImpactTypeLabel type={impact.type} />
          <ImpactStatusBadge status={impact.status} />
          <Button
            size="icon-xs"
            variant="ghost"
            onClick={(e) => {
              e.stopPropagation()
              onClose()
            }}
            className="size-5 rounded-full p-0 text-muted-foreground hover:bg-muted"
            title="Đóng"
          >
            <X className="size-3" />
            <span className="sr-only">Đóng</span>
          </Button>
        </div>
      </div>

      {/* Main Block: Điều khoản VBPL mới */}
      <div className="mt-3 space-y-1.5">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-primary">
          <Scale className="size-3.5" />
          <span>Điều khoản VBPL mới</span>
        </div>
        <div className="rounded-lg border border-primary/25 bg-primary/10 p-2.5 text-xs font-medium leading-relaxed text-foreground shadow-inner">
          {impact.changeClause}
        </div>
        {impact.citation && (
          <p className="text-[11px] text-muted-foreground italic">
            Trích dẫn: {impact.citation}
          </p>
        )}
      </div>

      {/* MODE 1: VIEW MODE */}
      {mode === 'view' && (
        <>
          {impact.status === 'accepted' && (impact.finalText ?? impact.suggestedText) && (
            <div className="mt-2.5 space-y-1">
              <p className="text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
                Nội dung đã được chấp nhận:
              </p>
              <p className="line-clamp-2 rounded border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1.5 text-xs text-emerald-950 dark:text-emerald-200">
                {impact.finalText ?? impact.suggestedText}
              </p>
            </div>
          )}

          {onDecide && (
            <div className="mt-3 flex items-center justify-between border-t pt-2.5">
              <span className="text-[11px] text-muted-foreground">
                {impact.status === 'accepted' ? 'Chỉnh sửa lại:' : 'Chỉnh sửa văn bản:'}
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={disabled || isLoadingAi}
                onClick={handleRequestAiSuggestion}
                className="gap-1.5 px-3 text-xs font-medium"
              >
                {isLoadingAi ? (
                  <>
                    <Loader2 className="size-3.5 animate-spin text-primary" />
                    <span>Đang lấy gợi ý AI...</span>
                  </>
                ) : (
                  <>
                    <PencilLine className="size-3.5 text-primary" />
                    <span>{impact.status === 'accepted' ? 'Chỉnh sửa lại' : 'Đề xuất chỉnh sửa'}</span>
                  </>
                )}
              </Button>
            </div>
          )}
        </>
      )}

      {/* MODE 2: EDIT MODE */}
      {mode === 'edit' && (
        <>
          <div className="mt-2.5 space-y-1">
            <div className="flex items-center gap-1.5 text-[11px] font-medium text-primary">
              <PencilLine className="size-3" />
              <span>Đề xuất chỉnh sửa từ AI:</span>
            </div>
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={3}
              placeholder="Nhập nội dung chỉnh sửa đề xuất..."
              className="resize-none text-xs bg-accent/25 focus-visible:bg-background"
              autoFocus
            />
          </div>

          <div className="mt-3 flex items-center justify-between border-t pt-2.5">
            <Button
              size="xs"
              variant="ghost"
              onClick={() => setMode('view')}
              className="text-xs text-muted-foreground"
            >
              Hủy
            </Button>
            <div className="flex items-center gap-2">
              <Button
                size="xs"
                variant="destructive"
                disabled={disabled}
                onClick={() => setMode('reject_feedback')}
                className="gap-1 px-2.5 text-xs"
              >
                <X className="size-3" />
                Từ chối
              </Button>
              <Button
                size="xs"
                disabled={!draft.trim() || disabled}
                onClick={handleAccept}
                className="gap-1 bg-emerald-600 px-2.5 text-xs text-white hover:bg-emerald-700"
              >
                <Check className="size-3" />
                Chấp nhận
              </Button>
            </div>
          </div>
        </>
      )}

      {/* MODE 3: REJECT FEEDBACK MODE */}
      {mode === 'reject_feedback' && (
        <>
          <div className="mt-2.5 space-y-1.5">
            <label className="text-[11px] font-medium text-muted-foreground">
              Lý do từ chối (feedback để hệ thống học và cải thiện):
            </label>
            {/* Quick reason tag chips */}
            <div className="flex flex-wrap gap-1">
              {reasonTags.map((tag) => {
                const isSelected = selectedTags.includes(tag)
                return (
                  <button
                    key={tag}
                    type="button"
                    onClick={() => toggleTag(tag)}
                    className={cn(
                      'cursor-pointer rounded-full border px-2 py-0.5 text-[10px] transition-colors',
                      isSelected
                        ? 'border-destructive/60 bg-destructive/15 font-medium text-destructive'
                        : 'border-border bg-muted/50 text-muted-foreground hover:bg-muted',
                    )}
                  >
                    {tag}
                  </button>
                )
              })}
            </div>
            <Textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              rows={2}
              placeholder="Nhập lý do hoặc phản hồi chi tiết..."
              className="resize-none text-xs"
              autoFocus
            />
          </div>

          <div className="mt-3 flex items-center justify-between border-t pt-2.5">
            <Button
              size="xs"
              variant="ghost"
              onClick={() => setMode('edit')}
              className="text-xs text-muted-foreground"
            >
              Quay lại
            </Button>
            <Button
              size="xs"
              variant="destructive"
              disabled={disabled}
              onClick={handleConfirmReject}
              className="gap-1 px-3 text-xs"
            >
              <X className="size-3" />
              Xác nhận từ chối
            </Button>
          </div>
        </>
      )}
    </div>
  )
}

function PageSkeleton({ width }: { width: number }) {
  return <Skeleton className="rounded-none" style={{ width, height: width * 1.414 }} />
}

