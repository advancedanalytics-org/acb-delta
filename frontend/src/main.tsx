import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router'
import { Toaster } from 'sonner'

import { TooltipProvider } from '@/components/ui/tooltip'
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

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <CurrentUserProvider>
          <TooltipProvider delayDuration={300}>
            <RouterProvider router={router} />
            <ThemedToaster />
          </TooltipProvider>
        </CurrentUserProvider>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
