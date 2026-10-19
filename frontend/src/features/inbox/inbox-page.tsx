import { useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Check, Search } from 'lucide-react'
import { useNavigate, useSearchParams } from 'react-router'

import { api } from '@/api/client'
import type { VbplStatus } from '@/api/types'
import { EmptyState, ErrorState } from '@/components/query-states'
import { VbplStatusBadge } from '@/components/status-badges'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { queryKeys, useVbpls } from '@/hooks/queries'
import { formatDate } from '@/lib/format'
import { vbplStatusLabel } from '@/lib/labels'
import { cn } from '@/lib/utils'
import { UploadVbplDialog } from './upload-vbpl-dialog'

type Filter = 'all' | VbplStatus

const normalize = (text: string) => text.normalize('NFD').replace(/\p{Diacritic}/gu, '').replace(/đ/gi, 'd').toLowerCase()

export function InboxPage() {
  const { data, error, isPending, refetch } = useVbpls()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const query = params.get('q') ?? ''
  const filter = (params.get('status') as Filter | null) ?? 'all'

  const update = (key: string, value: string) =>
    setParams(
      (current) => {
        if (value && value !== 'all') current.set(key, value)
        else current.delete(key)
        return current
      },
      { replace: true },
    )

  const needle = normalize(query.trim())
  const rows = (data ?? [])
    .filter((vbpl) => filter === 'all' || vbpl.status === filter)
    .filter((vbpl) => !needle || normalize(`${vbpl.number} ${vbpl.title} ${vbpl.issuer}`).includes(needle))
    .sort((a, b) => b.receivedAt.localeCompare(a.receivedAt))

  const pendingTotal = data?.reduce((sum, vbpl) => sum + vbpl.pendingCount, 0) ?? 0

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div className="flex flex-wrap items-end gap-4">
        <div className="flex-1">
          <h1 className="text-xl font-semibold">Hộp thư VBPL</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {data ? `${data.length} văn bản mới từ NHNN · ${pendingTotal} tác động chờ duyệt` : 'Đang tải văn bản'}
          </p>
        </div>
        <UploadVbplDialog />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-xs">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            type="search"
            value={query}
            onChange={(event) => update('q', event.target.value)}
            placeholder="Lọc theo số hiệu, tiêu đề"
            aria-label="Lọc VBPL"
            className="h-9 pl-8 text-base md:text-sm"
          />
        </div>
        <ToggleGroup
          type="single"
          value={filter}
          onValueChange={(value) => value && update('status', value)}
          variant="outline"
          size="sm"
          aria-label="Lọc theo trạng thái xử lý"
          className="flex-wrap"
        >
          <ToggleGroupItem value="all">Tất cả</ToggleGroupItem>
          {(Object.keys(vbplStatusLabel) as VbplStatus[]).map((status) => (
            <ToggleGroupItem key={status} value={status}>
              {vbplStatusLabel[status]}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>

      <div className="rounded-lg border bg-card">
        {error ? (
          <ErrorState error={error} onRetry={refetch} />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-44">Số hiệu</TableHead>
                <TableHead>Tiêu đề</TableHead>
                <TableHead className="w-44">Cơ quan ban hành</TableHead>
                <TableHead className="w-28">Hiệu lực</TableHead>
                <TableHead className="w-32">Trạng thái</TableHead>
                <TableHead className="w-28 text-right">Chờ duyệt</TableHead>
                <TableHead className="w-10">
                  <span className="sr-only">Mở</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isPending &&
                Array.from({ length: 3 }, (_, i) => (
                  <TableRow key={i}>
                    <TableCell colSpan={7}>
                      <Skeleton className="h-10" />
                    </TableCell>
                  </TableRow>
                ))}
              {rows.map((vbpl) => {
                const canOpen = vbpl.impactCount > 0 && vbpl.status !== 'not_found'
                const open = () => {
                  if (canOpen) navigate(`/review/${vbpl.id}`)
                }
                return (
                  <TableRow
                    key={vbpl.id}
                    onClick={open}
                    onKeyDown={(event) => event.key === 'Enter' && open()}
                    onMouseEnter={() => {
                      if (canOpen) {
                        queryClient.prefetchQuery({
                          queryKey: queryKeys.impacts(vbpl.id),
                          queryFn: () => api.listImpacts(vbpl.id),
                        })
                      }
                    }}
                    tabIndex={canOpen ? 0 : -1}
                    aria-label={canOpen ? `Mở ${vbpl.number}` : vbpl.number}
                    className={cn(
                      'group outline-none',
                      canOpen
                        ? 'cursor-pointer focus-visible:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:ring-inset'
                        : 'cursor-default hover:bg-transparent'
                    )}
                  >
                    <TableCell className="font-medium">{vbpl.number}</TableCell>
                    <TableCell className="whitespace-normal">
                      <p className="line-clamp-1 font-medium">{vbpl.title}</p>
                      <p className="line-clamp-1 text-xs text-muted-foreground">{vbpl.summary}</p>
                    </TableCell>
                    <TableCell className="text-sm whitespace-normal text-muted-foreground">{vbpl.issuer}</TableCell>
                    <TableCell>{formatDate(vbpl.effectiveDate)}</TableCell>
                    <TableCell>
                      <VbplStatusBadge status={vbpl.status} />
                    </TableCell>
                    <TableCell className="text-right">
                      {vbpl.status === 'processing' ? (
                        <span className="text-xs text-muted-foreground">Chưa có</span>
                      ) : canOpen ? (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            open()
                          }}
                          className={cn(
                            'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition-all cursor-pointer shadow-xs',
                            vbpl.pendingCount > 0
                              ? 'bg-amber-500/15 text-amber-700 dark:text-amber-300 hover:bg-amber-500/25 border border-amber-500/30'
                              : 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-500/20 border border-emerald-500/25',
                          )}
                          title={`Nhấn để duyệt ${vbpl.number}`}
                        >
                          {vbpl.pendingCount > 0 ? (
                            <>
                              <span className="font-semibold">{vbpl.pendingCount}</span>
                              <span className="opacity-75">/{vbpl.impactCount} chờ duyệt</span>
                              <ArrowRight className="size-3 opacity-75 group-hover:translate-x-0.5 transition-transform" />
                            </>
                          ) : (
                            <>
                              <Check className="size-3 text-emerald-600" />
                              <span>{vbpl.impactCount}/{vbpl.impactCount} đã duyệt</span>
                            </>
                          )}
                        </button>
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          {vbpl.pendingCount}/{vbpl.impactCount}
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      {canOpen && (
                        <ArrowRight
                          className="size-4 text-muted-foreground transition-transform duration-200 group-hover:translate-x-0.5"
                          aria-hidden
                        />
                      )}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
        {!isPending && !error && rows.length === 0 && (
          <EmptyState title="Không có VBPL phù hợp" description="Thử bỏ bớt từ khóa hoặc bộ lọc trạng thái." />
        )}
      </div>
    </div>
  )
}
