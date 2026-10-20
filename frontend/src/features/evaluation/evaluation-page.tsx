import { ArrowDownRight, ArrowUpRight, FlaskConical, GraduationCap } from 'lucide-react'
import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { apiMode } from '@/api/client'
import type { EvalMetrics, EvalRun, FeedbackStatus } from '@/api/types'
import { EmptyState, ErrorState } from '@/components/query-states'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { useEvalRuns, useFeedbackStatus } from '@/hooks/queries'
import { formatDateTime, formatNumber, formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'

interface Metric {
  label: string
  /** `null` when that step was not measured for this run; the tile then shows a dash. */
  read: (m: EvalMetrics) => number | null
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
  // Feedback can accumulate before any eval run is saved, so show the RLHF section even here.
  if (data.length === 0)
    return (
      <div className="mx-auto max-w-6xl space-y-6 p-6">
        <EmptyState title="Chưa có lượt đánh giá nào" description="Chạy experiment KHOA-01 để có số liệu." />
        <FeedbackLearningSection />
      </div>
    )

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

      <FeedbackLearningSection />
    </div>
  )
}

/** KHOA-02: makes the feedback loop visible — how much HITL feedback has been gathered toward a
 *  DPO dataset, and the few-shot examples being served. Read-only; building is a CLI. */
function FeedbackLearningSection() {
  const { data, isPending } = useFeedbackStatus()

  if (isPending) {
    return (
      <section className="rounded-lg border bg-card p-4">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="mt-4 h-20" />
      </section>
    )
  }

  return (
    <section className="rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <GraduationCap className="size-4 text-primary" aria-hidden />
          Học từ phản hồi (RLHF)
        </h2>
        {data && <ReadyBadge status={data} />}
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        Mỗi lượt duyệt (chấp nhận / sửa / từ chối) thành tín hiệu học: few-shot động và cặp preference cho DPO.
      </p>

      {!data ? (
        <p className="mt-4 text-sm text-muted-foreground">Chưa đọc được dữ liệu phản hồi.</p>
      ) : (
        <FeedbackLearningBody status={data} />
      )}
    </section>
  )
}

function ReadyBadge({ status }: { status: FeedbackStatus }) {
  const remaining = Math.max(0, status.minPairs - status.pairsUsable)
  return status.ready ? (
    <span className="rounded bg-status-accepted/15 px-2 py-0.5 text-xs font-medium text-status-accepted-fg">
      Sẵn sàng tạo dataset DPO
    </span>
  ) : (
    <span className="rounded bg-status-pending/15 px-2 py-0.5 text-xs font-medium text-status-pending-fg">
      Đang gom — còn thiếu {remaining} cặp
    </span>
  )
}

function FeedbackLearningBody({ status }: { status: FeedbackStatus }) {
  const { pairsUsable, minPairs, ready, decisionsRead, byAction, draftExamples, judgeExamples, draftFailures } = status
  const pct = minPairs > 0 ? Math.min(100, Math.round((pairsUsable / minPairs) * 100)) : 0

  return (
    <>
      <div className="mt-4">
        <div className="flex items-baseline justify-between text-sm">
          <span className="font-medium">Cặp preference cho DPO</span>
          <span className="tabular-nums text-muted-foreground">
            {pairsUsable} / {minPairs}
          </span>
        </div>
        <div
          className="mt-1 h-2 w-full overflow-hidden rounded-full bg-muted"
          role="img"
          aria-label={`${pairsUsable} trên ${minPairs} cặp preference cho DPO`}
        >
          <div
            className={cn('h-full rounded-full transition-all', ready ? 'bg-status-accepted' : 'bg-primary')}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-4">
        <Stat label="Quyết định đã gom" value={decisionsRead} />
        <Stat label="Chấp nhận / Sửa / Từ chối" value={`${byAction.accept} / ${byAction.edit} / ${byAction.reject}`} />
        <Stat label="Few-shot drafter (dương / âm)" value={`${draftExamples.positiveAvailable} / ${draftExamples.negativeAvailable}`} />
        <Stat label="Few-shot judge (dương / âm)" value={`${judgeExamples.positiveAvailable} / ${judgeExamples.negativeAvailable}`} />
      </dl>

      <p className="mt-4 text-xs text-muted-foreground">
        {ready ? 'Đủ ngưỡng — xuất dataset bằng ' : `Khi đủ ${minPairs} cặp, xuất dataset bằng `}
        <code className="rounded bg-muted px-1 py-0.5 text-[11px]">python -m app.evaluation.dpo_pipeline build</code>
        {draftFailures > 0 && ` · ${draftFailures} bản nháp lỗi/bỏ qua không tạo được cặp.`}
      </p>
    </>
  )
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold tabular-nums">{value}</dd>
    </div>
  )
}

function MetricValue({ metric, run, baseline }: { metric: Metric; run: EvalRun; baseline?: EvalRun }) {
  const value = metric.read(run.metrics)
  const before = baseline ? metric.read(baseline.metrics) : null
  // A delta needs both runs to have measured it; comparing against an unmeasured run would
  // present "not measured" as a change.
  const delta = value === null || before === null ? undefined : value - before
  const improved = delta !== undefined && (metric.lowerIsBetter ? delta < 0 : delta > 0)
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{metric.label}</dt>
      <dd className="mt-1 flex items-baseline gap-2">
        <span className="text-2xl font-semibold">
          {value === null ? <span title="Chưa đo được">—</span> : metric.format(value)}
        </span>
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
    step.metrics.flatMap((metric) => {
      const before = metric.read(baseline.metrics)
      const after = metric.read(run.metrics)
      // A bar pair needs both sides. Plotting an unmeasured metric as 0 would invent a regression.
      if (!metric.chartLabel || before === null || after === null) return []
      return [
        {
          name: metric.chartLabel,
          before: Math.round(before * 1000) / 10,
          after: Math.round(after * 1000) / 10,
        },
      ]
    }),
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
