import { Navigate } from 'react-router'

import { EmptyState, ErrorState } from '@/components/query-states'
import { Skeleton } from '@/components/ui/skeleton'
import { useVbpls } from '@/hooks/queries'

/** /review opens the oldest VBPL that still has impacts waiting for review. */
export function ReviewIndexRedirect() {
  const { data, error, isPending, refetch } = useVbpls()
  if (error) return <ErrorState error={error} onRetry={refetch} />
  if (isPending) return <Skeleton className="m-6 h-40" />
  const waiting = data
    .filter((vbpl) => vbpl.status === 'awaiting_review')
    .sort((a, b) => a.receivedAt.localeCompare(b.receivedAt))
  const target = waiting[0] ?? data.find((vbpl) => vbpl.impactCount > 0)
  if (!target) return <EmptyState title="Chưa có VBPL nào cần duyệt" className="h-full justify-center" />
  return <Navigate to={`/review/${target.id}`} replace />
}
