import { useState, useRef, type ChangeEvent, type DragEvent } from 'react'
import { FileText, Loader2, Upload, X } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { useUploadVbpl } from '@/hooks/queries'

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function UploadVbplDialog() {
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [code, setCode] = useState('')
  const [title, setTitle] = useState('')
  const [isDragging, setIsDragging] = useState(false)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const uploadMutation = useUploadVbpl()

  const resetState = () => {
    setFile(null)
    setCode('')
    setTitle('')
    setIsDragging(false)
  }

  const handleOpenChange = (nextOpen: boolean) => {
    if (!uploadMutation.isPending) {
      setOpen(nextOpen)
      if (!nextOpen) resetState()
    }
  }

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0]
    if (selected) {
      if (!selected.name.toLowerCase().endsWith('.pdf') && selected.type !== 'application/pdf') {
        toast.error('Chỉ hỗ trợ file định dạng PDF')
        return
      }
      setFile(selected)
    }
  }

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = () => {
    setIsDragging(false)
  }

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(false)
    const dropped = e.dataTransfer.files?.[0]
    if (dropped) {
      if (!dropped.name.toLowerCase().endsWith('.pdf') && dropped.type !== 'application/pdf') {
        toast.error('Chỉ hỗ trợ file định dạng PDF')
        return
      }
      setFile(dropped)
    }
  }

  const handleSubmit = async () => {
    if (!file) return

    try {
      const result = await uploadMutation.mutateAsync({
        file,
        code: code.trim() || undefined,
        title: title.trim() || undefined,
      })

      toast.success('Tải lên và ingest thành công', {
        description: `Đã chunking ${result.chunk_count} đoạn quy phạm pháp luật và ingest vào Vector DB.`,
      })
      setOpen(false)
      resetState()
    } catch (error) {
      toast.error('Tải lên thất bại', {
        description: error instanceof Error ? error.message : 'Có lỗi xảy ra khi xử lý file',
      })
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button>
          <Upload aria-hidden />
          Tải lên VBPL
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Tải lên Văn bản Pháp luật (VBPL)</DialogTitle>
          <DialogDescription>
            Tải lên file PDF từ NHNN để hệ thống tự động bóc tách (PyMuPDF), chunking theo Điều/Khoản và ingest vào Vector DB.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* Dropzone */}
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 text-center transition-colors cursor-pointer ${
              isDragging
                ? 'border-primary bg-primary/5'
                : 'border-muted-foreground/25 hover:border-muted-foreground/50 hover:bg-muted/30'
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,application/pdf"
              onChange={handleFileChange}
              className="hidden"
            />
            {file ? (
              <div className="flex w-full items-center justify-between rounded-md bg-muted/60 p-3">
                <div className="flex items-center gap-3 overflow-hidden text-left">
                  <div className="flex size-9 shrink-0 items-center justify-center rounded bg-primary/10 text-primary">
                    <FileText className="size-5" />
                  </div>
                  <div className="truncate">
                    <p className="truncate text-sm font-medium">{file.name}</p>
                    <p className="text-xs text-muted-foreground">{formatFileSize(file.size)}</p>
                  </div>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  onClick={(e) => {
                    e.stopPropagation()
                    setFile(null)
                  }}
                  disabled={uploadMutation.isPending}
                >
                  <X className="size-4" />
                  <span className="sr-only">Xóa file</span>
                </Button>
              </div>
            ) : (
              <div className="space-y-2">
                <div className="mx-auto flex size-10 items-center justify-center rounded-full bg-muted">
                  <Upload className="size-5 text-muted-foreground" />
                </div>
                <div className="text-sm">
                  <span className="font-semibold text-primary">Bấm để chọn file PDF</span> hoặc kéo thả vào đây
                </div>
                <p className="text-xs text-muted-foreground">Hỗ trợ các văn bản Thông tư, Quyết định dạng PDF</p>
              </div>
            )}
          </div>

          {/* Optional metadata overrides */}
          <div className="space-y-3">
            <div>
              <label htmlFor="vbpl-code" className="text-xs font-medium text-muted-foreground">
                Số hiệu văn bản (tùy chọn, tự động nhận diện nếu để trống)
              </label>
              <Input
                id="vbpl-code"
                placeholder="Ví dụ: 31/2026/TT-NHNN"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                disabled={uploadMutation.isPending}
                className="mt-1"
              />
            </div>
            <div>
              <label htmlFor="vbpl-title" className="text-xs font-medium text-muted-foreground">
                Tiêu đề văn bản (tùy chọn)
              </label>
              <Input
                id="vbpl-title"
                placeholder="Ví dụ: Thông tư quy định về hoạt động cho vay..."
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                disabled={uploadMutation.isPending}
                className="mt-1"
              />
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => handleOpenChange(false)}
            disabled={uploadMutation.isPending}
          >
            Hủy
          </Button>
          <Button
            type="button"
            onClick={handleSubmit}
            disabled={!file || uploadMutation.isPending}
          >
            {uploadMutation.isPending ? (
              <>
                <Loader2 className="mr-2 size-4 animate-spin" />
                Đang xử lý & Ingest...
              </>
            ) : (
              'Tải lên & Xử lý'
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

