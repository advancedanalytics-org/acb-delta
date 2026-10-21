import { Eye, EyeOff, Lock, LogIn, Moon, ShieldCheck, Sun, User } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/hooks/use-auth'
import { useTheme } from '@/hooks/use-theme'
import { cn } from '@/lib/utils'

/** ACB brand blue, taken from the logo, for the hero banner only. */
const ACB_HERO = {
  background:
    'radial-gradient(1100px 520px at 12% -8%, #2f6ad0 0%, transparent 52%), radial-gradient(900px 600px at 90% 110%, #17a2e0 0%, transparent 45%), linear-gradient(150deg, #1b3f9c 0%, #163377 52%, #0f2452 100%)',
} as const

const features = [
  'Tự động rà soát tác động của VBPL tới văn bản nội bộ',
  'Gợi ý chỉnh sửa và luồng duyệt có chuyên viên (HITL)',
  'Đánh giá chất lượng và học từ phản hồi theo thời gian',
]

/** The ACB wordmark PNG (transparent). On a dark surface, pass `white` to invert it. */
function AcbWordmark({ className, white = false }: { className?: string; white?: boolean }) {
  return (
    <img
      src="/brand/acb-wordmark.png"
      alt="ACB"
      className={cn('w-auto select-none', className)}
      style={white ? { filter: 'brightness(0) invert(1)' } : undefined}
      draggable={false}
    />
  )
}

export function LoginPage() {
  const { login } = useAuth()
  const { theme, toggle } = useTheme()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState(false)

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    const ok = login(username, password)
    // On success the app gate re-renders to the dashboard; on failure show one inline message.
    if (!ok) setError(true)
  }

  return (
    <div className="grid min-h-dvh lg:grid-cols-[1.05fr_1fr]">
      {/* Hero banner — ACB branding. Hidden on small screens to keep the form front and centre. */}
      <aside className="relative hidden flex-col justify-between overflow-hidden p-10 text-white lg:flex" style={ACB_HERO}>
        {/* dotted texture + soft glows for depth */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-20"
          style={{ backgroundImage: 'radial-gradient(rgba(255,255,255,0.5) 1px, transparent 1px)', backgroundSize: '24px 24px' }}
        />
        <div aria-hidden className="pointer-events-none absolute -top-28 -left-24 size-96 rounded-full bg-sky-300/20 blur-3xl" />
        <img
          src="/brand/acb-symbol.png"
          alt=""
          aria-hidden
          className="pointer-events-none absolute -right-20 -bottom-24 w-[480px] opacity-[0.12]"
          style={{ filter: 'brightness(0) invert(1)' }}
          draggable={false}
        />

        <div className="relative flex items-center gap-3">
          <span className="inline-flex items-center rounded-xl bg-white px-4 py-2.5 shadow-lg shadow-black/10">
            <AcbWordmark className="h-8" />
          </span>
        </div>

        <div className="relative max-w-md">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-white/90 ring-1 ring-white/20 backdrop-blur-sm">
            <ShieldCheck className="size-3.5 text-sky-300" aria-hidden />
            Hệ thống nội bộ
          </span>
          <h1 className="mt-4 text-[2rem] leading-tight font-semibold tracking-tight">
            Regulatory Impact Analysis bằng AI
          </h1>
          <p className="mt-4 text-sm leading-relaxed text-white/80">
            Khi có văn bản pháp luật mới, RIA tìm ngay những văn bản nội bộ bị ảnh hưởng, đề xuất
            chỉnh sửa và để chuyên viên duyệt — nhanh, có kiểm soát.
          </p>
          <ul className="mt-7 space-y-3.5">
            {features.map((f) => (
              <li key={f} className="flex items-start gap-2.5 text-sm text-white/90">
                <ShieldCheck className="mt-0.5 size-4 shrink-0 text-sky-300" aria-hidden />
                <span>{f}</span>
              </li>
            ))}
          </ul>
        </div>

        <p className="relative text-xs text-white/55">© 2026 Ngân hàng Á Châu (ACB) · Bản demo nội bộ</p>
      </aside>

      {/* Form side */}
      <main className="relative flex items-center justify-center overflow-hidden bg-background px-6 py-10">
        <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-48 bg-gradient-to-b from-primary/[0.06] to-transparent" />

        <Button
          variant="ghost"
          size="icon"
          onClick={toggle}
          className="absolute top-4 right-4"
          aria-label={theme === 'dark' ? 'Chuyển sang giao diện sáng' : 'Chuyển sang giao diện tối'}
        >
          {theme === 'dark' ? <Sun aria-hidden /> : <Moon aria-hidden />}
        </Button>

        <div className="relative w-full max-w-sm">
          <div className="rounded-2xl border bg-card p-7 shadow-xl shadow-black/5 duration-500 animate-in fade-in slide-in-from-bottom-2">
            {/* ACB mark (also visible on mobile where the banner is hidden) */}
            <div className="flex items-center gap-3">
              <span className="inline-flex items-center rounded-lg border bg-background px-2.5 py-1.5">
                <AcbWordmark className="h-6" />
              </span>
              <div className="h-6 w-px bg-border" aria-hidden />
              <div className="leading-tight">
                <p className="text-sm font-semibold">RIA</p>
                <p className="text-xs text-muted-foreground">Regulatory Impact Analysis</p>
              </div>
            </div>

            <h2 className="mt-7 text-2xl font-semibold tracking-tight">Đăng nhập</h2>
            <p className="mt-1 text-sm text-muted-foreground">Hệ thống Regulatory Impact Analysis nội bộ.</p>

            <form onSubmit={onSubmit} className="mt-6 space-y-4" noValidate>
              <div className="space-y-1.5">
                <label htmlFor="username" className="text-sm font-medium">
                  Tên đăng nhập
                </label>
                <div className="relative">
                  <User className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
                  <Input
                    id="username"
                    value={username}
                    onChange={(e) => {
                      setUsername(e.target.value)
                      setError(false)
                    }}
                    placeholder="Nhập tên đăng nhập"
                    autoComplete="username"
                    autoFocus
                    className="h-11 pl-8"
                    aria-invalid={error}
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <label htmlFor="password" className="text-sm font-medium">
                  Mật khẩu
                </label>
                <div className="relative">
                  <Lock className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
                  <Input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => {
                      setPassword(e.target.value)
                      setError(false)
                    }}
                    placeholder="Nhập mật khẩu"
                    autoComplete="current-password"
                    className="h-11 px-8"
                    aria-invalid={error}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((s) => !s)}
                    className="absolute top-1/2 right-2 grid size-7 -translate-y-1/2 place-items-center rounded-md text-muted-foreground hover:text-foreground focus-visible:outline-1 focus-visible:outline-ring"
                    aria-label={showPassword ? 'Ẩn mật khẩu' : 'Hiện mật khẩu'}
                  >
                    {showPassword ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
                  </button>
                </div>
              </div>

              {error && (
                <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  Tên đăng nhập hoặc mật khẩu không đúng.
                </p>
              )}

              <Button
                type="submit"
                className="h-11 w-full gap-2 shadow-sm transition hover:brightness-110"
                style={{ background: 'linear-gradient(90deg, #1b3f9c 0%, #2a63c8 100%)', color: '#fff' }}
              >
                <LogIn className="size-4" aria-hidden />
                Đăng nhập
              </Button>
            </form>
          </div>

          <p className="mt-5 text-center text-xs text-muted-foreground">Bản demo nội bộ · Dữ liệu minh họa</p>
        </div>
      </main>
    </div>
  )
}
