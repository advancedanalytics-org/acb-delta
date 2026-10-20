import { Check, FlaskConical, LogOut, Moon, RotateCcw, Search, Sun } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { apiMode } from '@/api/client'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useResetDemo } from '@/hooks/queries'
import { useAuth } from '@/hooks/use-auth'
import { useCurrentUser } from '@/hooks/use-current-user'
import { useTheme } from '@/hooks/use-theme'
import { initials } from '@/lib/format'

export function AppHeader() {
  const { theme, toggle } = useTheme()
  const { reviewer, reviewers, setReviewerId } = useCurrentUser()
  const { logout } = useAuth()
  const resetDemo = useResetDemo()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [query, setQuery] = useState(params.get('q') ?? '')

  const onSearch = (event: FormEvent) => {
    event.preventDefault()
    const q = query.trim()
    navigate(q ? `/?q=${encodeURIComponent(q)}` : '/')
  }

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-card px-4">
      <form role="search" onSubmit={onSearch} className="relative w-full max-w-sm">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <Input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Tìm VBPL theo số hiệu, tiêu đề"
          aria-label="Tìm văn bản pháp luật"
          className="h-9 pl-8 text-base md:text-sm"
        />
      </form>

      <div className="ml-auto flex items-center gap-2">
        {apiMode === 'mock' && (
          <Tooltip>
            <TooltipTrigger asChild>
              <span
                tabIndex={0}
                className="inline-flex h-7 items-center gap-1.5 rounded-md bg-status-pending/15 px-2 text-xs font-medium text-status-pending-fg outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                <FlaskConical className="size-3.5" aria-hidden />
                Dữ liệu demo
              </span>
            </TooltipTrigger>
            <TooltipContent>Dữ liệu giả lập để minh họa giao diện, không phải kết quả thật.</TooltipContent>
          </Tooltip>
        )}

        <Button
          variant="ghost"
          size="icon"
          onClick={toggle}
          aria-label={theme === 'dark' ? 'Chuyển sang giao diện sáng' : 'Chuyển sang giao diện tối'}
        >
          {theme === 'dark' ? <Sun aria-hidden /> : <Moon aria-hidden />}
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="h-9 gap-2 px-2" aria-label="Đổi người duyệt">
              <Avatar className="size-7">
                <AvatarFallback className="bg-accent text-xs text-accent-foreground">
                  {reviewer ? initials(reviewer.name) : '?'}
                </AvatarFallback>
              </Avatar>
              <span className="hidden text-left leading-tight lg:block">
                <span className="block text-sm font-medium">{reviewer?.name ?? 'Chưa chọn'}</span>
                <span className="block text-xs text-muted-foreground">{reviewer?.role}</span>
              </span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-64">
            <DropdownMenuLabel>Người duyệt (demo)</DropdownMenuLabel>
            {reviewers.map((r) => (
              <DropdownMenuItem key={r.id} onSelect={() => setReviewerId(r.id)}>
                <div className="flex-1 leading-tight">
                  <p className="text-sm">{r.name}</p>
                  <p className="text-xs text-muted-foreground">{r.role}</p>
                </div>
                {r.id === reviewer?.id && <Check aria-label="Đang chọn" />}
              </DropdownMenuItem>
            ))}
            {apiMode === 'mock' && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onSelect={() =>
                    resetDemo.mutate(undefined, { onSuccess: () => toast.success('Đã khôi phục dữ liệu demo ban đầu') })
                  }
                >
                  <RotateCcw aria-hidden />
                  Đặt lại dữ liệu demo
                </DropdownMenuItem>
              </>
            )}
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={logout}>
              <LogOut aria-hidden />
              Đăng xuất
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  )
}
