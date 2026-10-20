import {
  AlertCircle,
  BookOpen,
  Calendar,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FileText,
  Info,
  Layers,
  Loader2,
  Scale,
  Search,
  Upload,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import type { DocumentClause, DocumentObligation, InternalDocument } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

import { ImpactTree } from './impact-tree'
import { groupClauses } from './impact-tree-data'
import {
  useDocumentClauses,
  useDocuments,
  useIngestInternalDocument,
  useIngestInternalStatus,
} from '@/hooks/queries'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'

export function InternalDocumentsPage() {
  const { data: documents, isLoading: isLoadingDocs, refetch: refetchDocs } = useDocuments()
  const { data: ingestStatus } = useIngestInternalStatus()
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null)
  const [searchDocQuery, setSearchDocQuery] = useState('')
  const [searchClauseQuery, setSearchClauseQuery] = useState('')
  const [isPdfModalOpen, setIsPdfModalOpen] = useState(false)
  const [ingestSuccessMessage, setIngestSuccessMessage] = useState<string | null>(null)
  const [ingestErrorMessage, setIngestErrorMessage] = useState<string | null>(null)
  const [expandedArticles, setExpandedArticles] = useState<Record<string, boolean>>({})
  const [activeTab, setActiveTab] = useState('details')
  const [pendingClauseId, setPendingClauseId] = useState<string | null>(null)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const ingestDocMutation = useIngestInternalDocument()

  // Auto-refresh document list when a background ingest completes
  const prevProcessingRef = useRef(false)
  useEffect(() => {
    if (prevProcessingRef.current && !ingestStatus?.is_processing) {
      setIngestSuccessMessage(null)
      setIngestErrorMessage(null)
      if (ingestStatus?.status === 'completed') {
        refetchDocs()
        if (ingestStatus.result?.document_id) {
          setSelectedDocId(ingestStatus.result.document_id)
        }
      }
    }
    prevProcessingRef.current = Boolean(ingestStatus?.is_processing)
  }, [ingestStatus, refetchDocs])

  // Filter internal documents by search query
  const filteredDocs = useMemo(() => {
    if (!documents) return []
    const q = searchDocQuery.trim().toLowerCase()
    if (!q) return documents
    return documents.filter(
      (d) =>
        d.id.toLowerCase().includes(q) ||
        d.code.toLowerCase().includes(q) ||
        d.title.toLowerCase().includes(q) ||
        d.department.toLowerCase().includes(q),
    )
  }, [documents, searchDocQuery])

  // Active document
  const activeDocId = selectedDocId || (filteredDocs.length > 0 ? filteredDocs[0].id : null)
  const activeDoc = useMemo(
    () => documents?.find((d) => d.id === activeDocId) ?? (filteredDocs.length > 0 ? filteredDocs[0] : null),
    [documents, activeDocId, filteredDocs],
  )

  // Query clauses for active document
  const { data: clauseData, isLoading: isLoadingClauses } = useDocumentClauses(activeDoc?.id)

  // Organize clauses into Chapters & Articles (shared with the impact tree so node ids line up)
  const { articleGroups, chapters } = useMemo(
    () => (clauseData?.clauses ? groupClauses(clauseData.clauses) : { articleGroups: [], chapters: [] }),
    [clauseData],
  )

  // Obligations indexed by source clause ID
  const obligationsByClause = useMemo(() => {
    const map = new Map<string, DocumentObligation[]>()
    if (!clauseData?.obligations) return map
    for (const obl of clauseData.obligations) {
      const list = map.get(obl.source_clause_id) ?? []
      list.push(obl)
      map.set(obl.source_clause_id, list)
    }
    return map
  }, [clauseData])

  // Filtered article groups based on search inside clauses
  const filteredArticleGroups = useMemo(() => {
    const q = searchClauseQuery.trim().toLowerCase()
    if (!q) return articleGroups

    return articleGroups
      .map((ag) => {
        const matchingClauses = ag.clauses.filter(
          (c) =>
            c.numbering.toLowerCase().includes(q) ||
            (c.heading && c.heading.toLowerCase().includes(q)) ||
            c.text.toLowerCase().includes(q),
        )
        return {
          ...ag,
          matchingClauses,
        }
      })
      .filter((ag) => {
        const articleMatches =
          ag.numbering.toLowerCase().includes(q) || (ag.heading && ag.heading.toLowerCase().includes(q))
        return articleMatches || (ag.matchingClauses && ag.matchingClauses.length > 0)
      })
  }, [articleGroups, searchClauseQuery])

  const toggleArticle = (id: string) => {
    setExpandedArticles((prev) => ({
      ...prev,
      [id]: prev[id] === undefined ? false : !prev[id],
    }))
  }

  const expandAll = () => {
    const next: Record<string, boolean> = {}
    for (const ag of articleGroups) next[ag.id] = true
    setExpandedArticles(next)
  }

  const collapseAll = () => {
    const next: Record<string, boolean> = {}
    for (const ag of articleGroups) next[ag.id] = false
    setExpandedArticles(next)
  }

  // Open a clause from the impact tree: switch to the detail tab, expand it, then scroll to it.
  const openClause = (clauseId: string) => {
    setSearchClauseQuery('')
    setExpandedArticles((prev) => ({ ...prev, [clauseId]: true }))
    setActiveTab('details')
    setPendingClauseId(clauseId)
  }

  useEffect(() => {
    if (!pendingClauseId || activeTab !== 'details' || isLoadingClauses) return
    const id = pendingClauseId
    const raf = requestAnimationFrame(() => {
      document.getElementById(`article-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      setPendingClauseId(null)
    })
    return () => cancelAnimationFrame(raf)
  }, [pendingClauseId, activeTab, isLoadingClauses])

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    setIngestSuccessMessage(null)
    setIngestErrorMessage(null)

    try {
      const res = await ingestDocMutation.mutateAsync(file)
      setIngestSuccessMessage(
        res.message || `Đã tiếp nhận tệp "${file.name}", hệ thống đang xử lý ngầm...`,
      )
      if (res.document_id) {
        setSelectedDocId(res.document_id)
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Lỗi nạp văn bản nội bộ.'
      setIngestErrorMessage(msg)
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col md:flex-row overflow-hidden bg-background">
      {/* LEFT SUBHEADER / INGEST & DOCUMENT LIST PANEL */}
      <aside className="w-full shrink-0 border-r border-border bg-sidebar/50 md:w-80 lg:w-96 flex flex-col h-full min-h-0 overflow-hidden">
        {/* Header */}
        <div className="p-4 border-b border-border space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold flex items-center gap-2">
                <FileText className="size-4 text-primary" />
                Văn bản nội bộ
              </h2>
              <p className="text-xs text-muted-foreground mt-0.5">
                {documents ? `${documents.length} tài liệu đã lập chỉ mục` : 'Đang tải dữ liệu...'}
              </p>
            </div>
            <Badge variant="outline" className="text-xs bg-primary/10 text-primary border-primary/20">
              RIA Engine
            </Badge>
          </div>

          {/* MANUAL INGEST BOX */}
          <div className="rounded-lg border border-primary/20 bg-primary/5 p-3 space-y-2.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-primary flex items-center gap-1.5">
                <Upload className="size-3.5" />
                Ingest thủ công
              </span>
              <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                PDF
              </Badge>
            </div>

            <p className="text-[11px] leading-tight text-muted-foreground">
              Tải lên tệp PDF quy định, quy trình nội bộ mới để phân tích và lập chỉ mục vào kho.
            </p>

            {/* Live background processing banner: persists across page reloads */}
            {ingestStatus?.is_processing && (
              <div className="rounded-md border border-primary/40 bg-primary/10 p-2.5 space-y-1.5 animate-pulse">
                <div className="flex items-center gap-2 text-primary font-semibold text-xs">
                  <Loader2 className="size-3.5 animate-spin shrink-0" />
                  <span className="truncate">Đang xử lý: {ingestStatus.filename}</span>
                </div>
                <p className="text-[11px] text-muted-foreground leading-snug">
                  {ingestStatus.message || 'Đang phân tích cấu trúc điều khoản và lập chỉ mục vector...'}
                </p>
                {ingestStatus.progress && (
                  <Badge variant="secondary" className="text-[10px] h-4 font-normal">
                    Tiến độ: {ingestStatus.progress}
                  </Badge>
                )}
              </div>
            )}

            <div className="flex gap-2">
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,application/pdf"
                className="hidden"
                onChange={handleFileUpload}
              />
              <Button
                size="sm"
                className="w-full h-8 text-xs font-medium"
                onClick={() => fileInputRef.current?.click()}
                disabled={ingestDocMutation.isPending || Boolean(ingestStatus?.is_processing)}
              >
                {ingestDocMutation.isPending || ingestStatus?.is_processing ? (
                  <>
                    <Loader2 className="size-3.5 animate-spin mr-1.5" />
                    Đang xử lý {ingestStatus?.filename ? `(${ingestStatus.filename})` : ''}...
                  </>
                ) : (
                  <>
                    <Upload className="size-3.5 mr-1.5" />
                    Chọn tệp PDF nội bộ
                  </>
                )}
              </Button>
            </div>

            {/* Ingest messages */}
            {ingestSuccessMessage && (
              <div className="rounded border border-emerald-500/30 bg-emerald-500/10 p-2 text-[11px] text-emerald-700 dark:text-emerald-300 flex items-start gap-1.5">
                <CheckCircle2 className="size-3.5 shrink-0 mt-0.5 text-emerald-600 dark:text-emerald-400" />
                <span>{ingestSuccessMessage}</span>
              </div>
            )}
            {ingestErrorMessage && (
              <div className="rounded border border-destructive/30 bg-destructive/10 p-2 text-[11px] text-destructive flex items-start gap-1.5">
                <AlertCircle className="size-3.5 shrink-0 mt-0.5" />
                <span>{ingestErrorMessage}</span>
              </div>
            )}
            {!ingestStatus?.is_processing && ingestStatus?.status === 'completed' && ingestStatus.message && !ingestSuccessMessage && (
              ingestStatus.result?.unchanged ? (
                <div className="rounded border border-amber-500/30 bg-amber-500/10 p-2 text-[11px] text-amber-700 dark:text-amber-300 flex items-start gap-1.5">
                  <Info className="size-3.5 shrink-0 mt-0.5 text-amber-600 dark:text-amber-400" />
                  <span>{ingestStatus.message}</span>
                </div>
              ) : (
                <div className="rounded border border-emerald-500/30 bg-emerald-500/10 p-2 text-[11px] text-emerald-700 dark:text-emerald-300 flex items-start gap-1.5">
                  <CheckCircle2 className="size-3.5 shrink-0 mt-0.5 text-emerald-600 dark:text-emerald-400" />
                  <span>{ingestStatus.message}</span>
                </div>
              )
            )}
            {!ingestStatus?.is_processing && ingestStatus?.status === 'failed' && ingestStatus.message && !ingestErrorMessage && (
              <div className="rounded border border-destructive/30 bg-destructive/10 p-2 text-[11px] text-destructive flex items-start gap-1.5">
                <AlertCircle className="size-3.5 shrink-0 mt-0.5" />
                <span>{ingestStatus.message}</span>
              </div>
            )}
          </div>

          {/* Search internal docs */}
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
            <Input
              type="search"
              placeholder="Tìm mã tài liệu, tên quy định..."
              value={searchDocQuery}
              onChange={(e) => setSearchDocQuery(e.target.value)}
              className="h-8 pl-8 text-xs"
            />
          </div>
        </div>

        {/* Document list */}
        <div className="flex-1 min-h-0 overflow-y-auto p-2">
          {isLoadingDocs ? (
            <div className="space-y-2 p-2">
              <Skeleton className="h-16 w-full rounded-md" />
              <Skeleton className="h-16 w-full rounded-md" />
              <Skeleton className="h-16 w-full rounded-md" />
            </div>
          ) : filteredDocs.length === 0 ? (
            <div className="p-6 text-center text-xs text-muted-foreground">
              {searchDocQuery ? (
                'Không tìm thấy văn bản phù hợp'
              ) : ingestStatus?.is_processing ? (
                <div className="space-y-2.5 py-6">
                  <Loader2 className="size-5 animate-spin mx-auto text-primary" />
                  <p className="font-medium text-foreground text-xs">Đang đồng bộ văn bản nội bộ...</p>
                  <p className="text-[11px] text-muted-foreground leading-relaxed">
                    {ingestStatus.message || 'Backend đang tự động nạp các văn bản từ thư mục data/ vào cơ sở dữ liệu.'}
                  </p>
                </div>
              ) : (
                <div className="space-y-2 py-6">
                  <FileText className="size-8 mx-auto text-muted-foreground/40" />
                  <p className="font-medium text-foreground text-xs">Chưa có văn bản nội bộ nào</p>
                  <p className="text-[11px] text-muted-foreground leading-relaxed max-w-xs mx-auto">
                    Nhấn vào nút &quot;Chọn tệp PDF nội bộ&quot; ở trên để tải lên và phân tích văn bản.
                  </p>
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-1.5">
              {filteredDocs.map((doc: InternalDocument) => {
                const isSelected = doc.id === activeDoc?.id
                return (
                  <button
                    key={doc.id}
                    onClick={() => setSelectedDocId(doc.id)}
                    className={cn(
                      'w-full text-left rounded-lg p-2.5 transition-all text-xs border',
                      isSelected
                        ? 'border-primary bg-primary/10 shadow-xs ring-1 ring-primary/30'
                        : 'border-border/60 hover:bg-muted/60 bg-card/60',
                    )}
                  >
                    <div className="flex items-center justify-between gap-1 mb-1">
                      <span className="font-semibold text-primary">{doc.code || doc.id}</span>
                      <Badge variant="outline" className="text-[10px] px-1 py-0 h-4">
                        {doc.version || 'v1.0'}
                      </Badge>
                    </div>
                    <p className="line-clamp-2 text-foreground font-medium text-[11px] leading-tight">
                      {doc.title}
                    </p>
                    <div className="mt-2 flex items-center justify-between text-[10px] text-muted-foreground">
                      <span>{doc.department}</span>
                      <span>{doc.pageCount} trang</span>
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </aside>

      {/* RIGHT MAIN PANEL - DETAILS & CLAUSES */}
      <section className="flex-1 flex flex-col h-full min-h-0 overflow-hidden">
        {activeDoc ? (
          <>
            {/* Header info */}
            <div className="p-4 md:px-6 border-b border-border bg-card/40 flex flex-wrap items-center justify-between gap-3 shrink-0">
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge className="bg-primary text-primary-foreground font-semibold text-xs">
                    {activeDoc.code || activeDoc.id}
                  </Badge>
                  <Badge variant="outline" className="text-xs">
                    Phiên bản: {activeDoc.version || 'v1.0'}
                  </Badge>
                  <Badge
                    variant="outline"
                    className="border-emerald-500/30 text-emerald-700 dark:text-emerald-300 bg-emerald-500/10 text-xs"
                  >
                    Đang có hiệu lực
                  </Badge>
                </div>
                <h1 className="text-lg md:text-xl font-bold tracking-tight text-foreground">
                  {activeDoc.title}
                </h1>
                <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground pt-0.5">
                  <span className="flex items-center gap-1">
                    <Scale className="size-3.5 text-muted-foreground" />
                    Đơn vị: <strong className="text-foreground">{activeDoc.department}</strong>
                  </span>
                  {activeDoc.effectiveDate && (
                    <span className="flex items-center gap-1">
                      <Calendar className="size-3.5 text-muted-foreground" />
                      Hiệu lực: <strong className="text-foreground">{formatDate(activeDoc.effectiveDate)}</strong>
                    </span>
                  )}
                  {clauseData && (
                    <span className="flex items-center gap-1">
                      <Layers className="size-3.5 text-muted-foreground" />
                      Điều khoản:{' '}
                      <strong className="text-foreground">{clauseData.total_clauses} mục trích xuất</strong>
                    </span>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 text-xs gap-1.5"
                  onClick={() => setIsPdfModalOpen(true)}
                >
                  <ExternalLink className="size-3.5" />
                  Xem PDF gốc
                </Button>
              </div>
            </div>

            {/* TABS CONTAINER */}
            <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col min-h-0 h-full overflow-hidden gap-0">
              <div className="border-b border-border px-4 md:px-6 bg-muted/20 flex items-center justify-between shrink-0">
                <TabsList className="bg-transparent h-11 p-0 gap-4">
                  <TabsTrigger
                    value="overview"
                    className="data-[state=active]:border-b-2 data-[state=active]:border-primary data-[state=active]:bg-transparent rounded-none h-11 px-2 text-xs font-medium"
                  >
                    Tổng quan
                  </TabsTrigger>
                  <TabsTrigger
                    value="details"
                    className="data-[state=active]:border-b-2 data-[state=active]:border-primary data-[state=active]:bg-transparent rounded-none h-11 px-2 text-xs font-semibold text-primary"
                  >
                    Nội dung chi tiết
                  </TabsTrigger>
                  <TabsTrigger
                    value="source"
                    className="data-[state=active]:border-b-2 data-[state=active]:border-primary data-[state=active]:bg-transparent rounded-none h-11 px-2 text-xs font-medium"
                  >
                    Tài liệu gốc
                  </TabsTrigger>
                  <TabsTrigger
                    value="impact-tree"
                    className="data-[state=active]:border-b-2 data-[state=active]:border-primary data-[state=active]:bg-transparent rounded-none h-11 px-2 text-xs font-medium"
                  >
                    Đồ thị tác động
                  </TabsTrigger>
                </TabsList>

                {clauseData && (
                  <div className="text-xs text-muted-foreground flex items-center gap-2">
                    <span className="hidden sm:inline">Trích xuất:</span>
                    <Badge variant="secondary" className="text-[11px] font-normal">
                      {clauseData.total_clauses} điều khoản
                    </Badge>
                    <Badge variant="secondary" className="text-[11px] font-normal">
                      {clauseData.total_obligations} nghĩa vụ pháp lý
                    </Badge>
                  </div>
                )}
              </div>

              {/* TAB 1: TỔNG QUAN */}
              <TabsContent value="overview" className="flex-1 min-h-0 overflow-y-auto p-4 md:p-6 space-y-6 data-[state=inactive]:hidden">
                <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                  <Card>
                    <CardHeader className="pb-2">
                      <CardDescription className="text-xs">Mã văn bản / Số hiệu</CardDescription>
                      <CardTitle className="text-base">{activeDoc.code || activeDoc.id}</CardTitle>
                    </CardHeader>
                    <CardContent className="text-xs text-muted-foreground">
                      Mã định danh duy nhất trong hệ thống quản lý văn bản nội bộ.
                    </CardContent>
                  </Card>

                  <Card>
                    <CardHeader className="pb-2">
                      <CardDescription className="text-xs">Đơn vị chủ trì / Sở hữu</CardDescription>
                      <CardTitle className="text-base">{activeDoc.department}</CardTitle>
                    </CardHeader>
                    <CardContent className="text-xs text-muted-foreground">
                      Khối nghiệp vụ chịu trách nhiệm tuân thủ và cập nhật quy chế.
                    </CardContent>
                  </Card>

                  <Card>
                    <CardHeader className="pb-2">
                      <CardDescription className="text-xs">Ngày bắt đầu hiệu lực</CardDescription>
                      <CardTitle className="text-base">
                        {activeDoc.effectiveDate ? formatDate(activeDoc.effectiveDate) : 'Đang cập nhật'}
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="text-xs text-muted-foreground">
                      Thời điểm chính thức có hiệu lực thi hành nội bộ ACB.
                    </CardContent>
                  </Card>
                </div>

                {clauseData && (
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-sm font-semibold">Cấu trúc pháp lý được trích xuất (RIA Parser)</CardTitle>
                      <CardDescription className="text-xs">
                        Tự động phân tách các tầng Chương, Điều, Khoản, Điểm và Nghĩa vụ (Obligation)
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
                        <div className="rounded-lg border bg-muted/40 p-3">
                          <p className="text-2xl font-bold text-primary">{chapters.length}</p>
                          <p className="text-xs text-muted-foreground mt-1">Chương</p>
                        </div>
                        <div className="rounded-lg border bg-muted/40 p-3">
                          <p className="text-2xl font-bold text-primary">{articleGroups.length}</p>
                          <p className="text-xs text-muted-foreground mt-1">Điều</p>
                        </div>
                        <div className="rounded-lg border bg-muted/40 p-3">
                          <p className="text-2xl font-bold text-primary">{clauseData.total_clauses}</p>
                          <p className="text-xs text-muted-foreground mt-1">Khoản & Điểm</p>
                        </div>
                        <div className="rounded-lg border bg-muted/40 p-3">
                          <p className="text-2xl font-bold text-primary">{clauseData.total_obligations}</p>
                          <p className="text-xs text-muted-foreground mt-1">Nghĩa vụ pháp lý</p>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                )}
              </TabsContent>

              {/* TAB 2: NỘI DUNG CHI TIẾT (ACTIVE / PRIORITY TAB) */}
              <TabsContent value="details" className="flex-1 flex flex-col min-h-0 h-full overflow-hidden p-0 m-0 border-0 data-[state=active]:flex data-[state=inactive]:hidden">
                {/* Search & Filter Toolbar inside Tab 2 */}
                <div className="p-3 md:px-6 border-b border-border bg-card/60 flex flex-wrap items-center justify-between gap-3 shrink-0">
                  <div className="flex flex-wrap items-center gap-2 flex-1 max-w-lg">
                    <div className="relative w-full max-w-xs">
                      <Search className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
                      <Input
                        type="search"
                        placeholder="Tìm kiếm nội dung điều, khoản..."
                        value={searchClauseQuery}
                        onChange={(e) => setSearchClauseQuery(e.target.value)}
                        className="h-8 pl-8 text-xs"
                      />
                    </div>
                  </div>

                  <div className="flex items-center gap-2 text-xs">
                    <Button variant="ghost" size="sm" className="h-7 text-xs text-muted-foreground" onClick={expandAll}>
                      Mở rộng tất cả
                    </Button>
                    <span className="text-muted-foreground">·</span>
                    <Button variant="ghost" size="sm" className="h-7 text-xs text-muted-foreground" onClick={collapseAll}>
                      Thu gọn tất cả
                    </Button>
                  </div>
                </div>

                {/* Main Clauses List View */}
                <div className="flex-1 min-h-0 overflow-y-auto p-4 md:p-6">
                  {isLoadingClauses ? (
                    <div className="space-y-4 max-w-4xl mx-auto">
                      <Skeleton className="h-24 w-full rounded-lg" />
                      <Skeleton className="h-32 w-full rounded-lg" />
                      <Skeleton className="h-28 w-full rounded-lg" />
                    </div>
                  ) : filteredArticleGroups.length === 0 ? (
                    <div className="text-center py-16 text-muted-foreground space-y-2">
                      <BookOpen className="size-8 mx-auto text-muted-foreground/60" />
                      <p className="text-sm font-medium">Không tìm thấy nội dung phù hợp</p>
                      <p className="text-xs">Thử tìm kiếm với từ khóa khác hoặc xóa bộ lọc.</p>
                    </div>
                  ) : (
                    <div className="max-w-4xl mx-auto space-y-6 pb-12">
                      {filteredArticleGroups.map((group) => {
                        const isExpanded = expandedArticles[group.id] !== false
                        const displayClauses = group.matchingClauses || group.clauses

                        return (
                          <div
                            key={group.id}
                            id={`article-${group.id}`}
                            className="rounded-xl border border-border bg-card shadow-xs overflow-hidden transition-all scroll-mt-4"
                          >
                            {/* Article Header */}
                            <div
                              onClick={() => toggleArticle(group.id)}
                              className="p-3.5 md:px-4 bg-muted/40 hover:bg-muted/70 transition-colors cursor-pointer flex items-center justify-between gap-3 border-b border-border/70"
                            >
                              <div className="flex items-center gap-2.5 flex-1 min-w-0">
                                <button
                                  type="button"
                                  className="text-muted-foreground hover:text-foreground shrink-0"
                                >
                                  {isExpanded ? (
                                    <ChevronDown className="size-4" />
                                  ) : (
                                    <ChevronRight className="size-4" />
                                  )}
                                </button>
                                <div className="space-y-0.5 min-w-0">
                                  {group.chapterHeading && (
                                    <p className="text-[10px] font-semibold tracking-wider uppercase text-primary">
                                      {group.chapterHeading}
                                    </p>
                                  )}
                                  <h3 className="text-sm font-bold text-foreground truncate">
                                    {group.heading && group.heading.toLowerCase().includes('điều')
                                      ? group.heading
                                      : `Điều ${group.numbering}: ${group.heading || ''}`}
                                  </h3>
                                </div>
                              </div>

                              <div className="flex items-center gap-2 shrink-0">
                                {group.page && (
                                  <Badge variant="outline" className="text-[10px] h-5 bg-background">
                                    Trang {group.page}
                                  </Badge>
                                )}
                                <Badge variant="secondary" className="text-[10px] h-5 font-normal">
                                  {group.clauses.length} khoản
                                </Badge>
                              </div>
                            </div>

                            {/* Article Clauses Content */}
                            {isExpanded && (
                              <div className="divide-y divide-border/50 p-2 md:p-3 space-y-1">
                                {displayClauses.map((clause: DocumentClause) => {
                                  const obligations = obligationsByClause.get(clause.clause_id) || []
                                  const isPoint = clause.level === 'point'
                                  const isArticleHeader = clause.level === 'article'

                                  return (
                                    <div
                                      key={clause.clause_id}
                                      className={cn(
                                        'py-2 px-3 rounded-md transition-colors',
                                        isPoint ? 'ml-6 border-l-2 border-primary/30 pl-3 bg-muted/20' : '',
                                        obligations.length > 0 ? 'bg-amber-500/5' : '',
                                      )}
                                    >
                                      {/* Clause Numbering & Text */}
                                      <div className="flex items-start gap-2.5">
                                        <Badge
                                          variant="outline"
                                          className={cn(
                                            'text-[10px] px-1.5 py-0 h-4 shrink-0 mt-0.5 font-mono',
                                            isPoint ? 'text-primary' : 'text-muted-foreground',
                                          )}
                                        >
                                          {clause.numbering}
                                        </Badge>
                                        <div className="flex-1 space-y-1">
                                          {clause.heading && !isArticleHeader && (
                                            <p className="text-xs font-semibold text-foreground">
                                              {clause.heading}
                                            </p>
                                          )}
                                          <p className="text-xs leading-relaxed text-foreground/90 whitespace-pre-wrap">
                                            {clause.text}
                                          </p>
                                        </div>
                                      </div>

                                      {/* Extracted Obligations */}
                                      {obligations.length > 0 && (
                                        <div className="mt-2.5 ml-8 space-y-2 border-t border-border/40 pt-2">
                                          {obligations.map((obl) => {
                                            const modalityColor =
                                              obl.modality === 'must'
                                                ? 'bg-blue-500/10 text-blue-700 dark:text-blue-300 border-blue-500/30'
                                                : obl.modality === 'must_not'
                                                  ? 'bg-red-500/10 text-red-700 dark:text-red-300 border-red-500/30'
                                                  : 'bg-purple-500/10 text-purple-700 dark:text-purple-300 border-purple-500/30'

                                            const modalityLabel =
                                              obl.modality === 'must'
                                                ? 'Bắt buộc thực hiện'
                                                : obl.modality === 'must_not'
                                                  ? 'Nghiêm cấm'
                                                  : 'Được phép'

                                            return (
                                              <div
                                                key={obl.obligation_id}
                                                className="rounded-md border border-border/80 bg-background/80 p-2.5 text-xs space-y-1.5 shadow-2xs"
                                              >
                                                <div className="flex items-center justify-between gap-2">
                                                  <Badge
                                                    variant="outline"
                                                    className={cn('text-[10px] font-semibold', modalityColor)}
                                                  >
                                                    {modalityLabel}
                                                  </Badge>
                                                  {obl.subject && (
                                                    <span className="text-[11px] text-muted-foreground">
                                                      Chủ thể:{' '}
                                                      <strong className="text-foreground">{obl.subject}</strong>
                                                    </span>
                                                  )}
                                                </div>

                                                <p className="text-xs text-foreground/90 font-medium">
                                                  {obl.text}
                                                </p>

                                                {(obl.condition || obl.deadline) && (
                                                  <div className="flex flex-wrap gap-2 text-[10px] text-muted-foreground pt-1">
                                                    {obl.condition && <span>Điều kiện: {obl.condition}</span>}
                                                    {obl.deadline && <span>Thời hạn: {obl.deadline}</span>}
                                                  </div>
                                                )}
                                              </div>
                                            )
                                          })}
                                        </div>
                                      )}
                                    </div>
                                  )
                                })}
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              </TabsContent>

              {/* TAB 3: TÀI LIỆU GỐC */}
              <TabsContent
                value="source"
                className="flex-1 flex flex-col min-h-0 h-full overflow-hidden p-0 m-0 border-0 data-[state=active]:flex data-[state=inactive]:hidden"
              >
                {activeDoc.pdfUrl ? (
                  <div className="flex-1 min-h-0 flex flex-col">
                    <div className="flex items-center justify-between px-4 md:px-6 py-2 border-b bg-muted/20 shrink-0">
                      <p className="text-xs text-muted-foreground">Bản PDF gốc, chưa qua xử lý.</p>
                      <Button variant="outline" size="sm" asChild className="h-7 text-xs gap-1.5">
                        <a href={activeDoc.pdfUrl} target="_blank" rel="noreferrer">
                          <ExternalLink className="size-3.5" />
                          Mở trong tab mới
                        </a>
                      </Button>
                    </div>
                    <iframe src={activeDoc.pdfUrl} title="Tài liệu gốc" className="flex-1 w-full min-h-0 border-0" />
                  </div>
                ) : (
                  <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-muted-foreground">
                    <FileText className="size-10 mb-3 text-muted-foreground/40" />
                    <p className="text-sm">Chưa có tài liệu gốc để hiển thị.</p>
                  </div>
                )}
              </TabsContent>

              {/* TAB 4: ĐỒ THỊ TÁC ĐỘNG */}
              <TabsContent
                value="impact-tree"
                className="flex-1 flex flex-col min-h-0 h-full overflow-hidden p-0 m-0 border-0 data-[state=active]:flex data-[state=inactive]:hidden"
              >
                <ImpactTree
                  doc={activeDoc}
                  docs={documents ?? []}
                  activeDocId={activeDoc.id}
                  clauses={clauseData?.clauses ?? []}
                  onOpenClause={openClause}
                />
              </TabsContent>
            </Tabs>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-muted-foreground">
            <FileText className="size-12 mb-3 text-muted-foreground/40" />
            <h3 className="text-base font-semibold text-foreground">Chưa chọn văn bản nội bộ</h3>
            <p className="text-xs max-w-sm mt-1">
              Hãy chọn một văn bản từ danh sách bên trái hoặc tải lên văn bản mới bằng công cụ Ingest dữ liệu.
            </p>
          </div>
        )}
      </section>

      {/* PDF VIEWER MODAL */}
      <Dialog open={isPdfModalOpen} onOpenChange={setIsPdfModalOpen}>
        <DialogContent className="max-w-5xl h-[85vh] flex flex-col p-4">
          <DialogHeader className="flex flex-row items-center justify-between pb-2 border-b">
            <div>
              <DialogTitle className="text-base font-semibold">
                {activeDoc?.code || activeDoc?.id} — {activeDoc?.title}
              </DialogTitle>
              <p className="text-xs text-muted-foreground">Bản sao điện tử PDF chính thức từ kho lưu trữ ACB</p>
            </div>
            {activeDoc && (
              <Button variant="outline" size="sm" asChild className="h-7 text-xs">
                <a href={activeDoc.pdfUrl} target="_blank" rel="noreferrer">
                  Mở trong tab mới
                </a>
              </Button>
            )}
          </DialogHeader>
          <div className="flex-1 w-full h-full pt-2">
            {activeDoc && (
              <iframe
                src={activeDoc.pdfUrl}
                title="Bản xem trước PDF"
                className="w-full h-full rounded border border-border"
              />
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
