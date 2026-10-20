import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router'
import { Toaster } from 'sonner'

import { TooltipProvider } from '@/components/ui/tooltip'
import { LoginPage } from '@/features/auth/login-page'
import { AuthProvider, useAuth } from '@/hooks/use-auth'
import { CurrentUserProvider } from '@/hooks/use-current-user'
import { ThemeProvider, useTheme } from '@/hooks/use-theme'
import { router } from '@/router'

import './index.css'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false } },
})

function ThemedToaster() {
  const { theme } = useTheme()
  return <Toaster theme={theme} position="bottom-center" closeButton richColors={false} />
}

/** Demo login gate: show the login screen until authenticated, then mount the app. */
function AuthGate({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth()
  return isAuthenticated ? <>{children}</> : <LoginPage />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <AuthProvider>
        <QueryClientProvider client={queryClient}>
          <TooltipProvider delayDuration={300}>
            <AuthGate>
              <CurrentUserProvider>
                <RouterProvider router={router} />
              </CurrentUserProvider>
            </AuthGate>
            <ThemedToaster />
          </TooltipProvider>
        </QueryClientProvider>
      </AuthProvider>
    </ThemeProvider>
  </StrictMode>,
)
