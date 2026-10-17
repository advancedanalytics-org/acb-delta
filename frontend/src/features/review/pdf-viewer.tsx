import { useEffect, useRef, useState } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'

import type { Impact, InternalDocument } from '@/api/types'
import { Skeleton } from '@/components/ui/skeleton'
import { impactStatusLabel } from '@/lib/labels'
import { cn } from '@/lib/utils'

// react-pdf + our own overlay instead of react-pdf-highlighter-extended, which does not support React 19.
pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString()

const highlightStyle: Record<Impact['status'], string> = {
  pending: 'bg-status-pending/35 border-status-pending',
  accepted: 'bg-status-accepted/30 border-status-accepted',
  rejected: 'bg-status-rejected/25 border-status-rejected',
}

// Horizontal breathing room around pages; vertical gap is the gap-4 on the page column.
const PAGE_GAP = 16
const MAX_PAGE_WIDTH = 820

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

interface PdfViewerProps {
  document: InternalDocument
  impacts: Impact[]
  selectedId: string | undefined
  onSelect: (impactId: string) => void
}

/** Mount with key={document.id}: page measurements are per document. */
export function PdfViewer({ document, impacts, selectedId, onSelect }: PdfViewerProps) {
  const { ref, width } = useContainerWidth()
  const [numPages, setNumPages] = useState(0)
  // Original page width in PDF points, per page, to convert bbox points to pixels.
  const [pointWidths, setPointWidths] = useState<Record<number, number>>({})
  const selectedRef = useRef<HTMLDivElement>(null)

  const pageWidth = Math.min(Math.max(width - 2 * PAGE_GAP, 0), MAX_PAGE_WIDTH)
  const selected = impacts.find((impact) => impact.id === selectedId)
  const selectedPageReady = selected ? Boolean(pointWidths[selected.page]) : false

  useEffect(() => {
    if (!selectedPageReady) return
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    selectedRef.current?.scrollIntoView({ block: 'center', behavior: reduceMotion ? 'auto' : 'smooth' })
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
                            onClick={() => onSelect(impact.id)}
                            title={`${impact.location} · ${impactStatusLabel[impact.status]}`}
                            aria-hidden
                            className={cn(
                              'absolute cursor-pointer rounded-[2px] border-b-2 mix-blend-multiply transition-shadow duration-200',
                              highlightStyle[impact.status],
                              isSelected && 'z-10 ring-2 ring-primary ring-offset-1',
                            )}
                            style={{
                              left: x0 * scale - 2,
                              top: y0 * scale - 1,
                              width: (x1 - x0) * scale + 4,
                              height: (y1 - y0) * scale + 2,
                            }}
                          />
                        )
                      }),
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

function PageSkeleton({ width }: { width: number }) {
  return <Skeleton className="rounded-none" style={{ width, height: width * 1.414 }} />
}
