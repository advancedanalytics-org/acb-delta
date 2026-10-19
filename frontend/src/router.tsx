import { lazy, Suspense, type ReactNode } from 'react'
import { createBrowserRouter } from 'react-router'

import { AppShell } from '@/components/layout/app-shell'
import { EmptyState } from '@/components/query-states'
import { Skeleton } from '@/components/ui/skeleton'
import { InboxPage } from '@/features/inbox/inbox-page'
import { ReviewIndexRedirect } from '@/features/review/review-index-redirect'

import { ReviewPage } from '@/features/review/review-page'

// Heavy screens (PDF viewer, charts, tables) load on demand to keep the first load small.
const EvaluationPage = lazy(() =>
  import('@/features/evaluation/evaluation-page').then((m) => ({ default: m.EvaluationPage })),
)
const AuditPage = lazy(() => import('@/features/audit/audit-page').then((m) => ({ default: m.AuditPage })))
const SystemPage = lazy(() => import('@/features/system/system-page').then((m) => ({ default: m.SystemPage })))

const page = (element: ReactNode) => <Suspense fallback={<Skeleton className="m-6 h-40" />}>{element}</Suspense>

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { index: true, element: <InboxPage /> },
      { path: 'review', element: <ReviewIndexRedirect /> },
      { path: 'review/:vbplId', element: <ReviewPage /> },
      { path: 'evaluation', element: page(<EvaluationPage />) },
      { path: 'audit', element: page(<AuditPage />) },
      { path: 'system', element: page(<SystemPage />) },
      {
        path: '*',
        element: <EmptyState title="Không tìm thấy trang" description="Đường dẫn không tồn tại." className="h-full justify-center" />,
      },
    ],
  },
])
