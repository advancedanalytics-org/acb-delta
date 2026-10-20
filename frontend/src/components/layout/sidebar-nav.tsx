import { Activity, BarChart3, FileText, History, Inbox, type LucideIcon } from 'lucide-react'
import { NavLink, useLocation } from 'react-router'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useVbpls } from '@/hooks/queries'
import { cn } from '@/lib/utils'

const items: { to: string; label: string; Icon: LucideIcon }[] = [
  { to: '/', label: 'Hộp thư VBPL', Icon: Inbox },
  { to: '/internal-documents', label: 'Văn bản nội bộ', Icon: FileText },
  { to: '/evaluation', label: 'Đánh giá', Icon: BarChart3 },
  { to: '/audit', label: 'Nhật ký kiểm toán', Icon: History },
  { to: '/system', label: 'Trạng thái hệ thống', Icon: Activity },
]

export function SidebarNav() {
  const { data: vbpls } = useVbpls()
  const pending = vbpls?.reduce((sum, vbpl) => sum + vbpl.pendingCount, 0) ?? 0
  // The review workspace needs the width for three panes, so the sidebar shrinks to icons there.
  const { pathname } = useLocation()
  const compact = pathname.startsWith('/review')

  return (
    <nav
      aria-label="Điều hướng chính"
      className={cn(
        'flex shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground',
        // Icons only on the review route and on small screens.
        compact ? 'w-16' : 'w-16 md:w-60',
      )}
    >
      <div className={cn('flex h-14 items-center gap-2 border-b border-sidebar-border', compact ? 'justify-center' : 'justify-center md:justify-start md:px-4')}>
        <span className="grid size-8 place-items-center rounded-md bg-primary text-sm font-semibold text-primary-foreground">
          Δ
        </span>
        <div className={cn('leading-tight max-md:sr-only', compact && 'sr-only')}>
          <p className="text-sm font-semibold">Delta</p>
          <p className="text-xs text-muted-foreground">Phân tích tác động pháp lý</p>
        </div>
      </div>
      <ul className={cn('flex flex-col gap-1', compact ? 'p-2' : 'p-2 md:p-3')}>
        {items.map(({ to, label, Icon }) => {
          // Active state computed here: the tooltip's Slot cannot merge NavLink's function className.
          const isActive = to === '/' ? pathname === '/' : pathname.startsWith(to)
          const link = (
            <NavLink
              to={to}
              aria-current={isActive ? 'page' : undefined}
              className={cn(
                'relative flex h-10 items-center gap-3 rounded-md px-3 text-sm transition-colors duration-150 outline-none focus-visible:ring-3 focus-visible:ring-ring/50',
                compact ? 'justify-center px-0' : 'max-md:justify-center max-md:px-0',
                isActive ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground' : 'hover:bg-sidebar-accent/60',
              )}
            >
              <Icon className="size-4 shrink-0" aria-hidden />
              <span className={cn('flex-1 max-md:sr-only', compact && 'sr-only')}>{label}</span>
              {to === '/' && pending > 0 && (
                <span
                  className={cn(
                    'rounded bg-status-pending/20 px-1.5 text-xs font-medium text-status-pending-fg',
                    compact ? 'absolute top-0 right-0 px-1 text-[10px]' : 'max-md:absolute max-md:top-0 max-md:right-0 max-md:px-1 max-md:text-[10px]',
                  )}
                >
                  {pending}
                  <span className="sr-only"> tác động chờ duyệt</span>
                </span>
              )}
            </NavLink>
          )
          return (
            <li key={to}>
              {compact ? (
                <Tooltip>
                  <TooltipTrigger asChild>{link}</TooltipTrigger>
                  <TooltipContent side="right">{label}</TooltipContent>
                </Tooltip>
              ) : (
                link
              )}
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
