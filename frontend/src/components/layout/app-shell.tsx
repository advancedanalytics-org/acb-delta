import { Outlet } from 'react-router'

import { AppHeader } from './app-header'
import { SidebarNav } from './sidebar-nav'

export function AppShell() {
  return (
    <div className="flex h-dvh min-h-0 bg-background">
      <SidebarNav />
      <div className="flex min-w-0 flex-1 flex-col">
        <AppHeader />
        <main id="main" className="min-h-0 flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
