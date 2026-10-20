import {
  ArrowLeft,
  ArrowRight,
  BookmarkCheck,
  FileText,
  Landmark,
  Network,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import type { Impact, InternalDocument, Severity } from '@/api/types'
import { EmptyState, ErrorState } from '@/components/query-states'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useDocuments, useImpacts, useVbpls } from '@/hooks/queries'
import { cn } from '@/lib/utils'

/**
 * Phân loại văn bản nội bộ thành 'Quy định' hoặc 'Nội quy'
 */
export function getDocumentKind(title: string, code: string): 'Quy định' | 'Nội quy' {
  const combined = `${code} ${title}`.toLowerCase()
  if (combined.includes('nội quy') || combined.includes('nq-') || combined.includes('nq/')) {
    return 'Nội quy'
  }
  return 'Quy định'
}

/**
 * Danh mục tiêu đề Điều chuẩn của các văn bản nội bộ đã biết trong hệ thống
 */
const KNOWN_ARTICLE_TITLES: Record<string, Record<string, string>> = {
  'DOC-102': {
    '1': 'Phạm vi điều chỉnh',
    '2': 'Đối tượng áp dụng',
    '3': 'Giải thích từ ngữ',
    '4': 'Nguyên tắc',
    '5': 'Rà soát hồ sơ định kỳ',
    '6': 'Nội dung rà soát',
    '7': 'Hồ sơ mở quan hệ',
    '8': 'Xử lý thông tin không còn phù hợp',
    '9': 'Trách nhiệm của đơn vị và của khách hàng',
    '10': 'Lưu trữ',
    '11': 'Báo cáo',
    '12': 'Hiệu lực thi hành',
  },
  'doc-cv-01': {
    '1': 'Phạm vi điều chỉnh',
    '2': 'Đối tượng áp dụng',
    '3': 'Thời hạn cho vay',
    '4': 'Hạn mức cho vay không có tài sản bảo đảm',
    '5': 'Giải ngân',
    '6': 'Lãi suất chậm trả',
    '7': 'Điều chỉnh lãi suất',
  },
}

/**
 * Trọng số mức độ tác động để chọn mức cao nhất khi gom nhóm theo Điều
 */
const severityWeight: Record<Severity, number> = {
  high: 3,
  medium: 2,
  low: 1,
}

/**
 * Cấu hình hiển thị mức độ tác động cho từng Điều khoản
 */
const severityConfig: Record<Severity, { label: string; className: string }> = {
  high: {
    label: 'Tác động: Cao',
    className: 'bg-red-500/10 text-red-600 border-red-500/30 dark:text-red-400',
  },
  medium: {
    label: 'Tác động: Trung bình',
    className: 'bg-amber-500/10 text-amber-600 border-amber-500/30 dark:text-amber-400',
  },
  low: {
    label: 'Tác động: Thấp',
    className: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/30 dark:text-emerald-400',
  },
}

export interface GroupedArticle {
  key: string
  title: string
  highestSeverity: Severity
  impactCount: number
  leadImpactId: string
}

/**
 * Trích xuất định danh và tiêu đề đầy đủ của Điều cha từ location và docId
 * Định dạng: "Điều X: Tên điều"
 */
export function extractArticleInfo(
  location: string,
  docId?: string
): { articleKey: string; articleTitle: string } {
  const trimmed = location.trim()

  // 1. Trường hợp dạng "Điều X, khoản Y" hoặc "Điều X. Tiêu đề..."
  const dieuMatch = trimmed.match(/^Điều\s+(\d+)(?:[.,\s:]+(.+))?/i)
  if (dieuMatch) {
    const num = dieuMatch[1]
    let title = dieuMatch[2]?.trim()

    // Bỏ qua nếu phần sau chỉ là "khoản Y"
    if (title && /^khoản\b/i.test(title)) {
      title = ''
    }

    // Tra cứu tiêu đề Điều chính thức nếu chưa có
    if (!title && docId && KNOWN_ARTICLE_TITLES[docId]?.[num]) {
      title = KNOWN_ARTICLE_TITLES[docId][num]
    }

    const articleKey = `Điều ${num}`
    const articleTitle = title ? `Điều ${num}: ${title}` : `Điều ${num}`
    return { articleKey, articleTitle }
  }

  // 2. Trường hợp dạng "2.2. Đối tượng áp dụng" hoặc "5.6.d"
  const numberDotMatch = trimmed.match(/^(\d+)(?:\.[\w.]+)?(?:\s*[-–.:]\s*(.+))?$/)
  if (numberDotMatch) {
    const num = numberDotMatch[1]
    let title = numberDotMatch[2]?.trim()

    // Tra cứu tiêu đề Điều chính thức nếu chưa có
    if (!title && docId && KNOWN_ARTICLE_TITLES[docId]?.[num]) {
      title = KNOWN_ARTICLE_TITLES[docId][num]
    }

    const articleKey = `Điều ${num}`
    const articleTitle = title ? `Điều ${num}: ${title}` : `Điều ${num}`
    return { articleKey, articleTitle }
  }

  // 3. Trường hợp dạng "QD.1" hoặc "QD.2"
  if (/^qd\b/i.test(trimmed)) {
    return {
      articleKey: 'Quyết định',
      articleTitle: 'Quyết định ban hành',
    }
  }

  return {
    articleKey: trimmed,
    articleTitle: trimmed,
  }
}

/**
 * Gom nhóm các chunks con theo Điều khoản cha
 */
export function groupImpactsByArticle(docImpacts: Impact[], docId: string): GroupedArticle[] {
  const groupsMap = new Map<
    string,
    {
      articleKey: string
      articleTitle: string
      impacts: Impact[]
    }
  >()

  for (const imp of docImpacts) {
    const { articleKey, articleTitle } = extractArticleInfo(imp.location, docId)
    const existing = groupsMap.get(articleKey)
    if (existing) {
      existing.impacts.push(imp)
      // Ưu tiên tiêu đề có nội dung chi tiết nếu có
      if (articleTitle.includes(':') && !existing.articleTitle.includes(':')) {
        existing.articleTitle = articleTitle
      }
    } else {
      groupsMap.set(articleKey, {
        articleKey,
        articleTitle,
        impacts: [imp],
      })
    }
  }

  return Array.from(groupsMap.values()).map((group) => {
    let maxSev: Severity = 'low'
    let leadImp = group.impacts[0]

    for (const imp of group.impacts) {
      if ((severityWeight[imp.severity] ?? 0) >= (severityWeight[maxSev] ?? 0)) {
        maxSev = imp.severity
        leadImp = imp
      }
    }

    return {
      key: group.articleKey,
      title: group.articleTitle,
      highestSeverity: maxSev,
      impactCount: group.impacts.length,
      leadImpactId: leadImp.id,
    }
  })
}

export function VisualizePage() {
  const { vbplId } = useParams()
  const navigate = useNavigate()

  const vbpls = useVbpls()
  const impacts = useImpacts(vbplId)
  const documents = useDocuments()

  const containerRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  const vbpl = vbpls.data?.find((v) => v.id === vbplId)
  const all = impacts.data ?? []
  const docs = documents.data ?? []

  // Đảm bảo dữ liệu ổn định và có memoization tránh render lặp vô tận
  const { affectedDocs } = useMemo(() => {
    const knownDocIds = new Set(docs.map((d) => d.id))
    const synthesizedDocs: InternalDocument[] = Array.from(
      new Set(all.map((imp) => imp.documentId)),
    )
      .filter((docId) => !knownDocIds.has(docId))
      .map((docId) => ({
        id: docId,
        code: docId,
        title: docId,
        department: 'Nội bộ',
        version: '1.0',
        effectiveDate: '',
        pageCount: 1,
        pdfUrl: `/api/documents/${encodeURIComponent(docId)}/pdf`,
      }))
    const merged = [...docs, ...synthesizedDocs]
    const affectedDocIds = new Set(all.map((imp) => imp.documentId))
    const affected = merged.filter((doc) => affectedDocIds.has(doc.id))
    return { allDocs: merged, affectedDocs: affected }
  }, [docs, all])

  // Vẽ các đường nối cong SVG trực tiếp vào DOM (không qua React state, tuyệt đối tránh render loop)
  const drawEdges = useCallback(() => {
    const svg = svgRef.current
    const container = containerRef.current
    if (!svg || !container) return

    const containerRect = container.getBoundingClientRect()

    // Xóa sạch các path và circle cũ trước khi vẽ lại
    while (svg.firstChild) {
      svg.removeChild(svg.firstChild)
    }

    // 1. Nối từ Root (VBPL) sang từng Document
    const rootEl = container.querySelector<HTMLElement>('[data-node="root"]')
    if (rootEl) {
      const rootRect = rootEl.getBoundingClientRect()
      const startX = rootRect.right - containerRect.left
      const startY = rootRect.top + rootRect.height / 2 - containerRect.top

      const docEls = container.querySelectorAll<HTMLElement>('[data-doc-id]')
      docEls.forEach((docEl) => {
        const docRect = docEl.getBoundingClientRect()
        const endX = docRect.left - containerRect.left
        const endY = docRect.top + docRect.height / 2 - containerRect.top

        const dx = Math.max(endX - startX, 40)
        const d =
          Math.abs(startY - endY) < 2
            ? `M ${startX} ${startY} L ${endX} ${endY}`
            : `M ${startX} ${startY} C ${startX + dx * 0.45} ${startY}, ${endX - dx * 0.45} ${endY}, ${endX} ${endY}`

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path')
        path.setAttribute('d', d)
        path.setAttribute('fill', 'none')
        path.setAttribute('stroke', '#3b82f6')
        path.setAttribute('stroke-width', '2.5')
        path.setAttribute('stroke-linecap', 'round')
        path.setAttribute('opacity', '0.9')
        svg.appendChild(path)

        // Điểm chấm ở đầu và cuối đường nối
        const startDot = document.createElementNS('http://www.w3.org/2000/svg', 'circle')
        startDot.setAttribute('cx', String(startX))
        startDot.setAttribute('cy', String(startY))
        startDot.setAttribute('r', '3.5')
        startDot.setAttribute('fill', '#3b82f6')
        svg.appendChild(startDot)

        const endDot = document.createElementNS('http://www.w3.org/2000/svg', 'circle')
        endDot.setAttribute('cx', String(endX))
        endDot.setAttribute('cy', String(endY))
        endDot.setAttribute('r', '3.5')
        endDot.setAttribute('fill', '#60a5fa')
        svg.appendChild(endDot)

        // 2. Nối từ Document sang các Điều khoản (Articles) thuộc về Document đó
        const docId = docEl.getAttribute('data-doc-id')
        const docStartX = docRect.right - containerRect.left
        const docStartY = docRect.top + docRect.height / 2 - containerRect.top

        const articleEls = container.querySelectorAll<HTMLElement>(`[data-article-doc="${docId}"]`)
        articleEls.forEach((artEl) => {
          const artRect = artEl.getBoundingClientRect()
          const artEndX = artRect.left - containerRect.left
          const artEndY = artRect.top + artRect.height / 2 - containerRect.top

          const cdx = Math.max(artEndX - docStartX, 30)
          const artD =
            Math.abs(docStartY - artEndY) < 2
              ? `M ${docStartX} ${docStartY} L ${artEndX} ${artEndY}`
              : `M ${docStartX} ${docStartY} C ${docStartX + cdx * 0.45} ${docStartY}, ${artEndX - cdx * 0.45} ${artEndY}, ${artEndX} ${artEndY}`

          const artPath = document.createElementNS('http://www.w3.org/2000/svg', 'path')
          artPath.setAttribute('d', artD)
          artPath.setAttribute('fill', 'none')
          artPath.setAttribute('stroke', '#60a5fa')
          artPath.setAttribute('stroke-width', '2')
          artPath.setAttribute('stroke-linecap', 'round')
          artPath.setAttribute('opacity', '0.85')
          svg.appendChild(artPath)

          // Điểm chấm vào Điều khoản
          const artDot = document.createElementNS('http://www.w3.org/2000/svg', 'circle')
          artDot.setAttribute('cx', String(artEndX))
          artDot.setAttribute('cy', String(artEndY))
          artDot.setAttribute('r', '3')
          artDot.setAttribute('fill', '#60a5fa')
          svg.appendChild(artDot)
        })

        if (articleEls.length > 0) {
          const docExitDot = document.createElementNS('http://www.w3.org/2000/svg', 'circle')
          docExitDot.setAttribute('cx', String(docStartX))
          docExitDot.setAttribute('cy', String(docStartY))
          docExitDot.setAttribute('r', '3.5')
          docExitDot.setAttribute('fill', '#3b82f6')
          svg.appendChild(docExitDot)
        }
      })
    }
  }, [])

  useEffect(() => {
    drawEdges()
    const animId = requestAnimationFrame(drawEdges)
    const timer = setTimeout(drawEdges, 100)

    const ro = new ResizeObserver(() => {
      drawEdges()
    })

    if (containerRef.current) {
      ro.observe(containerRef.current)
    }
    window.addEventListener('resize', drawEdges)

    return () => {
      cancelAnimationFrame(animId)
      clearTimeout(timer)
      ro.disconnect()
      window.removeEventListener('resize', drawEdges)
    }
  }, [drawEdges, affectedDocs, all])

  if (vbpls.isLoading || impacts.isLoading || documents.isLoading) {
    return <VisualizeSkeleton />
  }

  if (vbpls.isError || impacts.isError || documents.isError) {
    return (
      <ErrorState
        error={vbpls.error || impacts.error || documents.error}
        onRetry={() => {
          vbpls.refetch()
          impacts.refetch()
          documents.refetch()
        }}
        className="flex-1 justify-center"
      />
    )
  }

  if (!vbpl) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4">
        <EmptyState
          title="Không tìm thấy văn bản pháp luật"
          description="Văn bản quy phạm pháp luật không tồn tại hoặc đã bị xóa."
        />
        <Button asChild variant="outline">
          <Link to="/">Quay về hộp thư</Link>
        </Button>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col bg-background">
      {/* Top Navigation Taskbar */}
      <header className="flex h-14 shrink-0 items-center justify-between border-b bg-card px-4 lg:px-6">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="sm"
            asChild
            className="h-8 gap-1.5 text-xs font-semibold text-muted-foreground hover:text-foreground cursor-pointer"
          >
            <Link to={`/review/${vbpl.id}`}>
              <ArrowLeft className="size-4" />
              <span>Quay lại duyệt văn bản</span>
            </Link>
          </Button>
          <div className="h-4 w-px bg-border" />
          <div className="flex items-center gap-2">
            <Network className="size-4 text-primary" />
            <span className="text-sm font-bold text-foreground">Sơ đồ cây liên kết văn bản</span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground">
            Tác động: <strong className="font-semibold text-foreground">{affectedDocs.length} văn bản nội bộ liên quan</strong>
          </span>
        </div>
      </header>

      {/* Main Canvas Area */}
      <div className="flex-1 overflow-auto bg-muted/15 p-6 lg:p-10">
        {affectedDocs.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-4">
            <EmptyState
              title="Chưa có văn bản nội bộ liên kết"
              description="AI chưa phát hiện tác động nào tới các văn bản nội bộ trong hệ thống."
            />
            <Button asChild variant="outline">
              <Link to={`/review/${vbpl.id}`}>Quay lại trang duyệt</Link>
            </Button>
          </div>
        ) : (
          <div
            ref={containerRef}
            className="relative mx-auto flex min-w-[1050px] max-w-7xl items-center justify-start gap-16 lg:gap-20 py-12 px-6"
          >
            {/* SVG Connecting Paths Layer */}
            <svg
              ref={svgRef}
              className="pointer-events-none absolute inset-0 size-full z-0 overflow-visible"
              aria-hidden="true"
            />

            {/* LEVEL 1: UPLOADED LEGAL DOCUMENT (ROOT NODE) */}
            <div data-node="root" className="relative z-10 w-80 shrink-0 lg:w-96">
              <div className="relative rounded-2xl border-2 border-primary/50 bg-card p-6 shadow-md transition-all hover:border-primary hover:shadow-lg">
                <div className="flex items-center gap-3">
                  <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-xs">
                    <Landmark className="size-6" />
                  </div>
                  <div>
                    <span className="inline-flex items-center rounded-md bg-primary/15 px-2.5 py-0.5 text-xs font-semibold text-primary">
                      Văn bản quy phạm pháp luật
                    </span>
                    <h2 className="mt-1 text-base font-bold text-foreground">
                      {vbpl.number}
                    </h2>
                  </div>
                </div>

                {/* Tên tài liệu */}
                <p className="mt-4 text-sm font-semibold leading-relaxed text-foreground">
                  {vbpl.title}
                </p>
              </div>
            </div>

            {/* LEVEL 2 & 3: INTERNAL DOCUMENTS AND THEIR GROUPED ARTICLES */}
            <div className="relative z-10 flex flex-col justify-center gap-10">
              {affectedDocs.map((doc) => {
                const kind = getDocumentKind(doc.title, doc.code)
                const isNộiQuy = kind === 'Nội quy'
                const docImpacts = all.filter((i) => i.documentId === doc.id)
                const groupedArticles = groupImpactsByArticle(docImpacts, doc.code || doc.id)

                return (
                  <div key={doc.id} className="flex items-center gap-14 lg:gap-18">
                    {/* LEVEL 2: DOCUMENT CARD */}
                    <div
                      data-doc-id={doc.id}
                      onClick={() => navigate(`/review/${vbpl.id}?doc=${encodeURIComponent(doc.id)}`)}
                      className="group relative w-72 lg:w-80 shrink-0 flex flex-col justify-between rounded-xl border-2 border-border/80 bg-card p-5 shadow-sm transition-all duration-200 hover:border-primary/70 hover:shadow-md cursor-pointer"
                    >
                      <div>
                        {/* Phân loại: Nội quy hay Quy định */}
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <div className="flex size-7 items-center justify-center rounded-md bg-primary/10 text-primary">
                              <FileText className="size-4" />
                            </div>
                            <span className="font-mono text-xs font-semibold text-muted-foreground">
                              {doc.code}
                            </span>
                          </div>
                          <span
                            className={`inline-flex items-center rounded-md px-2.5 py-0.5 text-xs font-bold border ${
                              isNộiQuy
                                ? 'bg-purple-500/10 text-purple-600 border-purple-500/20 dark:text-purple-400'
                                : 'bg-blue-500/10 text-blue-600 border-blue-500/20 dark:text-blue-400'
                            }`}
                          >
                            {kind}
                          </span>
                        </div>

                        {/* Tên tài liệu */}
                        <h3 className="mt-3 text-sm font-bold text-foreground transition-colors group-hover:text-primary">
                          {doc.title}
                        </h3>
                      </div>

                      <div className="mt-4 pt-3 border-t">
                        <Button
                          size="sm"
                          variant="ghost"
                          className="w-full justify-between p-0 h-auto text-xs font-semibold text-primary group-hover:text-primary cursor-pointer hover:bg-transparent"
                        >
                          <span>Duyệt văn bản này</span>
                          <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-1" />
                        </Button>
                      </div>
                    </div>

                    {/* LEVEL 3: ARTICLES BRANCHING FOR THIS DOCUMENT */}
                    {groupedArticles.length > 0 && (
                      <div className="flex flex-col justify-center gap-4">
                        {groupedArticles.map((article) => {
                          const sev = severityConfig[article.highestSeverity] ?? {
                            label: `Tác động: ${article.highestSeverity || 'Khác'}`,
                            className: 'bg-muted text-muted-foreground border-border',
                          }

                          return (
                            <div
                              key={article.key}
                              data-article-key={article.key}
                              data-article-doc={doc.id}
                              onClick={() =>
                                navigate(
                                  `/review/${vbpl.id}?doc=${encodeURIComponent(doc.id)}&impact=${encodeURIComponent(article.leadImpactId)}`
                                )
                              }
                              className="group relative w-72 lg:w-80 shrink-0 rounded-xl border-2 border-border/70 bg-card p-4 shadow-2xs transition-all duration-200 hover:border-primary/60 hover:shadow-md cursor-pointer"
                            >
                              <div className="flex items-center justify-between gap-1.5 text-xs text-muted-foreground mb-1.5">
                                <div className="flex items-center gap-1.5">
                                  <BookmarkCheck className="size-3.5 text-primary" />
                                  <span className="font-semibold uppercase tracking-wider text-[10px]">
                                    Điều khoản
                                  </span>
                                </div>
                                {article.impactCount > 1 && (
                                  <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                                    {article.impactCount} điểm tác động
                                  </span>
                                )}
                              </div>

                              {/* Tiêu đề của Điều khoản cha theo định dạng "Điều 5: Tên điều" */}
                              <h4 className="text-sm font-bold text-foreground tracking-tight group-hover:text-primary transition-colors line-clamp-2">
                                {article.title}
                              </h4>

                              {/* Tag mức độ tác động cao nhất (Thấp, Trung bình, Cao) */}
                              <div className="mt-3 flex items-center justify-between border-t pt-2.5">
                                <span
                                  className={cn(
                                    'inline-flex items-center rounded-md px-2 py-0.5 text-xs font-bold border',
                                    sev.className
                                  )}
                                >
                                  {sev.label}
                                </span>
                                <span className="text-[11px] font-medium text-primary opacity-0 group-hover:opacity-100 transition-opacity">
                                  Xem chi tiết →
                                </span>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function VisualizeSkeleton() {
  return (
    <div className="flex h-full flex-col bg-background" aria-busy="true">
      <div className="flex h-14 items-center justify-between border-b bg-card px-6">
        <Skeleton className="h-6 w-56" />
        <Skeleton className="h-6 w-32" />
      </div>
      <div className="flex flex-1 items-center justify-center p-12">
        <div className="flex w-full max-w-5xl items-center justify-between gap-12">
          <Skeleton className="h-44 w-80 rounded-2xl" />
          <div className="flex flex-col gap-6 w-72">
            <Skeleton className="h-28 w-full rounded-xl" />
            <Skeleton className="h-28 w-full rounded-xl" />
          </div>
          <div className="flex flex-col gap-4 w-56">
            <Skeleton className="h-20 w-full rounded-xl" />
            <Skeleton className="h-20 w-full rounded-xl" />
            <Skeleton className="h-20 w-full rounded-xl" />
          </div>
        </div>
      </div>
    </div>
  )
}
