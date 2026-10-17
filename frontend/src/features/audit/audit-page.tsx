import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ExpandedState,
  type SortingState,
} from '@tanstack/react-table'
import { ArrowDownUp, ChevronRight, Download, History } from 'lucide-react'
import { Fragment, useMemo, useState } from 'react'

import type { AuditEntry, DecisionAction } from '@/api/types'
import { EmptyState, ErrorState } from '@/components/query-states'
import { ActionBadge } from '@/components/status-badges'
import { TextDiff } from '@/components/text-diff'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useAuditTrail } from '@/hooks/queries'
import { useCurrentUser } from '@/hooks/use-current-user'
import { formatDateTime } from '@/lib/format'
import { actionLabel } from '@/lib/labels'
import { cn } from '@/lib/utils'

const column = createColumnHelper<AuditEntry>()

const columns = [
  column.display({
    id: 'expand',
    header: () => <span className="sr-only">Mở chi tiết</span>,
    cell: ({ row }) => (
      <Button
        variant="ghost"
        size="icon-sm"
        onClick={row.getToggleExpandedHandler()}
        aria-expanded={row.getIsExpanded()}
        aria-label={row.getIsExpanded() ? 'Thu gọn' : 'Xem nội dung'}
      >
        <ChevronRight className={cn('transition-transform duration-200', row.getIsExpanded() && 'rotate-90')} aria-hidden />
      </Button>
    ),
  }),
  column.accessor('at', {
    header: 'Thời gian',
    cell: (info) => {
      const val = info.getValue()
      if (!val) return <span className="text-muted-foreground">-</span>
      try {
        return <span className="whitespace-nowrap">{formatDateTime(val)}</span>
      } catch {
        return <span className="whitespace-nowrap text-muted-foreground">{val}</span>
      }
    },
  }),
  column.accessor((entry) => entry.reviewer?.name ?? 'Chưa xác định', {
    id: 'reviewer',
    header: 'Người duyệt',
    cell: ({ row }) => (
      <div className="leading-tight">
        <p>{row.original.reviewer?.name ?? 'Chưa xác định'}</p>
        <p className="text-xs text-muted-foreground">{row.original.reviewer?.role ?? ''}</p>
      </div>
    ),
  }),
  column.accessor('vbplNumber', {
    header: 'VBPL',
    cell: (info) => info.getValue() || <span className="text-muted-foreground">-</span>,
  }),
  column.accessor('documentCode', {
    header: 'Văn bản nội bộ',
    cell: ({ row }) => (
      <div className="leading-tight">
        <p>{row.original.documentCode || '-'}</p>
        <p className="text-xs text-muted-foreground">{row.original.location || ''}</p>
      </div>
    ),
  }),
  column.accessor('action', {
    header: 'Hành động',
    cell: (info) => <ActionBadge action={info.getValue() || 'accept'} />,
  }),
  column.accessor((entry) => (Array.isArray(entry.reasonTags) ? entry.reasonTags.join(', ') : ''), {
    id: 'reasons',
    header: 'Lý do',
    enableSorting: false,
    cell: (info) => info.getValue() || <span className="text-muted-foreground">Không ghi</span>,
  }),
]

function toCsv(rows: AuditEntry[]): string {
  const header = ['Thời gian', 'Người duyệt', 'Vai trò', 'VBPL', 'Văn bản nội bộ', 'Vị trí', 'Hành động', 'Lý do', 'Nội dung gốc', 'Nội dung được duyệt']
  // A leading = + - @ makes Excel evaluate the cell as a formula; prefix with ' to keep it text.
  const escape = (value: unknown) => `"${(value ?? '').toString().replace(/^[=+\-@\t\r]/, "'$&").replaceAll('"', '""')}"`
  const lines = rows.map((r) => {
    let atStr = ''
    try {
      atStr = r.at ? formatDateTime(r.at) : ''
    } catch {
      atStr = r.at ?? ''
    }
    return [
      atStr,
      r.reviewer?.name ?? '',
      r.reviewer?.role ?? '',
      r.vbplNumber ?? '',
      r.documentCode ?? '',
      r.location ?? '',
      actionLabel[r.action] ?? r.action ?? '',
      Array.isArray(r.reasonTags) ? r.reasonTags.join('; ') : '',
      r.originalText ?? '',
      r.action === 'reject' ? '' : (r.editedText ?? r.suggestedText ?? ''),
    ]
      .map(escape)
      .join(',')
  })
  // BOM so Excel opens Vietnamese text as UTF-8.
  return '﻿' + [header.map(escape).join(','), ...lines].join('\r\n')
}

function downloadCsv(rows: AuditEntry[]) {
  const url = URL.createObjectURL(new Blob([toCsv(rows)], { type: 'text/csv;charset=utf-8' }))
  const link = Object.assign(document.createElement('a'), { href: url, download: `nhat-ky-kiem-toan-${new Date().toISOString().slice(0, 10)}.csv` })
  link.click()
  // Revoking synchronously can cancel the download in Safari.
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function AuditPage() {
  const { data, error, isPending, refetch } = useAuditTrail()
  const { reviewers } = useCurrentUser()
  const [action, setAction] = useState<'all' | DecisionAction>('all')
  const [reviewerId, setReviewerId] = useState('all')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [sorting, setSorting] = useState<SortingState>([{ id: 'at', desc: true }])
  const [expanded, setExpanded] = useState<ExpandedState>({})

  const rows = useMemo(() => {
    return (data ?? []).filter((entry) => {
      let day = ''
      try {
        if (entry.at) {
          const d = new Date(entry.at)
          if (!isNaN(d.getTime())) day = d.toLocaleDateString('sv-SE')
        }
      } catch {
        day = ''
      }
      const entryReviewerId = entry.reviewer?.id ?? ''
      return (
        (action === 'all' || entry.action === action) &&
        (reviewerId === 'all' || entryReviewerId === reviewerId) &&
        (!from || day >= from) &&
        (!to || day <= to)
      )
    })
  }, [data, action, reviewerId, from, to])

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting, expanded },
    onSortingChange: setSorting,
    onExpandedChange: setExpanded,
    getRowId: (row) => row.id,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div className="flex flex-wrap items-end gap-4">
        <div className="flex-1">
          <h1 className="text-xl font-semibold">Nhật ký kiểm toán</h1>
          <p className="mt-1 text-sm text-muted-foreground">Mọi quyết định duyệt của người dùng, dùng cho kiểm toán và học từ phản hồi.</p>
        </div>
        <Button variant="outline" onClick={() => downloadCsv(table.getSortedRowModel().rows.map((r) => r.original))} disabled={rows.length === 0}>
          <Download aria-hidden />
          Xuất CSV
        </Button>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <Filter label="Hành động" htmlFor="filter-action">
          <Select value={action} onValueChange={(value) => setAction(value as typeof action)}>
            <SelectTrigger id="filter-action" className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tất cả</SelectItem>
              {(Object.keys(actionLabel) as DecisionAction[]).map((key) => (
                <SelectItem key={key} value={key}>
                  {actionLabel[key]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Filter>
        <Filter label="Người duyệt" htmlFor="filter-reviewer">
          <Select value={reviewerId} onValueChange={setReviewerId}>
            <SelectTrigger id="filter-reviewer" className="w-52">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tất cả</SelectItem>
              {reviewers.map((r) => (
                <SelectItem key={r.id} value={r.id}>
                  {r.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Filter>
        <Filter label="Từ ngày" htmlFor="filter-from">
          <Input id="filter-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="h-8 w-40 text-base md:text-sm" />
        </Filter>
        <Filter label="Đến ngày" htmlFor="filter-to">
          <Input id="filter-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} className="h-8 w-40 text-base md:text-sm" />
        </Filter>
        <p className="ml-auto text-sm text-muted-foreground">{rows.length} bản ghi</p>
      </div>

      <div className="rounded-lg border bg-card">
        {error ? (
          <ErrorState error={error} onRetry={refetch} />
        ) : (
          <Table>
            <TableHeader>
              {table.getHeaderGroups().map((group) => (
                <TableRow key={group.id}>
                  {group.headers.map((header) => (
                    <TableHead key={header.id} className={header.id === 'expand' ? 'w-10' : undefined}>
                      {header.column.getCanSort() ? (
                        <button
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                          className="inline-flex items-center gap-1 rounded outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          <ArrowDownUp className="size-3.5 text-muted-foreground" aria-hidden />
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </TableHead>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {isPending &&
                Array.from({ length: 4 }, (_, i) => (
                  <TableRow key={i}>
                    <TableCell colSpan={columns.length}>
                      <Skeleton className="h-9" />
                    </TableCell>
                  </TableRow>
                ))}
              {table.getRowModel().rows.map((row) => (
                <Fragment key={row.id}>
                  <TableRow data-state={row.getIsExpanded() ? 'selected' : undefined}>
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                    ))}
                  </TableRow>
                  {row.getIsExpanded() && (
                    <TableRow className="hover:bg-transparent">
                      <TableCell colSpan={columns.length} className="bg-muted/40 p-4 whitespace-normal">
                        <ExpandedEntry entry={row.original} />
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        )}
        {!isPending && !error && rows.length === 0 && (
          <EmptyState icon={History} title="Chưa có bản ghi phù hợp" description="Quyết định trong Không gian duyệt sẽ xuất hiện ở đây." />
        )}
      </div>
    </div>
  )
}

function ExpandedEntry({ entry }: { entry: AuditEntry }) {
  if (entry.action === 'reject') {
    return (
      <div className="space-y-2">
        <p className="text-xs font-medium text-muted-foreground">Đề xuất đã bị từ chối</p>
        <TextDiff oldValue={entry.originalText || ''} newValue={entry.suggestedText || ''} className="bg-card" />
      </div>
    )
  }
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-muted-foreground">
        {entry.action === 'edit' ? 'Nội dung gốc → nội dung người duyệt đã sửa' : 'Nội dung gốc → đề xuất đã chấp nhận'}
      </p>
      <TextDiff oldValue={entry.originalText || ''} newValue={entry.editedText || entry.suggestedText || ''} className="bg-card" />
    </div>
  )
}

function Filter({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={htmlFor} className="text-xs font-medium text-muted-foreground">
        {label}
      </label>
      {children}
    </div>
  )
}
