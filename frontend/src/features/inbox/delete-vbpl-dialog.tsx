import { useState } from 'react'
import { Loader2, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import type { Vbpl } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { useDeleteVbpl } from '@/hooks/queries'
import { useCurrentUser } from '@/hooks/use-current-user'

/**
 * Trash button + confirmation for a VBPL that is not processing (failed or reviewable).
 * Shown only to a department head (`canDelete`); specialists cannot delete.
 */
export function DeleteVbplDialog({ vbpl }: { vbpl: Vbpl }) {
  const [open, setOpen] = useState(false)
  const { reviewer } = useCurrentUser()
  const failed = vbpl.status === 'failed'
  const decidedCount = vbpl.impactCount - vbpl.pendingCount
  // The API refuses to delete a VBPL with reviewer decisions: they are the audit trail.
  const hasDecisions = !failed && decidedCount > 0
  const deleteMutation = useDeleteVbpl()

  if (!reviewer?.canDelete) return null

  const handleDelete = () => {
    deleteMutation.mutate({ vbpl, reviewerId: reviewer.id }, {
      onSuccess: () => {
        toast.success(`Đã xóa ${vbpl.number}. Có thể tải lại văn bản này.`)
        setOpen(false)
      },
      onError: (error) => toast.error(error.message),
    })
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !deleteMutation.isPending && setOpen(next)}>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon-xs"
          onClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
          aria-label={`Xóa ${vbpl.number}`}
          title={failed ? 'Xóa văn bản bị lỗi' : 'Xóa văn bản'}
          className="text-muted-foreground hover:text-destructive"
        >
          <Trash2 />
        </Button>
      </DialogTrigger>
      {/* The dialog renders in a portal, but React still bubbles its events to the table row,
          whose click / Enter opens the review page. */}
      <DialogContent onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
        <DialogHeader>
          <DialogTitle>{failed ? 'Xóa văn bản bị lỗi?' : 'Xóa văn bản?'}</DialogTitle>
          <DialogDescription>
            <span className="font-medium text-foreground">{vbpl.number}</span> — {vbpl.title}
            <br />
            File gốc, toàn bộ kết quả phân tích và các đề xuất chỉnh sửa của văn bản này sẽ bị xóa vĩnh viễn. Sau
            đó có thể tải lại đúng file này.
          </DialogDescription>
        </DialogHeader>
        {vbpl.error && <p className="text-sm text-destructive">Lỗi: {vbpl.error}</p>}
        {hasDecisions && (
          <p className="text-sm text-destructive">
            {decidedCount}/{vbpl.impactCount} tác động đã được duyệt. Không thể xóa vì các quyết định duyệt là
            nhật ký kiểm toán.
          </p>
        )}
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" disabled={deleteMutation.isPending}>
              Hủy
            </Button>
          </DialogClose>
          <Button variant="destructive" onClick={handleDelete} disabled={deleteMutation.isPending || hasDecisions}>
            {deleteMutation.isPending ? <Loader2 className="animate-spin" /> : <Trash2 />}
            Xóa văn bản
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
