import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Clock,
  FileWarning,
  Link2Off,
  Loader2,
  PencilLine,
  ScaleIcon,
  SignalHigh,
  SignalLow,
  SignalMedium,
  XCircle,
} from 'lucide-react'

import type { DecisionAction, ImpactStatus, ImpactType, Severity, VbplStatus } from '@/api/types'
import { actionLabel, impactStatusLabel, impactTypeLabel, severityLabel, vbplStatusLabel } from '@/lib/labels'
import { cn } from '@/lib/utils'

// Status is always icon + text + color, never color alone.
const pill = 'inline-flex h-6 shrink-0 items-center gap-1 rounded-md px-2 text-xs font-medium whitespace-nowrap'

const impactStatusStyle: Record<ImpactStatus, { className: string; Icon: typeof Clock }> = {
  pending: { className: 'bg-status-pending/15 text-status-pending-fg', Icon: Clock },
  accepted: { className: 'bg-status-accepted/15 text-status-accepted-fg', Icon: CheckCircle2 },
  rejected: { className: 'bg-status-rejected/15 text-status-rejected-fg', Icon: XCircle },
}

export function ImpactStatusBadge({ status, className }: { status: ImpactStatus; className?: string }) {
  const { className: style, Icon } = impactStatusStyle[status]
  return (
    <span className={cn(pill, style, className)}>
      <Icon className="size-3.5" aria-hidden />
      {impactStatusLabel[status]}
    </span>
  )
}

const severityStyle: Record<Severity, { className: string; Icon: typeof SignalHigh }> = {
  high: { className: 'border-severity-high/40 text-severity-high', Icon: SignalHigh },
  medium: { className: 'border-severity-medium/40 text-severity-medium', Icon: SignalMedium },
  low: { className: 'border-severity-low/40 text-severity-low', Icon: SignalLow },
}

export function SeverityBadge({ severity, className }: { severity: Severity; className?: string }) {
  const { className: style, Icon } = severityStyle[severity]
  return (
    <span className={cn(pill, 'border', style, className)} title={`Mức độ: ${severityLabel[severity]}`}>
      <Icon className="size-3.5" aria-hidden />
      {severityLabel[severity]}
    </span>
  )
}

const typeIcon: Record<ImpactType, typeof ScaleIcon> = {
  conflict: AlertTriangle,
  outdated_reference: Link2Off,
  new_obligation: FileWarning,
}

export function ImpactTypeLabel({ type, className }: { type: ImpactType; className?: string }) {
  const Icon = typeIcon[type]
  return (
    <span className={cn('inline-flex items-center gap-1 text-xs whitespace-nowrap text-muted-foreground', className)}>
      <Icon className="size-3.5" aria-hidden />
      {impactTypeLabel[type]}
    </span>
  )
}

const vbplStatusStyle: Record<VbplStatus, { className: string; Icon: typeof Clock; spin?: boolean }> = {
  processing: { className: 'bg-secondary text-secondary-foreground', Icon: Loader2, spin: true },
  awaiting_review: { className: 'bg-status-pending/15 text-status-pending-fg', Icon: CircleDashed },
  done: { className: 'bg-status-accepted/15 text-status-accepted-fg', Icon: CheckCircle2 },
  not_found: { className: 'bg-status-accepted/15 text-status-accepted-fg', Icon: CheckCircle2 },
  failed: { className: 'bg-destructive/15 text-destructive', Icon: XCircle },
}

export function VbplStatusBadge({ status }: { status: VbplStatus }) {
  const { className, Icon, spin } = vbplStatusStyle[status]
  return (
    <span className={cn(pill, className)}>
      <Icon className={cn('size-3.5', spin && 'animate-spin motion-reduce:animate-none')} aria-hidden />
      {vbplStatusLabel[status]}
    </span>
  )
}

const actionStyle: Record<DecisionAction, { className: string; Icon: typeof Clock }> = {
  accept: { className: 'bg-status-accepted/15 text-status-accepted-fg', Icon: CheckCircle2 },
  edit: { className: 'bg-accent text-accent-foreground', Icon: PencilLine },
  reject: { className: 'bg-status-rejected/15 text-status-rejected-fg', Icon: XCircle },
}

export function ActionBadge({ action }: { action: DecisionAction }) {
  const { className, Icon } = actionStyle[action]
  return (
    <span className={cn(pill, className)}>
      <Icon className="size-3.5" aria-hidden />
      {actionLabel[action]}
    </span>
  )
}
