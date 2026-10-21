import { Check, FileText, Info, Loader2, PencilLine, Scale, X } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'

import type { Impact, InternalDocument } from '@/api/types'
import { ImpactStatusBadge, ImpactTypeLabel, SeverityBadge } from '@/components/status-badges'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useImpactVbplClauses } from '@/hooks/queries'
import { categoryMeaning, reasonTags } from '@/lib/labels'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'
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
const DEFAULT_POINT_WIDTH = 595.0

function useContainerWidth() {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(() => {
    return typeof window !== 'undefined' ? Math.max(window.innerWidth - 380, 600) : 0
  })

  useLayoutEffect(() => {
    if (ref.current) {
      const initial = Math.floor(ref.current.clientWidth)
      if (initial > 0 && Math.abs(initial - width) > 4) {
        setWidth(initial)
      }
    }
  }, [])

  useEffect(() => {
    const element = ref.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return
      const newWidth = Math.floor(entry.contentRect.width)
      setWidth((prev) => (Math.abs(prev - newWidth) > 4 ? newWidth : prev))
    })
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
  selectionTrigger?: number
  onSelect: (impactId: string) => void
  onDecide?: (impact: Impact, request: DecisionRequest) => void
  disabled?: boolean
  onRegisterDownload?: (downloadFn: () => void) => void
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

function isArticleLocation(loc?: string): boolean {
  if (!loc) return false
  const trimmed = loc.trim()
  // If it refers to a sub-clause ("khoản") or sub-point ("điểm"), it is NOT an article level replacement
  if (/khoản|điểm/i.test(trimmed)) return false
  return /^Điều\s+\d+/i.test(trimmed)
}

function inferPrefixFromLocation(loc: string): string {
  if (!loc) return ''
  const trimmed = loc.trim()

  // 1. Point / Điểm: e.g. "Điều 14, khoản 5, điểm a", "Điểm a", "Khoản 2, điểm b", "14.5.a"
  const diemMatch = trimmed.match(/(?:điểm|\.)\s*([a-zđĐ])(?:\b|$|\s|[.)])/i)
  if (diemMatch) {
    return `${diemMatch[1].toLowerCase()}) `
  }

  // 2. Clause / Khoản: e.g. "Điều 14, khoản 5", "Khoản 5", "Khoản 14.5", "14.5"
  // In Vietnamese documents, sequential numbered paragraphs inside an article are "1. ", "2. ", "5. "
  // They must NEVER be prefixed with "Khoản" in the document body!
  const khoanMatch = trimmed.match(/khoản\s*(\d+(?:\.\d+)*)/i)
  if (khoanMatch) {
    const parts = khoanMatch[1].split('.')
    const clauseNum = parts[parts.length - 1]
    return `${clauseNum}. `
  }

  // 3. Article / Điều (only if it has no khoản/điểm, which were handled above)
  const dieuMatch = trimmed.match(/^Điều\s*([IVXLC\d]+)/i)
  if (dieuMatch) {
    return `Điều ${dieuMatch[1]}. `
  }

  // 4. Chapter / Chương: e.g. "Chương I"
  const chuongMatch = trimmed.match(/^Chương\s*([IVXLC\d]+)/i)
  if (chuongMatch) {
    return `Chương ${chuongMatch[1]}. `
  }

  // 5. Appendix / Phụ lục: e.g. "Phụ lục 1"
  const phuLucMatch = trimmed.match(/^Phụ\s*lục\s*([IVXLC\d]+)?/i)
  if (phuLucMatch) {
    return phuLucMatch[1] ? `Phụ lục ${phuLucMatch[1]}. ` : 'Phụ lục. '
  }

  // 6. Section / Mục / Mục lục
  const mucLucMatch = trimmed.match(/^Mục\s*lục\b/i)
  if (mucLucMatch) {
    return 'Mục lục. '
  }
  const mucMatch = trimmed.match(/^Mục\s*([IVXLC\d]+)/i)
  if (mucMatch) {
    return `Mục ${mucMatch[1]}. `
  }

  // 7. Decimal or simple numbering: e.g. "14.5", "2.2. Đối tượng", "1. Phạm vi"
  const firstToken = trimmed.split(/\s+/)[0]?.replace(/\.+$/, '')
  if (firstToken) {
    const parts = firstToken.split('.')
    if (parts.length > 1) {
      const lastPart = parts[parts.length - 1]
      if (/^[a-zđĐ]$/i.test(lastPart)) {
        return `${lastPart.toLowerCase()}) `
      }
      if (/^\d+$/.test(lastPart)) {
        return `${lastPart}. `
      }
    } else if (/^\d+$/.test(firstToken)) {
      return `${firstToken}. `
    }
  }
  return ''
}

export function getReplacementParts(impact: Impact): {
  prefix: string
  content: string
  fullText: string
} {
  const rawText = (impact.finalText ?? impact.suggestedText ?? '')
    .trim()
    .replace(/\s+,/g, ',')
    .replace(/\s+\./g, '.')
    .normalize('NFC')
  if (!rawText) {
    return { prefix: '', content: '', fullText: '' }
  }

  const prefixRegex =
    /^((?:(?:Điều|Khoản|Điểm|Chương|Phụ lục|Mục lục|Mục)\s*(?:[IVXLC\d]+|[a-zđĐ])?[.)]?|\d+(?:\.\d+)*[.)]|[a-zđĐ][.)]|[-+•*])\s*)/i

  // 1. Check if rawText already starts with a prefix (e.g. "Điều 1. ", "1. ", "a) ")
  const rawMatch = rawText.match(prefixRegex)
  if (rawMatch) {
    let prefix = rawMatch[1].trimEnd() + ' '
    const content = rawText.slice(rawMatch[1].length).trim()

    // If prefix is just digits like "1." or "1)", but location explicitly indicates it is an Article (Điều X)
    // (and NOT a clause/khoản), keep "Điều X. "
    const isArticle = /^\d+[.)]\s*$/.test(prefix) && isArticleLocation(impact.location)
    if (isArticle) {
      const numMatch = prefix.match(/^(\d+)/)
      if (numMatch) {
        prefix = `Điều ${numMatch[1]}. `
      }
    }

    return {
      prefix,
      content,
      fullText: prefix ? `${prefix}${content}` : rawText,
    }
  }

  // 2. Check if affectedText starts with a prefix
  const affectedMatch = (impact.affectedText || '').trim().match(prefixRegex)
  let prefix = ''
  if (affectedMatch) {
    prefix = affectedMatch[1].trimEnd() + ' '
    const isArticle = /^\d+[.)]\s*$/.test(prefix) && isArticleLocation(impact.location)
    if (isArticle) {
      const numMatch = prefix.match(/^(\d+)/)
      if (numMatch) {
        prefix = `Điều ${numMatch[1]}. `
      }
    }
  } else if (impact.location) {
    prefix = inferPrefixFromLocation(impact.location)
  }

  const content = rawText
  const fullText = prefix ? `${prefix}${content}` : content
  return { prefix, content, fullText }
}


function CanvasSlice({
  sourceCanvas,
  startY,
  endY,
  pageWidth,
  renderTrigger,
}: {
  sourceCanvas: HTMLCanvasElement | null
  startY: number
  endY: number
  pageWidth: number
  renderTrigger: number
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const sliceHeight = Math.max(0, Math.round(endY - startY))

  useEffect(() => {
    const target = canvasRef.current
    if (!target || !sourceCanvas || sliceHeight <= 0) return

    const dpr = sourceCanvas.width > 0 && pageWidth > 0 ? sourceCanvas.width / pageWidth : 1
    const targetW = Math.round(pageWidth * dpr)
    const targetH = Math.round(sliceHeight * dpr)

    if (target.width !== targetW || target.height !== targetH) {
      target.width = targetW
      target.height = targetH
    }

    const ctx = target.getContext('2d')
    if (!ctx) return

    ctx.clearRect(0, 0, target.width, target.height)

    const sy = Math.round(startY * dpr)
    const sh = Math.min(Math.round(sliceHeight * dpr), Math.max(0, sourceCanvas.height - sy))
    const sw = sourceCanvas.width

    if (sw > 0 && sh > 0) {
      ctx.drawImage(sourceCanvas, 0, sy, sw, sh, 0, 0, target.width, sh)
    }
  }, [sourceCanvas, startY, endY, pageWidth, sliceHeight, renderTrigger])

  if (sliceHeight <= 0) return null

  return (
    <canvas
      ref={canvasRef}
      style={{
        width: `${pageWidth}px`,
        height: `${sliceHeight}px`,
        display: 'block',
      }}
      className="pointer-events-none select-none bg-white"
    />
  )
}

function ReplacedClauseBlock({
  impact,
  scale,
  pageWidth,
  docMaxX1,
  isSelected,
  selectedRef,
  onSelect,
  onMouseEnter,
  onMouseLeave,
  onHeightChange,
}: {
  impact: Impact
  scale: number
  pageWidth: number
  docMaxX1: number
  isSelected: boolean
  selectedRef: { current: HTMLDivElement | null }
  onSelect: (impactId: string) => void
  onMouseEnter: () => void
  onMouseLeave: () => void
  onHeightChange: (id: string, height: number) => void
}) {
  const blockRef = useRef<HTMLDivElement>(null)
  const bbox = getImpactBoundingBox(impact.bboxes)
  const { prefix, content } = getReplacementParts(impact)

  useLayoutEffect(() => {
    if (!blockRef.current) return
    const h = blockRef.current.offsetHeight
    if (h > 0) {
      onHeightChange(impact.id, h)
    }
  }, [onHeightChange, impact.id, impact.finalText, impact.suggestedText])

  useEffect(() => {
    const el = blockRef.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return
      const h = Math.round(entry.borderBoxSize?.[0]?.blockSize ?? entry.contentRect.height)
      if (h > 0) {
        onHeightChange(impact.id, h)
      }
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [onHeightChange, impact.id])

  const left = Math.max(0, (bbox.x0 - 2) * scale)
  // Expand width to match the document's maximum text margin (matching paragraphs above/below)
  const targetRight = (docMaxX1 && docMaxX1 > bbox.x1 ? docMaxX1 : Math.max(bbox.x1, 516.0)) * scale
  const width = Math.min(
    pageWidth - left - 12,
    Math.max(targetRight - left, (bbox.x1 - bbox.x0) * scale),
  )

  return (
    <div
      ref={blockRef}
      className="w-full bg-white relative py-1"
      style={{ width: `${pageWidth}px` }}
    >
      <div
        ref={isSelected ? selectedRef : undefined}
        id={`impact-highlight-${impact.id}`}
        onClick={() => onSelect(impact.id)}
        onMouseEnter={onMouseEnter}
        onMouseLeave={onMouseLeave}
        aria-label="Đoạn văn đã được thay thế bằng đề xuất của AI"
        className={cn(
          'cursor-pointer transition-all duration-200 select-text',
          'bg-white rounded-r-xs',
          'hover:bg-emerald-50/20',
          isSelected ? 'ring-2 ring-emerald-600 ring-offset-1 z-20' : 'ring-1 ring-emerald-500/20 z-10',
        )}
        style={{
          marginLeft: `${left}px`,
          width: `${width}px`,
          paddingLeft: `${Math.max(4, 5 * scale)}px`,
          paddingRight: `${Math.max(4, 5 * scale)}px`,
          paddingTop: `${Math.max(2, 3 * scale)}px`,
          paddingBottom: `${Math.max(2, 3 * scale)}px`,
        }}
      >
        <p
          className="font-sans text-slate-900 leading-[1.38] text-justify whitespace-pre-line m-0"
          style={{
            fontSize: `${Math.max(11, 11.2 * scale)}px`,
          }}
        >
          {prefix && (
            <span className="font-bold text-slate-950 mr-1 select-none">
              {prefix}
            </span>
          )}
          <span className="text-slate-900 font-normal">
            {content}
          </span>
        </p>
      </div>
    </div>
  )
}

export interface PageCanvasData {
  canvas: HTMLCanvasElement
  ptWidth: number
  ptHeight: number
}

export function downloadCanvasesAsPdf(pages: PageCanvasData[], filename: string) {
  if (pages.length === 0) return

  const encoder = new TextEncoder()
  const pad10 = (n: number) => n.toString().padStart(10, '0')

  const header = encoder.encode('%PDF-1.4\n')
  const numPages = pages.length

  const obj1 = encoder.encode('1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n')

  const kidsStr = Array.from({ length: numPages }, (_, i) => `${3 + i * 3} 0 R`).join(' ')
  const obj2 = encoder.encode(`2 0 obj\n<< /Type /Pages /Kids [${kidsStr}] /Count ${numPages} >>\nendobj\n`)

  const bodyObjs: Uint8Array[] = [obj1, obj2]

  for (let i = 0; i < numPages; i++) {
    const k = i + 1
    const pageId = 3 + i * 3
    const contentId = pageId + 1
    const imgId = pageId + 2

    const pageData = pages[i]
    const ptW = pageData.ptWidth
    const ptH = pageData.ptHeight
    const canvas = pageData.canvas

    const dataUrl = canvas.toDataURL('image/jpeg', 0.95)
    const binaryString = atob(dataUrl.split(',')[1] || '')
    const len = binaryString.length
    const jpegBytes = new Uint8Array(len)
    for (let j = 0; j < len; j++) {
      jpegBytes[j] = binaryString.charCodeAt(j)
    }

    const contentStream = encoder.encode(
      `q\n${ptW.toFixed(2)} 0 0 ${ptH.toFixed(2)} 0 0 cm\n/Im${k} Do\nQ\n`,
    )

    const pageObj = encoder.encode(
      `${pageId} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${ptW.toFixed(2)} ${ptH.toFixed(2)}] /Contents ${contentId} 0 R /Resources << /XObject << /Im${k} ${imgId} 0 R >> /ProcSet [/PDF /ImageC] >> >>\nendobj\n`,
    )

    const contentObj = new Uint8Array([
      ...encoder.encode(`${contentId} 0 obj\n<< /Length ${contentStream.length} >>\nstream\n`),
      ...contentStream,
      ...encoder.encode('endstream\nendobj\n'),
    ])

    const imgHeader = encoder.encode(
      `${imgId} 0 obj\n<< /Type /XObject /Subtype /Image /Width ${canvas.width} /Height ${canvas.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpegBytes.length} >>\nstream\n`,
    )
    const imgFooter = encoder.encode('\nendstream\nendobj\n')
    const imgObj = new Uint8Array(imgHeader.length + jpegBytes.length + imgFooter.length)
    imgObj.set(imgHeader, 0)
    imgObj.set(jpegBytes, imgHeader.length)
    imgObj.set(imgFooter, imgHeader.length + jpegBytes.length)

    bodyObjs.push(pageObj, contentObj, imgObj)
  }

  let currentOffset = header.length
  const objOffsets: number[] = [0]
  for (const obj of bodyObjs) {
    objOffsets.push(currentOffset)
    currentOffset += obj.length
  }

  const xrefPos = currentOffset
  const totalObjs = bodyObjs.length + 1

  let xrefStr = `xref\n0 ${totalObjs}\n0000000000 65535 f \n`
  for (let idx = 1; idx < objOffsets.length; idx++) {
    xrefStr += `${pad10(objOffsets[idx])} 00000 n \n`
  }
  const xref = encoder.encode(xrefStr)
  const trailer = encoder.encode(
    `trailer\n<< /Size ${totalObjs} /Root 1 0 R >>\nstartxref\n${xrefPos}\n%%EOF\n`,
  )

  const totalLength = xrefPos + xref.length + trailer.length
  const pdfBytes = new Uint8Array(totalLength)
  let pos = 0
  pdfBytes.set(header, pos)
  pos += header.length
  for (const obj of bodyObjs) {
    pdfBytes.set(obj, pos)
    pos += obj.length
  }
  pdfBytes.set(xref, pos)
  pos += xref.length
  pdfBytes.set(trailer, pos)

  const blob = new Blob([pdfBytes], { type: 'application/pdf' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  setTimeout(() => {
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }, 1000)
}

interface PdfPageViewProps {
  pageNumber: number
  pageWidth: number
  numPages: number
  scale: number
  impacts: Impact[]
  selectedId: string | undefined
  selectedRef: { current: HTMLDivElement | null }
  hoveredInfo: HoveredInfo | null
  onSelect: (impactId: string) => void
  onMouseEnter: (
    impact: Impact,
    pageNumber: number,
    scale: number,
    customTop?: number,
    customHeight?: number,
  ) => void
  onMouseLeave: () => void
  clearHoverTimeout: () => void
  handlePageLoadSuccess: (pageNumber: number, originalWidth: number) => void
  onDecide?: (impact: Impact, request: DecisionRequest) => void
  isEditingRef: { current: boolean }
  hoveredImpactIdRef: { current: string | null }
  setHoveredInfo: React.Dispatch<React.SetStateAction<HoveredInfo | null>>
  disabled?: boolean
  onRegisterPageExport?: (pageNumber: number, getter: (() => PageCanvasData | null) | null) => void
}

function PdfPageView({
  pageNumber,
  pageWidth,
  numPages,
  scale,
  impacts,
  selectedId,
  selectedRef,
  hoveredInfo,
  onSelect,
  onMouseEnter,
  onMouseLeave,
  clearHoverTimeout,
  handlePageLoadSuccess,
  onDecide,
  isEditingRef,
  hoveredImpactIdRef,
  setHoveredInfo,
  disabled,
  onRegisterPageExport,
}: PdfPageViewProps) {
  const sourceContainerRef = useRef<HTMLDivElement>(null)
  const [sourceCanvas, setSourceCanvas] = useState<HTMLCanvasElement | null>(null)
  const [renderTrigger, setRenderTrigger] = useState(0)
  const [clauseHeights, setClauseHeights] = useState<Record<string, number>>({})
  const [measuredPageHeight, setMeasuredPageHeight] = useState<number>(0)

  const docMaxX1 = useMemo(() => {
    let max = 0
    for (const imp of impacts) {
      for (const bbox of imp.bboxes || []) {
        if (bbox[2] > max) max = bbox[2]
      }
    }
    return max > 0 ? max : 516.0
  }, [impacts])

  const updateSourceCanvas = useCallback(() => {
    const container = sourceContainerRef.current
    if (!container) return
    const canvas = container.querySelector('canvas')
    if (canvas && canvas.width > 0 && canvas.height > 0) {
      setSourceCanvas(canvas)
      const h =
        container.clientHeight ||
        (canvas.width > 0 && pageWidth > 0 ? (canvas.height / canvas.width) * pageWidth : 0)
      if (h > 0) {
        setMeasuredPageHeight((prev) => (Math.abs(prev - h) < 1 ? prev : h))
      }
      setRenderTrigger((prev) => prev + 1)
    }
  }, [pageWidth])

  const pageImpacts = useMemo(
    () => impacts.filter((impact) => impact.page === pageNumber),
    [impacts, pageNumber],
  )

  const acceptedImpacts = useMemo(
    () =>
      pageImpacts.filter(
        (impact) => impact.status === 'accepted' && impact.bboxes && impact.bboxes.length > 0,
      ),
    [pageImpacts],
  )

  const sortedAccepted = useMemo(() => {
    return [...acceptedImpacts].sort((a, b) => {
      const boxA = getImpactBoundingBox(a.bboxes)
      const boxB = getImpactBoundingBox(b.bboxes)
      return boxA.y0 - boxB.y0
    })
  }, [acceptedImpacts])

  const onHeightChange = useCallback((id: string, height: number) => {
    setClauseHeights((prev) => {
      if (prev[id] && Math.abs(prev[id] - height) < 1) return prev
      return { ...prev, [id]: height }
    })
  }, [])

  const getShiftAtY = useCallback(
    (origY: number) => {
      let shift = 0
      for (const imp of sortedAccepted) {
        const box = getImpactBoundingBox(imp.bboxes)
        const startY = box.y0 * scale
        const endY = box.y1 * scale
        const origH = Math.max(0, endY - startY)
        const measuredH = clauseHeights[imp.id] ?? origH
        if (origY >= endY - 1) {
          shift += measuredH - origH
        }
      }
      return shift
    },
    [sortedAccepted, scale, clauseHeights],
  )

  const isSliced = sortedAccepted.length > 0 && scale > 0

  const pageHeight =
    measuredPageHeight > 0
      ? measuredPageHeight
      : sourceCanvas && pageWidth > 0 && sourceCanvas.width > 0
        ? (sourceCanvas.height / sourceCanvas.width) * pageWidth
        : pageWidth * 1.414

  const pendingAndRejected = useMemo(
    () => pageImpacts.filter((imp) => imp.status !== 'accepted'),
    [pageImpacts],
  )

  const getPageExportData = useCallback((): PageCanvasData | null => {
    const canvas = sourceCanvas || sourceContainerRef.current?.querySelector('canvas')
    if (!canvas || canvas.width === 0 || canvas.height === 0) return null

    const dpr = canvas.width > 0 && pageWidth > 0 ? canvas.width / pageWidth : 1.5
    const ptW = 595.28

    if (!isSliced) {
      const ptH = canvas.width > 0 ? (canvas.height / canvas.width) * ptW : 841.89
      return { canvas, ptWidth: ptW, ptHeight: ptH }
    }

    // When sliced, composite canvas slices + replaced clause blocks seamlessly
    const totalCssHeight = pageHeight + getShiftAtY(pageHeight)
    const exportCanvas = window.document.createElement('canvas')
    exportCanvas.width = Math.round(pageWidth * dpr)
    exportCanvas.height = Math.round(totalCssHeight * dpr)
    const ctx = exportCanvas.getContext('2d')
    if (!ctx) return null

    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, exportCanvas.width, exportCanvas.height)

    let currentSourceY = 0
    let currentOutY = 0

    sortedAccepted.forEach((imp) => {
      const bbox = getImpactBoundingBox(imp.bboxes)
      const startY = bbox.y0 * scale
      const endY = bbox.y1 * scale
      const origH = Math.max(0, endY - startY)
      const measuredH = clauseHeights[imp.id] ?? origH

      // 1. Draw top canvas slice
      const sliceH = Math.max(0, startY - currentSourceY)
      if (sliceH > 0) {
        const sy = Math.round(currentSourceY * dpr)
        const sh = Math.min(Math.round(sliceH * dpr), Math.max(0, canvas.height - sy))
        const outH = sh
        if (canvas.width > 0 && sh > 0) {
          ctx.drawImage(canvas, 0, sy, canvas.width, sh, 0, Math.round(currentOutY * dpr), exportCanvas.width, outH)
        }
        currentOutY += sliceH
      }

      // 2. Draw Replaced Clause Block
      const blockOutY = currentOutY
      const blockOutH = measuredH
      const left = Math.max(0, (bbox.x0 - 2) * scale)
      const targetRight = (docMaxX1 && docMaxX1 > bbox.x1 ? docMaxX1 : Math.max(bbox.x1, 516.0)) * scale
      const blockW = Math.min(pageWidth - left - 12, Math.max(targetRight - left, (bbox.x1 - bbox.x0) * scale))

      // Clean white background behind text
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(Math.round(left * dpr), Math.round(blockOutY * dpr), Math.round(blockW * dpr), Math.round(blockOutH * dpr))

      // Text inside block - clean document text without badges or borders
      const { fullText } = getReplacementParts(imp)
      const padL = Math.max(4, 5 * scale) * dpr
      const padR = Math.max(4, 5 * scale) * dpr
      const padT = Math.max(2, 3 * scale) * dpr
      const fontSize = Math.max(11, 11.2 * scale) * dpr
      const lineHeight = fontSize * 1.38

      const textX = Math.round(left * dpr + padL)
      let textY = Math.round(blockOutY * dpr + padT) + fontSize * 0.85
      const maxTextW = Math.round(blockW * dpr - padL - padR)

      ctx.fillStyle = '#0f172a'
      ctx.font = `${Math.round(fontSize)}px "Be Vietnam Pro", sans-serif`

      const words = fullText.split(/\s+/)
      let currentLine = ''

      for (let n = 0; n < words.length; n++) {
        const testLine = currentLine ? `${currentLine} ${words[n]}` : words[n]
        const metrics = ctx.measureText(testLine)
        if (metrics.width > maxTextW && currentLine) {
          ctx.fillText(currentLine, textX, textY)
          currentLine = words[n]
          textY += lineHeight
        } else {
          currentLine = testLine
        }
      }
      if (currentLine) {
        ctx.fillText(currentLine, textX, textY)
      }

      currentOutY += measuredH
      currentSourceY = endY
    })

    // 3. Draw last slice
    const lastSliceH = Math.max(0, pageHeight - currentSourceY)
    if (lastSliceH > 0) {
      const sy = Math.round(currentSourceY * dpr)
      const sh = Math.min(Math.round(lastSliceH * dpr), Math.max(0, canvas.height - sy))
      const outH = sh
      if (canvas.width > 0 && sh > 0) {
        ctx.drawImage(canvas, 0, sy, canvas.width, sh, 0, Math.round(currentOutY * dpr), exportCanvas.width, outH)
      }
    }

    const ptH = totalCssHeight > 0 && pageWidth > 0 ? (totalCssHeight / pageWidth) * ptW : 841.89
    return { canvas: exportCanvas, ptWidth: ptW, ptHeight: ptH }
  }, [sourceCanvas, pageWidth, isSliced, pageHeight, getShiftAtY, sortedAccepted, scale, clauseHeights, docMaxX1])

  useEffect(() => {
    onRegisterPageExport?.(pageNumber, getPageExportData)
  }, [onRegisterPageExport, pageNumber, getPageExportData])

  useEffect(() => {
    return () => {
      onRegisterPageExport?.(pageNumber, null)
    }
  }, [onRegisterPageExport, pageNumber])

  return (
    <div
      key={pageNumber}
      data-page-number={pageNumber}
      className="relative bg-white shadow-[0_1px_2px_oklch(0.3_0.03_258/0.08),0_4px_12px_oklch(0.3_0.03_258/0.08)]"
      style={{ width: pageWidth }}
    >
      {/* 1. Underlying react-pdf Page: always mounted so canvas bitmap stays in memory */}
      <div
        ref={sourceContainerRef}
        className={cn(
          'w-full',
          isSliced && 'absolute top-0 left-0 opacity-0 pointer-events-none -z-10',
        )}
        style={{ width: pageWidth }}
        aria-hidden={isSliced}
      >
        <Page
          pageNumber={pageNumber}
          width={pageWidth}
          renderTextLayer={false}
          renderAnnotationLayer={false}
          loading={<PageSkeleton width={pageWidth} />}
          onLoadSuccess={(page) => {
            handlePageLoadSuccess(pageNumber, page.originalWidth)
            updateSourceCanvas()
          }}
          onRenderSuccess={updateSourceCanvas}
        />
      </div>

      {/* 2. Sliced Column Mode: Canvas slices with Replaced Clause Block in normal DOM flow */}
      {isSliced && (
        <div className="flex flex-col w-full bg-white">
          {(() => {
            const elements: React.ReactNode[] = []
            let currentY = 0

            sortedAccepted.forEach((imp, index) => {
              const bbox = getImpactBoundingBox(imp.bboxes)
              const startY = bbox.y0 * scale
              const endY = bbox.y1 * scale

              // Top slice before this accepted block
              const sliceTop = currentY
              const sliceBottom = Math.max(sliceTop, startY)
              if (sliceBottom > sliceTop) {
                elements.push(
                  <CanvasSlice
                    key={`slice-${pageNumber}-${index}`}
                    sourceCanvas={sourceCanvas}
                    startY={sliceTop}
                    endY={sliceBottom}
                    pageWidth={pageWidth}
                    renderTrigger={renderTrigger}
                  />,
                )
              }

              // Replaced block
              const isSelected = imp.id === selectedId
              const blockTop = startY + getShiftAtY(startY)
              const origH = Math.max(0, endY - startY)
              const blockHeight = clauseHeights[imp.id] ?? origH

              elements.push(
                <ReplacedClauseBlock
                  key={`block-${imp.id}`}
                  impact={imp}
                  scale={scale}
                  pageWidth={pageWidth}
                  docMaxX1={docMaxX1}
                  isSelected={isSelected}
                  selectedRef={selectedRef}
                  onSelect={onSelect}
                  onMouseEnter={() =>
                    onMouseEnter(imp, pageNumber, scale, blockTop, blockHeight)
                  }
                  onMouseLeave={onMouseLeave}
                  onHeightChange={onHeightChange}
                />,
              )

              currentY = Math.max(currentY, endY)
            })

            // Final slice to bottom of page
            if (pageHeight > currentY) {
              elements.push(
                <CanvasSlice
                  key={`slice-${pageNumber}-last`}
                  sourceCanvas={sourceCanvas}
                  startY={currentY}
                  endY={pageHeight}
                  pageWidth={pageWidth}
                  renderTrigger={renderTrigger}
                />,
              )
            }

            return elements
          })()}
        </div>
      )}

      {/* 3. Highlights overlay for pending/rejected impacts (with vertical shift in sliced mode) */}
      {scale > 0 && isSliced && (
        <div className="absolute inset-0 pointer-events-none">
          {pendingAndRejected.map((impact) => {
            const isSelected = impact.id === selectedId
            return impact.bboxes.map(([x0, y0, x1, y1], boxIndex) => {
              const origTop = y0 * scale
              const shift = getShiftAtY(origTop)
              const shiftedTop = origTop + shift
              const boxHeight = (y1 - y0) * scale

              return (
                <div
                  key={`${impact.id}-${boxIndex}`}
                  ref={isSelected && boxIndex === 0 ? selectedRef : undefined}
                  id={isSelected && boxIndex === 0 ? `impact-highlight-${impact.id}` : undefined}
                  onClick={() => {
                    onSelect(impact.id)
                    const fullBox = getImpactBoundingBox(impact.bboxes)
                    const fTop = fullBox.y0 * scale + getShiftAtY(fullBox.y0 * scale)
                    const fH = (fullBox.y1 - fullBox.y0) * scale
                    onMouseEnter(impact, pageNumber, scale, fTop, fH)
                  }}
                  onMouseEnter={() => {
                    const fullBox = getImpactBoundingBox(impact.bboxes)
                    const fTop = fullBox.y0 * scale + getShiftAtY(fullBox.y0 * scale)
                    const fH = (fullBox.y1 - fullBox.y0) * scale
                    onMouseEnter(impact, pageNumber, scale, fTop, fH)
                  }}
                  onMouseLeave={onMouseLeave}
                  aria-hidden
                  className={cn(
                    'absolute cursor-pointer mix-blend-multiply transition-all duration-200 pointer-events-auto',
                    highlightStyle[impact.status],
                    isSelected &&
                      (impact.status === 'rejected'
                        ? 'bg-rose-500/50 ring-2 ring-rose-600 ring-offset-1 z-10'
                        : 'bg-amber-400/65 ring-2 ring-amber-500 ring-offset-1 z-10'),
                  )}
                  style={{
                    left: x0 * scale,
                    top: shiftedTop,
                    width: (x1 - x0) * scale,
                    height: boxHeight,
                  }}
                />
              )
            })
          })}
        </div>
      )}

      {/* 4. Highlights overlay for normal mode (when no impacts are accepted yet) */}
      {scale > 0 && !isSliced && (
        <>
          {pageImpacts.map((impact) => {
            const isSelected = impact.id === selectedId
            return impact.bboxes.map(([x0, y0, x1, y1], boxIndex) => (
              <div
                key={`${impact.id}-${boxIndex}`}
                ref={isSelected && boxIndex === 0 ? selectedRef : undefined}
                id={isSelected && boxIndex === 0 ? `impact-highlight-${impact.id}` : undefined}
                onClick={() => {
                  onSelect(impact.id)
                  onMouseEnter(impact, pageNumber, scale)
                }}
                onMouseEnter={() => onMouseEnter(impact, pageNumber, scale)}
                onMouseLeave={onMouseLeave}
                aria-hidden
                className={cn(
                  'absolute cursor-pointer mix-blend-multiply transition-all duration-200',
                  highlightStyle[impact.status],
                  isSelected &&
                    (impact.status === 'rejected'
                      ? 'bg-rose-500/50 ring-2 ring-rose-600 ring-offset-1 z-10'
                      : 'bg-amber-400/65 ring-2 ring-amber-500 ring-offset-1 z-10'),
                )}
                style={{
                  left: x0 * scale,
                  top: y0 * scale,
                  width: (x1 - x0) * scale,
                  height: (y1 - y0) * scale,
                }}
              />
            ))
          })}
        </>
      )}

      {/* 5. Floating hover card showing the new legal regulation text */}
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
          onMouseLeave={onMouseLeave}
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

      <span className="absolute right-2 bottom-1 text-[11px] text-slate-400 font-mono">
        {pageNumber}/{numPages}
      </span>
    </div>
  )
}

/** Mount with key={document.id}: page measurements are per document. */
export function PdfViewer({
  document,
  impacts,
  selectedId,
  selectionTrigger,
  onSelect,
  onDecide,
  disabled,
  onRegisterDownload,
}: PdfViewerProps) {
  const { ref, width } = useContainerWidth()
  const [numPages, setNumPages] = useState(0)
  // Original page width in PDF points, per page, to convert bbox points to pixels.
  const [pointWidths, setPointWidths] = useState<Record<number, number>>({})
  const selectedRef = useRef<HTMLDivElement>(null)
  const lastScrolledIdRef = useRef<string | null>(null)
  const [hoveredInfo, setHoveredInfo] = useState<HoveredInfo | null>(null)
  const hoveredImpactIdRef = useRef<string | null>(null)
  const hoverTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const isEditingRef = useRef(false)
  const pageExportsRef = useRef<Record<number, () => PageCanvasData | null>>({})

  const onRegisterPageExport = useCallback(
    (pageNumber: number, getter: (() => PageCanvasData | null) | null) => {
      if (getter) {
        pageExportsRef.current[pageNumber] = getter
      } else {
        delete pageExportsRef.current[pageNumber]
      }
    },
    [],
  )

  const downloadFullEditedPdf = useCallback(() => {
    const pages: PageCanvasData[] = []
    const container = ref.current
    for (let p = 1; p <= numPages; p++) {
      let pageData: PageCanvasData | null = null
      const getter = pageExportsRef.current[p]
      if (getter) {
        pageData = getter()
      }
      if (!pageData && container) {
        const pageEl = container.querySelector(`[data-page-number="${p}"]`)
        const canvas = pageEl?.querySelector('canvas')
        if (canvas && canvas.width > 0 && canvas.height > 0) {
          const ptW = pointWidths[p] || DEFAULT_POINT_WIDTH
          const ptH = (canvas.height / canvas.width) * ptW
          pageData = { canvas, ptWidth: ptW, ptHeight: ptH }
        }
      }
      if (pageData) {
        pages.push(pageData)
      }
    }
    if (pages.length > 0) {
      toast.success('Đang tạo và tải xuống tệp PDF đã chỉnh sửa...')
      downloadCanvasesAsPdf(pages, `${document.code}_DaChinhSua.pdf`)
    } else {
      toast.error('Chưa có dữ liệu trang để xuất PDF. Vui lòng thử lại sau giây lát.')
    }
  }, [numPages, document.code, pointWidths, ref])

  useEffect(() => {
    onRegisterDownload?.(downloadFullEditedPdf)
    return () => {
      onRegisterDownload?.(() => {})
    }
  }, [onRegisterDownload, downloadFullEditedPdf])

  const handlePageLoadSuccess = useCallback((pageNumber: number, originalWidth: number) => {
    setPointWidths((prev) => {
      const current = prev[pageNumber] || DEFAULT_POINT_WIDTH
      if (Math.abs(current - originalWidth) > 2) {
        return { ...prev, [pageNumber]: originalWidth }
      }
      return prev
    })
  }, [])

  const getPageScale = useCallback(
    (pageNumber: number, pWidth: number) => {
      const ptWidth = pointWidths[pageNumber] || DEFAULT_POINT_WIDTH
      return pWidth > 0 && ptWidth > 0 ? pWidth / ptWidth : 0
    },
    [pointWidths],
  )

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
    customTop?: number,
    customHeight?: number,
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
      top: customTop !== undefined ? customTop : bbox.y0 * scale,
      left: bbox.x0 * scale,
      width: (bbox.x1 - bbox.x0) * scale,
      height: customHeight !== undefined ? customHeight : (bbox.y1 - bbox.y0) * scale,
    })
  }

  const handleMouseLeave = () => {
    clearHoverTimeout()
    if (isEditingRef.current) return
    // If card belongs to the selected impact, keep it visible!
    if (selectedId && hoveredImpactIdRef.current === selectedId) return
    hoverTimeoutRef.current = setTimeout(() => {
      hoveredImpactIdRef.current = null
      setHoveredInfo(null)
    }, 250)
  }

  const pageWidth = Math.min(Math.max(width - 2 * PAGE_GAP, 0), MAX_PAGE_WIDTH)
  const selected = impacts.find((impact) => impact.id === selectedId)
  const selectedPage = selected ? (selected.page ?? (selected.bboxes && selected.bboxes.length > 0 ? 1 : null)) : null

  const scrollToSelected = useCallback((smooth: boolean = true) => {
    if (!selectedId) return false
    const el = selectedRef.current || window.document.getElementById(`impact-highlight-${selectedId}`)
    if (el) {
      const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      el.scrollIntoView({ block: 'center', behavior: !smooth || reduceMotion ? 'auto' : 'smooth' })
      return true
    }
    return false
  }, [selectedId])

  useEffect(() => {
    if (!selectedId) {
      lastScrolledIdRef.current = null
      return
    }

    // Try scrolling immediately if element is already rendered
    if (scrollToSelected()) return

    // If element is not in DOM yet (e.g. PDF page canvas is still rendering), poll until it mounts
    let attempts = 0
    const timer = setInterval(() => {
      attempts++
      if (scrollToSelected() || attempts >= 30) {
        clearInterval(timer)
      }
    }, 100)

    return () => clearInterval(timer)
  }, [selectedId, selectionTrigger, scrollToSelected])

  // When selection changes or user clicks card, anchor hover card to the selected impact
  useEffect(() => {
    if (!selectedId || !selected || selectedPage == null) {
      if (!selectedId) {
        hoveredImpactIdRef.current = null
        setHoveredInfo(null)
      }
      return
    }
    if (!selected.bboxes || selected.bboxes.length === 0) {
      hoveredImpactIdRef.current = null
      setHoveredInfo(null)
      return
    }
    const pageNumber = selectedPage
    const scale = getPageScale(pageNumber, pageWidth)
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
  }, [selectedId, selectedPage, pageWidth, getPageScale, selected, selectionTrigger])

  return (
    <div ref={ref} className="h-full overflow-y-scroll overflow-x-hidden [scrollbar-gutter:stable] bg-muted/60 py-4">
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
            const scale = getPageScale(pageNumber, pageWidth)
            return (
              <PdfPageView
                key={pageNumber}
                pageNumber={pageNumber}
                pageWidth={pageWidth}
                numPages={numPages}
                scale={scale}
                impacts={impacts}
                selectedId={selectedId}
                selectedRef={selectedRef}
                hoveredInfo={hoveredInfo}
                onSelect={onSelect}
                onMouseEnter={handleMouseEnter}
                onMouseLeave={handleMouseLeave}
                clearHoverTimeout={clearHoverTimeout}
                handlePageLoadSuccess={handlePageLoadSuccess}
                onDecide={onDecide}
                isEditingRef={isEditingRef}
                hoveredImpactIdRef={hoveredImpactIdRef}
                setHoveredInfo={setHoveredInfo}
                disabled={disabled}
                onRegisterPageExport={onRegisterPageExport}
              />
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
  // Where "Quay lại" returns to from the reject form.
  const [rejectFrom, setRejectFrom] = useState<'view' | 'edit'>('view')
  const proposal = impact.finalText ?? impact.suggestedText
  // Cited VBPL articles (Điều + tên) behind the citation; empty for impacts with no RIA findings.
  const { data: vbplClauses } = useImpactVbplClauses(impact.id)

  const openRejectFeedback = (from: 'view' | 'edit') => {
    onSelect?.(impact.id)
    setRejectFrom(from)
    setMode('reject_feedback')
  }

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

      {/* Category meaning — short plain-language explanation of the impact type (highlighted) */}
      {impact.category && categoryMeaning[impact.category] && (
        <div className="mt-2 flex items-start gap-1.5 rounded-md bg-primary/10 px-2 py-1 text-xs font-medium text-primary ring-1 ring-primary/20">
          <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span title={impact.category}>{categoryMeaning[impact.category]}</span>
        </div>
      )}

      {/* Main Block: Điều khoản VBPL mới */}
      <div className="mt-3 space-y-1.5">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-primary">
          <Scale className="size-3.5" />
          <span>Điều khoản VBPL mới</span>
        </div>
        <div className="rounded-lg border border-primary/25 bg-primary/10 p-2.5 text-xs font-medium leading-relaxed text-foreground shadow-inner">
          {vbplClauses && vbplClauses.length > 0 && (
            <div className="mb-1.5 space-y-0.5 border-b border-primary/20 pb-1.5">
              {vbplClauses.map((group) => {
                const subClauses = group.clauses.filter((c) => c !== group.articleNumbering)
                return (
                  <p key={group.articleNumbering} className="font-semibold text-primary">
                    Điều {group.articleNumbering}
                    {group.articleTitle ? ` — ${group.articleTitle}` : ''}
                    {subClauses.length > 0 && (
                      <span className="font-normal text-muted-foreground"> (khoản {subClauses.join(', ')})</span>
                    )}
                  </p>
                )
              })}
            </div>
          )}
          <div className="whitespace-pre-line">{impact.changeClause}</div>
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
                {getReplacementParts(impact).fullText}
              </p>
            </div>
          )}

          {/* Pending/rejected with an AI draft: show it right away so the reviewer only accepts or rejects. */}
          {impact.status !== 'accepted' && proposal && (
            <div className="mt-2.5 space-y-1">
              <div className="flex items-center gap-1.5 text-[11px] font-medium text-primary">
                <PencilLine className="size-3" />
                <span>Đề xuất chỉnh sửa từ AI:</span>
              </div>
              {impact.location && (
                <p className="text-[11px] font-semibold text-foreground">{impact.location}</p>
              )}
              <p className="max-h-40 overflow-auto whitespace-pre-wrap rounded border border-primary/25 bg-accent/25 px-2.5 py-1.5 text-xs leading-relaxed">
                {proposal}
              </p>
            </div>
          )}

          {onDecide && impact.status !== 'accepted' && proposal && (
            <div className="mt-3 flex items-center justify-between border-t pt-2.5">
              <Button
                size="xs"
                variant="ghost"
                disabled={disabled}
                onClick={() => {
                  onSelect?.(impact.id)
                  setMode('edit')
                }}
                className="gap-1 text-xs text-muted-foreground"
              >
                <PencilLine className="size-3" />
                Sửa
              </Button>
              <div className="flex items-center gap-2">
                <Button
                  size="xs"
                  variant="destructive"
                  disabled={disabled}
                  onClick={() => openRejectFeedback('view')}
                  className="gap-1 px-2.5 text-xs"
                >
                  <X className="size-3" />
                  Từ chối
                </Button>
                <Button
                  size="xs"
                  disabled={disabled}
                  onClick={handleAccept}
                  className="gap-1 bg-emerald-600 px-2.5 text-xs text-white hover:bg-emerald-700"
                >
                  <Check className="size-3" />
                  Chấp nhận
                </Button>
              </div>
            </div>
          )}

          {onDecide && (impact.status === 'accepted' || !proposal) && (
            <div className="mt-3 flex items-center justify-between border-t pt-2.5">
              <span className="text-[11px] text-muted-foreground">
                {impact.status === 'accepted' ? 'Chỉnh sửa lại:' : 'AI chưa có đề xuất:'}
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
            {impact.location && (
              <p className="text-[11px] font-semibold text-foreground">{impact.location}</p>
            )}
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
                onClick={() => openRejectFeedback('edit')}
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
              onClick={() => setMode(rejectFrom)}
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
  return (
    <div
      className="relative flex items-center justify-center bg-white shadow-[0_1px_2px_oklch(0.3_0.03_258/0.08),0_4px_12px_oklch(0.3_0.03_258/0.08)]"
      style={{ width, height: Math.round(width * 1.414) }}
    >
      <Loader2 className="size-6 animate-spin text-slate-300" />
    </div>
  )
}

