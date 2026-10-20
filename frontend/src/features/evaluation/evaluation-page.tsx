import {
  ArrowDownRight,
  ArrowUpRight,
  FlaskConical,
  GraduationCap,
  Search,
  Sparkles,
  Target,
  Timer,
  TriangleAlert,
} from 'lucide-react'
import { useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  RadialBar,
  RadialBarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { apiMode } from '@/api/client'
import type { EvalMetrics, EvalRun, FeedbackStatus } from '@/api/types'
import { EmptyState, ErrorState } from '@/components/query-states'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { useEvalRuns, useFeedbackStatus } from '@/hooks/queries'
import { formatDateTime, formatNumber, formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'

/** vi-VN decimal comma for chart tooltips (the rest of the UI uses lib/format). */
const vi = (n: number | string) => String(n).replace('.', ',')
/** Shared recharts tooltip surface so every chart matches the card theme. */
const tooltipStyle = {
  background: 'var(--popover)',
  border: '1px solid var(--border)',
  borderRadius: 8,
  color: 'var(--popover-foreground)',
  fontSize: 12,
} as const

interface Metric {
  label: string
  /** `null` when that step was not measured for this run; the tile then shows a dash. */
  read: (m: EvalMetrics) => number | null
  format: (value: number) => string
  /** Latency and cost improve when they go down. */
  lowerIsBetter?: boolean
  /** Full-scale value for the inline gauge bar (1 = ratio, 5 = judge score). Unbounded metrics
   *  (latency, cost) omit it and show no bar. */
  gaugeMax?: number
  /** Shown in the before/after chart under this label; omitted metrics stay out of the chart. */
  chartLabel?: string
}

const steps: { title: string; description: string; metrics: Metric[] }[] = [
  {
    title: 'Tách thay đổi',
    description: 'Điều khoản mới, sửa đổi, bãi bỏ tách từ VBPL',
    metrics: [
      { label: 'Precision', read: (m) => m.extraction.precision, format: formatPercent, gaugeMax: 1 },
      { label: 'Recall', read: (m) => m.extraction.recall, format: formatPercent, gaugeMax: 1 },
    ],
  },
  {
    title: 'Truy xuất văn bản nội bộ',
    description: 'Tìm đúng đoạn văn bản nội bộ liên quan',
    metrics: [
      { label: 'Recall@5', read: (m) => m.retrieval.recallAtK, format: formatPercent, gaugeMax: 1, chartLabel: 'Recall@5' },
      { label: 'MRR', read: (m) => m.retrieval.mrr, format: (v) => formatNumber(v, 3), gaugeMax: 1, chartLabel: 'MRR' },
    ],
  },
  {
    title: 'Phát hiện tác động',
    description: 'Đánh giá có bị ảnh hưởng, loại và mức độ (ưu tiên Recall)',
    metrics: [
      { label: 'Precision', read: (m) => m.impact.precision, format: formatPercent, gaugeMax: 1, chartLabel: 'Tác động P' },
      { label: 'Recall', read: (m) => m.impact.recall, format: formatPercent, gaugeMax: 1, chartLabel: 'Tác động R' },
      { label: 'F1', read: (m) => m.impact.f1, format: formatPercent, gaugeMax: 1, chartLabel: 'Tác động F1' },
    ],
  },
  {
    title: 'Gợi ý chỉnh sửa',
    description: 'Chất lượng văn bản đề xuất',
    metrics: [
      { label: 'Điểm LLM-judge (/5)', read: (m) => m.amendment.judgeScore, format: (v) => formatNumber(v, 2), gaugeMax: 5 },
      { label: 'Tỉ lệ chấp nhận HITL', read: (m) => m.amendment.hitlAcceptRate, format: formatPercent, gaugeMax: 1, chartLabel: 'Chấp nhận HITL' },
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

/** Headline tiles at the top — the four numbers a reviewer looks at first. */
const kpis: { label: string; icon: typeof Target; read: (m: EvalMetrics) => number | null; format: (v: number) => string; lowerIsBetter?: boolean }[] = [
  { label: 'Recall@5 truy xuất', icon: Search, read: (m) => m.retrieval.recallAtK, format: formatPercent },
  { label: 'F1 phát hiện tác động', icon: Target, read: (m) => m.impact.f1, format: formatPercent },
  { label: 'Điểm LLM-judge', icon: Sparkles, read: (m) => m.amendment.judgeScore, format: (v) => `${formatNumber(v, 2)}/5` },
  { label: 'Độ trễ mỗi văn bản', icon: Timer, read: (m) => m.system.latencySeconds, format: (v) => `${formatNumber(v, 1)}s`, lowerIsBetter: true },
]

/** Axes of the quality radar, each normalised to 0–1 (judge is /5). */
const radarAxes: { axis: string; read: (m: EvalMetrics) => number | null }[] = [
  { axis: 'Tách · P', read: (m) => m.extraction.precision },
  { axis: 'Tách · R', read: (m) => m.extraction.recall },
  { axis: 'Truy xuất R@5', read: (m) => m.retrieval.recallAtK },
  { axis: 'MRR', read: (m) => m.retrieval.mrr },
  { axis: 'Tác động F1', read: (m) => m.impact.f1 },
  { axis: 'LLM-judge', read: (m) => (m.amendment.judgeScore === null ? null : m.amendment.judgeScore / 5) },
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
            {run.datasetSize} mẫu ground truth · chạy lúc {formatDateTime(run.createdAt)}
            {run.note ? ` · ${run.note}` : ''}
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

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {kpis.map((kpi) => (
          <KpiTile key={kpi.label} kpi={kpi} run={run} baseline={baseline} />
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <QualityRadar run={run} baseline={baseline} />
        <WeakestPoint run={run} />
      </div>

      <div className="divide-y rounded-lg border bg-card">
        {steps.map((step) => (
          <section key={step.title} className="grid gap-4 p-4 md:grid-cols-[220px_1fr]">
            <div>
              <h2 className="text-sm font-semibold">{step.title}</h2>
              <p className="mt-1 text-xs text-muted-foreground">{step.description}</p>
            </div>
            <dl className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-x-6 gap-y-5">
              {step.metrics.map((metric) => (
                <MetricValue key={metric.label} metric={metric} run={run} baseline={baseline} />
              ))}
            </dl>
          </section>
        ))}
      </div>

      {data.length >= 3 && <TrendChart runs={data} />}
      {baseline && <ComparisonChart run={run} baseline={baseline} />}

      <FeedbackLearningSection />
    </div>
  )
}

function KpiTile({ kpi, run, baseline }: { kpi: (typeof kpis)[number]; run: EvalRun; baseline?: EvalRun }) {
  const value = kpi.read(run.metrics)
  const before = baseline ? kpi.read(baseline.metrics) : null
  const Icon = kpi.icon
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <span className="flex size-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="size-4" aria-hidden />
        </span>
        {kpi.label}
      </div>
      <div className="mt-3 flex items-end justify-between gap-2">
        <span className="text-3xl font-semibold tabular-nums">
          {value === null ? <span title="Chưa đo được">—</span> : kpi.format(value)}
        </span>
        <Delta value={value} before={before} lowerIsBetter={kpi.lowerIsBetter} format={kpi.format} baselineLabel={baseline?.label} />
      </div>
    </div>
  )
}

function QualityRadar({ run, baseline }: { run: EvalRun; baseline?: EvalRun }) {
  const rows = radarAxes.flatMap((a) => {
    const after = a.read(run.metrics)
    if (after === null) return []
    const before = baseline ? a.read(baseline.metrics) : null
    return [{ axis: a.axis, after: Math.round(after * 100), before: before === null ? null : Math.round(before * 100) }]
  })
  // A radar needs at least 3 spokes to read as an area rather than a line.
  if (rows.length < 3) return null
  return (
    <section className="rounded-lg border bg-card p-4 lg:col-span-2">
      <h2 className="text-sm font-semibold">Chất lượng theo bước</h2>
      <p className="mt-1 text-xs text-muted-foreground">Chuẩn hoá về 0–100% (LLM-judge quy đổi /5)</p>
      <div className="mt-2 h-72" role="img" aria-label={`Biểu đồ radar chất lượng của ${run.label}`}>
        <ResponsiveContainer width="100%" height="100%">
          <RadarChart data={rows} outerRadius="72%">
            <PolarGrid stroke="var(--border)" />
            <PolarAngleAxis dataKey="axis" tick={{ fill: 'var(--muted-foreground)', fontSize: 11 }} />
            <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
            {baseline && (
              <Radar name={baseline.label} dataKey="before" stroke="var(--chart-1)" fill="var(--chart-1)" fillOpacity={0.2} />
            )}
            <Radar name={run.label} dataKey="after" stroke="var(--chart-2)" fill="var(--chart-2)" fillOpacity={0.4} />
            <Tooltip contentStyle={tooltipStyle} formatter={(value) => (value === null ? '—' : `${vi(value as number)}%`)} />
            {baseline && <Legend wrapperStyle={{ fontSize: 12 }} />}
          </RadarChart>
        </ResponsiveContainer>
      </div>
    </section>
  )
}

/** Auto-surface the single lowest measured ratio so the room's eye goes to the real gap. */
function WeakestPoint({ run }: { run: EvalRun }) {
  const m = run.metrics
  const candidates: { label: string; norm: number; display: string }[] = [
    { label: 'Tách · Precision', norm: m.extraction.precision, display: formatPercent(m.extraction.precision) },
    { label: 'Tách · Recall', norm: m.extraction.recall, display: formatPercent(m.extraction.recall) },
    { label: 'Truy xuất · Recall@5', norm: m.retrieval.recallAtK, display: formatPercent(m.retrieval.recallAtK) },
    { label: 'Truy xuất · MRR', norm: m.retrieval.mrr, display: formatNumber(m.retrieval.mrr, 3) },
    { label: 'Tác động · Precision', norm: m.impact.precision, display: formatPercent(m.impact.precision) },
    { label: 'Tác động · Recall', norm: m.impact.recall, display: formatPercent(m.impact.recall) },
    { label: 'Tác động · F1', norm: m.impact.f1, display: formatPercent(m.impact.f1) },
  ]
  if (m.amendment.judgeScore !== null)
    candidates.push({ label: 'LLM-judge', norm: m.amendment.judgeScore / 5, display: `${formatNumber(m.amendment.judgeScore, 2)}/5` })

  const weakest = candidates.reduce((lo, c) => (c.norm < lo.norm ? c : lo))
  const pct = Math.round(weakest.norm * 100)

  return (
    <section className="flex flex-col rounded-lg border bg-card p-4">
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        <TriangleAlert className="size-4 text-status-pending-fg" aria-hidden />
        Điểm cần cải thiện
      </h2>
      <div className="mt-4 flex-1">
        <p className="text-sm font-medium">{weakest.label}</p>
        <p className="mt-1 text-3xl font-semibold tabular-nums">{weakest.display}</p>
        <div
          className="mt-3 h-2 w-full overflow-hidden rounded-full bg-muted"
          role="img"
          aria-label={`${weakest.label} đạt ${pct}%`}
        >
          <div className="h-full rounded-full bg-status-pending" style={{ width: `${pct}%` }} />
        </div>
      </div>
      <p className="mt-4 text-xs text-muted-foreground">
        Chỉ số thấp nhất trong các bước đo được — ưu tiên cải thiện trước.
      </p>
    </section>
  )
}

function Delta({
  value,
  before,
  lowerIsBetter,
  format,
  baselineLabel,
}: {
  value: number | null
  before: number | null
  lowerIsBetter?: boolean
  format: (v: number) => string
  baselineLabel?: string
}) {
  // A delta needs both runs to have measured it; comparing against an unmeasured run would
  // present "not measured" as a change.
  if (value === null || before === null) return null
  const delta = value - before
  if (delta === 0) return null
  const improved = lowerIsBetter ? delta < 0 : delta > 0
  const up = delta > 0
  return (
    <span
      className={cn('inline-flex items-center gap-0.5 text-xs font-medium', improved ? 'text-status-accepted-fg' : 'text-status-rejected-fg')}
      title={baselineLabel ? `So với ${baselineLabel}` : undefined}
    >
      {up ? <ArrowUpRight className="size-3.5" aria-hidden /> : <ArrowDownRight className="size-3.5" aria-hidden />}
      {up ? '+' : '−'}
      {format(Math.abs(delta))}
      <span className="sr-only">{improved ? ' (tốt hơn)' : ' (kém hơn)'}</span>
    </span>
  )
}

function MetricValue({ metric, run, baseline }: { metric: Metric; run: EvalRun; baseline?: EvalRun }) {
  const value = metric.read(run.metrics)
  const before = baseline ? metric.read(baseline.metrics) : null
  const gaugePct = value !== null && metric.gaugeMax ? Math.min(100, Math.max(0, (value / metric.gaugeMax) * 100)) : null
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{metric.label}</dt>
      <dd className="mt-1 flex items-baseline gap-2">
        <span className="text-2xl font-semibold tabular-nums">
          {value === null ? <span title="Chưa đo được">—</span> : metric.format(value)}
        </span>
        <Delta value={value} before={before} lowerIsBetter={metric.lowerIsBetter} format={metric.format} baselineLabel={baseline?.label} />
      </dd>
      {gaugePct !== null && (
        <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted" aria-hidden>
          <div className="h-full rounded-full bg-chart-2" style={{ width: `${gaugePct}%` }} />
        </div>
      )}
    </div>
  )
}

/** Trend of the headline ratios across every saved run (normalised to 0–100). */
function TrendChart({ runs }: { runs: EvalRun[] }) {
  const rows = runs.map((r) => ({
    name: r.label,
    r5: pctOrNull(r.metrics.retrieval.recallAtK),
    f1: pctOrNull(r.metrics.impact.f1),
    judge: r.metrics.amendment.judgeScore === null ? null : Math.round(r.metrics.amendment.judgeScore * 20),
    accept: pctOrNull(r.metrics.amendment.hitlAcceptRate),
  }))
  const lines: { key: string; name: string; color: string }[] = [
    { key: 'r5', name: 'Recall@5', color: 'var(--chart-2)' },
    { key: 'f1', name: 'Tác động F1', color: 'var(--chart-3)' },
    { key: 'judge', name: 'LLM-judge (×20)', color: 'var(--chart-4)' },
    { key: 'accept', name: 'Chấp nhận HITL', color: 'var(--chart-5)' },
  ]
  return (
    <section className="rounded-lg border bg-card p-4">
      <h2 className="text-sm font-semibold">Xu hướng qua các lượt đánh giá</h2>
      <p className="mt-1 text-xs text-muted-foreground">Chuẩn hoá về 0–100 (LLM-judge ×20); chỉ vẽ các mốc đã đo</p>
      <div className="mt-4 h-72" role="img" aria-label="Biểu đồ xu hướng các chỉ số qua các lượt đánh giá">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ left: -16, right: 8 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" />
            <XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} />
            <YAxis domain={[0, 100]} tickLine={false} axisLine={false} tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} />
            <Tooltip contentStyle={tooltipStyle} formatter={(value) => (value === null ? '—' : vi(value as number))} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {lines.map((l) => (
              <Line key={l.key} type="monotone" dataKey={l.key} name={l.name} stroke={l.color} strokeWidth={2} dot={{ r: 3 }} connectNulls />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
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
      <h2 className="text-sm font-semibold">So sánh chi tiết: {baseline.label} → {run.label}</h2>
      <p className="mt-1 text-xs text-muted-foreground">Đơn vị % (MRR × 100)</p>
      <div className="mt-4 h-72" role="img" aria-label={`Biểu đồ so sánh ${baseline.label} và ${run.label}`}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} barGap={4} margin={{ left: -16, right: 8 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" />
            <XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} />
            <YAxis domain={[0, 100]} tickLine={false} axisLine={false} tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} />
            <Tooltip
              cursor={{ fill: 'var(--muted)' }}
              contentStyle={tooltipStyle}
              formatter={(value) => `${vi(value as number)}%`}
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

  const actions = [
    { key: 'accept', label: 'Chấp nhận', value: byAction.accept, color: 'var(--status-accepted)' },
    { key: 'edit', label: 'Sửa', value: byAction.edit, color: 'var(--chart-4)' },
    { key: 'reject', label: 'Từ chối', value: byAction.reject, color: 'var(--status-rejected)' },
  ]
  const totalActions = actions.reduce((s, a) => s + a.value, 0)

  return (
    <div className="mt-4 grid gap-6 lg:grid-cols-[200px_1fr]">
      {/* progress ring toward the DPO threshold */}
      <div className="flex flex-col items-center">
        <div className="relative h-40 w-40">
          <ResponsiveContainer width="100%" height="100%">
            <RadialBarChart
              data={[{ name: 'DPO', value: pct }]}
              innerRadius="72%"
              outerRadius="100%"
              startAngle={90}
              endAngle={-270}
            >
              <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
              <RadialBar
                dataKey="value"
                cornerRadius={8}
                fill={ready ? 'var(--status-accepted)' : 'var(--chart-2)'}
                background={{ fill: 'var(--muted)' }}
              />
            </RadialBarChart>
          </ResponsiveContainer>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-2xl font-semibold tabular-nums">
              {pairsUsable}/{minPairs}
            </span>
            <span className="text-xs text-muted-foreground">cặp DPO</span>
          </div>
        </div>
        <p className="mt-2 text-center text-xs text-muted-foreground">{pct}% tới ngưỡng tạo dataset</p>
      </div>

      {/* action mix + few-shot counts */}
      <div className="grid gap-6 sm:grid-cols-[160px_1fr]">
        <div className="flex flex-col items-center">
          <div className="h-32 w-32" role="img" aria-label="Tỉ lệ chấp nhận / sửa / từ chối">
            {totalActions > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={actions} dataKey="value" nameKey="label" innerRadius={38} outerRadius={60} paddingAngle={2} stroke="var(--card)" strokeWidth={2}>
                    {actions.map((a) => (
                      <Cell key={a.key} fill={a.color} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={tooltipStyle} />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full items-center justify-center text-xs text-muted-foreground">Chưa có quyết định</div>
            )}
          </div>
          <ul className="mt-2 space-y-1 text-xs">
            {actions.map((a) => (
              <li key={a.key} className="flex items-center gap-1.5">
                <span className="size-2.5 rounded-sm" style={{ background: a.color }} aria-hidden />
                <span className="text-muted-foreground">{a.label}</span>
                <span className="ml-auto tabular-nums font-medium">{a.value}</span>
              </li>
            ))}
          </ul>
        </div>

        <dl className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] content-start gap-4">
          <Stat label="Quyết định đã gom" value={decisionsRead} />
          <Stat label="Few-shot drafter (dương / âm)" value={`${draftExamples.positiveAvailable} / ${draftExamples.negativeAvailable}`} />
          <Stat label="Few-shot judge (dương / âm)" value={`${judgeExamples.positiveAvailable} / ${judgeExamples.negativeAvailable}`} />
          {draftFailures > 0 && <Stat label="Nháp lỗi / bỏ qua" value={draftFailures} />}
        </dl>
      </div>

      <p className="text-xs text-muted-foreground lg:col-span-2">
        {ready ? 'Đủ ngưỡng — xuất dataset bằng ' : `Khi đủ ${minPairs} cặp, xuất dataset bằng `}
        <code className="rounded bg-muted px-1 py-0.5 text-[11px]">python -m app.evaluation.dpo_pipeline build</code>
        {draftFailures > 0 && ` · ${draftFailures} bản nháp lỗi/bỏ qua không tạo được cặp.`}
      </p>
    </div>
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

/** Ratio (0–1) to a rounded 0–100, or null so the trend line leaves a gap. */
function pctOrNull(value: number | null): number | null {
  return value === null ? null : Math.round(value * 100)
}

function EvaluationSkeleton() {
  return (
    <div className="mx-auto max-w-6xl space-y-4 p-6" aria-busy="true">
      <Skeleton className="h-12 w-1/2" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      {Array.from({ length: 3 }, (_, i) => (
        <Skeleton key={i} className="h-20" />
      ))}
    </div>
  )
}
