import { CheckCircle2, Database, RefreshCw, Server, XCircle, type LucideIcon } from 'lucide-react'

import { ErrorState } from '@/components/query-states'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useHealth } from '@/hooks/queries'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'

const checkInfo: Record<string, { label: string; description: string; Icon: LucideIcon }> = {
  database: { label: 'PostgreSQL + pgvector', description: 'Kết nối CSDL và extension vector', Icon: Database },
  agent: { label: 'Agent (LangGraph)', description: 'Dịch vụ phân tích tác động, cổng 8080', Icon: Server },
}

/** Live backend readiness. Never mocked, in either API mode. */
export function SystemPage() {
  const { data, error, isPending, isFetching, refetch, dataUpdatedAt } = useHealth()

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <div className="flex flex-wrap items-end gap-4">
        <div className="flex-1">
          <h1 className="text-xl font-semibold">Trạng thái hệ thống</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Dữ liệu thật từ <code className="rounded bg-muted px-1">/api/health/ready</code>, tự làm mới mỗi 10 giây.
          </p>
        </div>
        <Button variant="outline" onClick={() => refetch()} disabled={isFetching}>
          <RefreshCw className={cn(isFetching && 'animate-spin motion-reduce:animate-none')} aria-hidden />
          Kiểm tra lại
        </Button>
      </div>

      {error && data && (
        <p role="alert" className="flex items-center gap-2 rounded-lg bg-status-rejected/15 px-4 py-3 text-sm font-medium text-status-rejected-fg">
          <XCircle className="size-5 shrink-0" aria-hidden />
          Mất kết nối backend API. Kết quả dưới đây là lần kiểm tra thành công gần nhất.
        </p>
      )}

      {error && !data ? (
        <div className="rounded-lg border bg-card">
          <ErrorState error={error} onRetry={refetch} />
          <p className="pb-6 text-center text-xs text-muted-foreground">Không kết nối được backend API (cổng 8000).</p>
        </div>
      ) : isPending ? (
        <div className="space-y-3">
          <Skeleton className="h-16" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      ) : (
        <>
          <div
            role="status"
            className={cn(
              'flex items-center gap-3 rounded-lg px-4 py-3',
              data.status === 'ok' ? 'bg-status-accepted/15 text-status-accepted-fg' : 'bg-status-rejected/15 text-status-rejected-fg',
            )}
          >
            {data.status === 'ok' ? <CheckCircle2 className="size-5" aria-hidden /> : <XCircle className="size-5" aria-hidden />}
            <p className="font-medium">
              {data.status === 'ok' ? 'Tất cả dịch vụ hoạt động bình thường' : 'Có dịch vụ đang gặp sự cố'}
            </p>
            <p className="ml-auto text-xs">Cập nhật {formatDateTime(new Date(dataUpdatedAt).toISOString())}</p>
          </div>
          <ul className="divide-y rounded-lg border bg-card">
            {Object.entries(data.checks).map(([name, result]) => {
              const info = checkInfo[name] ?? { label: name, description: '', Icon: Server }
              const ok = result === 'ok'
              return (
                <li key={name} className="flex items-start gap-4 p-4">
                  <info.Icon className="mt-0.5 size-5 text-muted-foreground" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{info.label}</p>
                    <p className="text-sm text-muted-foreground">{info.description}</p>
                    {!ok && (
                      <pre className="mt-2 overflow-x-auto rounded-md bg-muted p-2 text-xs whitespace-pre-wrap text-status-rejected-fg">
                        {result}
                      </pre>
                    )}
                  </div>
                  <span
                    className={cn(
                      'inline-flex h-6 items-center gap-1 rounded-md px-2 text-xs font-medium',
                      ok ? 'bg-status-accepted/15 text-status-accepted-fg' : 'bg-status-rejected/15 text-status-rejected-fg',
                    )}
                  >
                    {ok ? <CheckCircle2 className="size-3.5" aria-hidden /> : <XCircle className="size-3.5" aria-hidden />}
                    {ok ? 'Hoạt động' : 'Lỗi'}
                  </span>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </div>
  )
}
