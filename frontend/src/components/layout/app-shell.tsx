import { Outlet, useLocation } from 'react-router'

import { ErrorBoundary } from '@/components/error-boundary'
import { AppHeader } from './app-header'
import { SidebarNav } from './sidebar-nav'

export function AppShell() {
  const { pathname } = useLocation()

  return (
    <div className="flex h-dvh min-h-0 bg-background">
      <SidebarNav />
      <div className="flex min-w-0 flex-1 flex-col">
        <AppHeader />
        <main id="main" className="min-h-0 flex-1 overflow-auto">
          <ErrorBoundary key={pathname}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </div>
  )
}
