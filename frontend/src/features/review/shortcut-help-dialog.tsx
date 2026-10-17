import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'

const shortcuts: [string, string][] = [
  ['A', 'Chấp nhận đề xuất'],
  ['E', 'Sửa đề xuất'],
  ['R', 'Từ chối'],
  ['J', 'Tác động tiếp theo'],
  ['K', 'Tác động trước'],
  ['Ctrl + Enter', 'Lưu khi đang sửa'],
  ['Esc', 'Hủy sửa'],
  ['?', 'Mở bảng phím tắt'],
]

export function Kbd({ children }: { children: string }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border bg-muted px-1 font-sans text-[11px] font-medium text-muted-foreground">
      {children}
    </kbd>
  )
}

export function ShortcutHelpDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Phím tắt</DialogTitle>
          <DialogDescription>Dùng trong Không gian duyệt khi không gõ vào ô nhập liệu.</DialogDescription>
        </DialogHeader>
        <dl className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2 text-sm">
          {shortcuts.map(([key, label]) => (
            <div key={key} className="contents">
              <dt>
                <Kbd>{key}</Kbd>
              </dt>
              <dd>{label}</dd>
            </div>
          ))}
        </dl>
      </DialogContent>
    </Dialog>
  )
}
