import { ArrowDownRight, ArrowUpRight, FlaskConical } from 'lucide-react'
import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { apiMode } from '@/api/client'
import type { EvalMetrics, EvalRun } from '@/api/types'
import { EmptyState, ErrorState } from '@/components/query-states'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { useEvalRuns } from '@/hooks/queries'
import { formatDateTime, formatNumber, formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'

interface Metric {
  label: string
  read: (m: EvalMetrics) => number
  format: (value: number) => string
  /** Latency and cost improve when they go down. */
  lowerIsBetter?: boolean
  /** Shown in the before/after chart under this label; omitted metrics stay out of the chart. */
  chartLabel?: string
}

const steps: { title: string; description: string; metrics: Metric[] }[] = [
  {
    title: 'Tách thay đổi',
    description: 'Điều khoản mới, sửa đổi, bãi bỏ tách từ VBPL',
    metrics: [
      { label: 'Precision', read: (m) => m.extraction.precision, format: formatPercent },
      { label: 'Recall', read: (m) => m.extraction.recall, format: formatPercent },
    ],
  },
  {
    title: 'Truy xuất văn bản nội bộ',
    description: 'Tìm đúng đoạn văn bản nội bộ liên quan',
    metrics: [
      { label: 'Recall@5', read: (m) => m.retrieval.recallAtK, format: formatPercent, chartLabel: 'Recall@5' },
      { label: 'MRR', read: (m) => m.retrieval.mrr, format: (v) => formatNumber(v, 3), chartLabel: 'MRR' },
    ],
  },
  {
    title: 'Phát hiện tác động',
    description: 'Đánh giá có bị ảnh hưởng, loại và mức độ (ưu tiên Recall)',
    metrics: [
      { label: 'Precision', read: (m) => m.impact.precision, format: formatPercent, chartLabel: 'Tác động P' },
      { label: 'Recall', read: (m) => m.impact.recall, format: formatPercent, chartLabel: 'Tác động R' },
      { label: 'F1', read: (m) => m.impact.f1, format: formatPercent, chartLabel: 'Tác động F1' },
    ],
  },
  {
    title: 'Gợi ý chỉnh sửa',
    description: 'Chất lượng văn bản đề xuất',
    metrics: [
      { label: 'Điểm LLM-judge (/5)', read: (m) => m.amendment.judgeScore, format: (v) => formatNumber(v, 2) },
      { label: 'Tỉ lệ chấp nhận HITL', read: (m) => m.amendment.hitlAcceptRate, format: formatPercent, chartLabel: 'Chấp nhận HITL' },
    ],
  },
  {
    title: 'Hệ thống',
    description: 'Chi phí vận hành cho mỗi VBPL',
    metrics: [
      { label: 'Độ trễ (giây/văn bản)', read: (m) => m.system.latencySeconds, format: (v) => formatNumber(v, 1), lowerIsBetter: true },
      { label: 'Chi phí (USD/văn bản)', read: (m) => m.system.costUsdPerDocument, format: (v) => formatNumber(v, 3), lowerIsBetter: true },
    ],
  },
]

export function EvaluationPage() {
  const { data, error, isPending, refetch } = useEvalRuns()
  const [runId, setRunId] = useState<string>()

  if (error) return <ErrorState error={error} onRetry={refetch} />
  if (isPending) return <EvaluationSkeleton />
  if (data.length === 0) return <EmptyState title="Chưa có lượt đánh giá nào" description="Chạy experiment KHOA-01 để có số liệu." />

  const run = data.find((r) => r.id === runId) ?? data[data.length - 1]
  const runIndex = data.indexOf(run)
  const baseline = runIndex > 0 ? data[runIndex - 1] : undefined

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div className="flex flex-wrap items-end gap-4">
        <div className="flex-1">
          <h1 className="text-xl font-semibold">Đánh giá chất lượng</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {run.datasetSize} mẫu ground truth · chạy lúc {formatDateTime(run.createdAt)} · {run.note}
          </p>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="eval-run" className="text-xs font-medium text-muted-foreground">
            Lượt đánh giá
          </label>
          <Select value={run.id} onValueChange={setRunId}>
            <SelectTrigger id="eval-run" className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {data.map((r) => (
                <SelectItem key={r.id} value={r.id}>
                  {r.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {apiMode === 'mock' && (
        <p className="flex items-center gap-2 rounded-md bg-status-pending/15 px-3 py-2 text-sm text-status-pending-fg">
          <FlaskConical className="size-4 shrink-0" aria-hidden />
          Số liệu minh họa. Kết quả thật đến từ pipeline đánh giá KHOA-01.
        </p>
      )}

      <div className="divide-y rounded-lg border bg-card">
        {steps.map((step) => (
          <section key={step.title} className="grid gap-4 p-4 md:grid-cols-[220px_1fr]">
            <div>
              <h2 className="text-sm font-semibold">{step.title}</h2>
              <p className="mt-1 text-xs text-muted-foreground">{step.description}</p>
            </div>
            <dl className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-4">
              {step.metrics.map((metric) => (
                <MetricValue key={metric.label} metric={metric} run={run} baseline={baseline} />
              ))}
            </dl>
          </section>
        ))}
      </div>

      {baseline && <ComparisonChart run={run} baseline={baseline} />}
    </div>
  )
}

function MetricValue({ metric, run, baseline }: { metric: Metric; run: EvalRun; baseline?: EvalRun }) {
  const value = metric.read(run.metrics)
  const before = baseline ? metric.read(baseline.metrics) : undefined
  const delta = before === undefined ? undefined : value - before
  const improved = delta !== undefined && (metric.lowerIsBetter ? delta < 0 : delta > 0)
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{metric.label}</dt>
      <dd className="mt-1 flex items-baseline gap-2">
        <span className="text-2xl font-semibold">{metric.format(value)}</span>
        {delta !== undefined && delta !== 0 && (
          <span
            className={cn(
              'inline-flex items-center gap-0.5 text-xs font-medium',
              improved ? 'text-status-accepted-fg' : 'text-status-rejected-fg',
            )}
            title={`So với ${baseline?.label}`}
          >
            {delta > 0 ? <ArrowUpRight className="size-3.5" aria-hidden /> : <ArrowDownRight className="size-3.5" aria-hidden />}
            {delta > 0 ? '+' : '−'}
            {metric.format(Math.abs(delta))}
            <span className="sr-only">{improved ? ' (tốt hơn)' : ' (kém hơn)'}</span>
          </span>
        )}
      </dd>
    </div>
  )
}

function ComparisonChart({ run, baseline }: { run: EvalRun; baseline: EvalRun }) {
  const rows = steps.flatMap((step) =>
    step.metrics
      .filter((metric) => metric.chartLabel)
      .map((metric) => ({
        name: metric.chartLabel,
        before: Math.round(metric.read(baseline.metrics) * 1000) / 10,
        after: Math.round(metric.read(run.metrics) * 1000) / 10,
      })),
  )
  return (
    <section className="rounded-lg border bg-card p-4">
      <h2 className="text-sm font-semibold">Trước và sau phản hồi</h2>
      <p className="mt-1 text-xs text-muted-foreground">
        {baseline.label} so với {run.label}, đơn vị % (MRR × 100)
      </p>
      <div className="mt-4 h-72" role="img" aria-label={`Biểu đồ so sánh ${baseline.label} và ${run.label}`}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} barGap={4} margin={{ left: -16, right: 8 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" />
            <XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} />
            <YAxis domain={[0, 100]} tickLine={false} axisLine={false} tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} />
            <Tooltip
              cursor={{ fill: 'var(--muted)' }}
              contentStyle={{ background: 'var(--popover)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--popover-foreground)', fontSize: 12 }}
              formatter={(value) => `${String(value).replace('.', ',')}%`}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="before" name={baseline.label} fill="var(--chart-1)" radius={[4, 4, 0, 0]} />
            <Bar dataKey="after" name={run.label} fill="var(--chart-2)" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  )
}

function EvaluationSkeleton() {
  return (
    <div className="mx-auto max-w-6xl space-y-4 p-6" aria-busy="true">
      <Skeleton className="h-12 w-1/2" />
      {Array.from({ length: 5 }, (_, i) => (
        <Skeleton key={i} className="h-20" />
      ))}
    </div>
  )
}
