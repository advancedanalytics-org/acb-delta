import { Check, PencilLine, X } from 'lucide-react'
import { useState, type KeyboardEvent } from 'react'

import type { DecisionAction, Impact, InternalDocument } from '@/api/types'
import { ImpactStatusBadge, ImpactTypeLabel, SeverityBadge } from '@/components/status-badges'
import { TextDiff } from '@/components/text-diff'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useImpactVbplClauses } from '@/hooks/queries'
import { formatDateTime } from '@/lib/format'
import { actionLabel, reasonTags } from '@/lib/labels'

import { Kbd } from './shortcut-help-dialog'
import { useReviewShortcuts } from './use-review-shortcuts'

export interface DecisionRequest {
  action: DecisionAction
  editedText?: string
  reasonTags: string[]
}

interface ImpactDetailProps {
  impact: Impact
  document: InternalDocument | undefined
  onDecide: (request: DecisionRequest) => void
  disabled?: boolean
}

/** Remounted per impact (key) so edit state and reason chips reset when the selection changes. */
export function ImpactDetail({ impact, document, onDecide, disabled }: ImpactDetailProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(impact.finalText || impact.suggestedText || impact.affectedText)
  // A failed or skipped draft has no AI text: the reviewer can edit or reject, not accept.
  const hasProposal = Boolean(impact.finalText ?? impact.suggestedText)
  const [tags, setTags] = useState<string[]>([])
  // The articles + clauses behind the citation, resolved from the real VBPL (empty while loading
  // or for impacts with no RIA findings).
  const { data: vbplClauses } = useImpactVbplClauses(impact.id)

  const decide = (action: DecisionAction) => {
    if (disabled) return
    if (action === 'accept' && !hasProposal) return
    if (action === 'edit') {
      setEditing(true)
      return
    }
    onDecide({ action, reasonTags: tags })
  }

  const saveEdit = () => {
    const text = draft.trim()
    if (!text || disabled) return
    onDecide({ action: 'edit', editedText: text, reasonTags: tags })
    setEditing(false)
  }

  const onEditorKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault()
      saveEdit()
    } else if (event.key === 'Escape') {
      event.preventDefault()
      setEditing(false)
    }
  }

  useReviewShortcuts({ a: () => decide('accept'), e: () => decide('edit'), r: () => decide('reject') }, !editing)

  const proposal = impact.finalText ?? impact.suggestedText

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 space-y-6 overflow-auto p-4">
        <header className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={impact.severity} />
            <ImpactStatusBadge status={impact.status} />
            <ImpactTypeLabel type={impact.type} className="ml-auto" />
          </div>
          <h2 className="text-base font-semibold">
            {document?.code} · {impact.location}
          </h2>
          {document && <p className="text-sm text-muted-foreground">{document.title}</p>}
        </header>

        <Section title="Điều khoản VBPL mới">
          <div className="rounded-md bg-accent px-3 py-2 text-sm text-accent-foreground">
            {vbplClauses && vbplClauses.length > 0 && (
              <div className="mb-1.5 space-y-0.5 border-b border-accent-foreground/15 pb-1.5">
                {vbplClauses.map((group) => {
                  const subClauses = group.clauses.filter((c) => c !== group.articleNumbering)
                  return (
                    <p key={group.articleNumbering} className="font-semibold">
                      Điều {group.articleNumbering}
                      {group.articleTitle ? ` — ${group.articleTitle}` : ''}
                      {subClauses.length > 0 && (
                        <span className="font-normal text-accent-foreground/70"> (khoản {subClauses.join(', ')})</span>
                      )}
                    </p>
                  )
                })}
              </div>
            )}
            <p className="whitespace-pre-line">{impact.changeClause}</p>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">Trích dẫn: {impact.citation}</p>
        </Section>

        <Section title="Đoạn hiện hành bị ảnh hưởng">
          <p className="rounded-md border px-3 py-2 text-sm">{impact.affectedText}</p>
        </Section>

        <Section title="Lý do">
          <p className="text-sm leading-relaxed whitespace-pre-line">{impact.reasoning}</p>
        </Section>

        <Section title={impact.decision?.action === 'edit' ? 'Nội dung đã sửa' : 'Đề xuất chỉnh sửa'}>
          {impact.location && <p className="text-sm font-semibold text-foreground">{impact.location}</p>}
          {editing ? (
            <div className="space-y-2">
              <Textarea
                autoFocus
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={onEditorKeyDown}
                rows={6}
                aria-label="Nội dung chỉnh sửa"
                className="text-base md:text-sm"
              />
              <div className="flex items-center gap-2">
                <Button size="sm" onClick={saveEdit} disabled={!draft.trim() || disabled}>
                  <Check aria-hidden />
                  Lưu bản sửa
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                  Hủy
                </Button>
                <span className="ml-auto text-xs text-muted-foreground">
                  <Kbd>Ctrl + Enter</Kbd> lưu · <Kbd>Esc</Kbd> hủy
                </span>
              </div>
            </div>
          ) : hasProposal ? (
            <TextDiff oldValue={impact.affectedText} newValue={proposal} />
          ) : (
            <p className="rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground">
              AI chưa soạn được đề xuất{impact.draftError ? ` (${impact.draftError})` : ''}. Hãy sửa
              trực tiếp hoặc từ chối.
            </p>
          )}
        </Section>

        {impact.decision && (
          <p className="text-xs text-muted-foreground">
            Quyết định gần nhất: {actionLabel[impact.decision.action]} bởi {impact.decision.reviewer.name} lúc{' '}
            {formatDateTime(impact.decision.at)}
            {impact.decision.reasonTags.length > 0 && ` · ${impact.decision.reasonTags.join(', ')}`}
          </p>
        )}
      </div>

      <footer className="space-y-3 border-t bg-card px-4 py-3">
        <div>
          <p id="reason-label" className="mb-2 text-xs font-medium text-muted-foreground">
            Lý do (tùy chọn, dùng cho học từ phản hồi)
          </p>
          <ToggleGroup
            type="multiple"
            value={tags}
            onValueChange={setTags}
            variant="outline"
            size="sm"
            spacing={1}
            aria-labelledby="reason-label"
            className="flex-wrap justify-start"
          >
            {reasonTags.map((tag) => (
              <ToggleGroupItem key={tag} value={tag} className="h-7 rounded-full px-2.5 text-xs data-[state=on]:border-primary/50 data-[state=on]:bg-accent data-[state=on]:text-accent-foreground">
                {tag}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <Button onClick={() => decide('accept')} disabled={disabled || !hasProposal} className="h-10">
            <Check aria-hidden />
            Chấp nhận
            <Kbd>A</Kbd>
          </Button>
          <Button variant="outline" onClick={() => decide('edit')} disabled={disabled || editing} className="h-10">
            <PencilLine aria-hidden />
            Sửa
            <Kbd>E</Kbd>
          </Button>
          <Button variant="destructive" onClick={() => decide('reject')} disabled={disabled} className="h-10">
            <X aria-hidden />
            Từ chối
            <Kbd>R</Kbd>
          </Button>
        </div>
      </footer>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-medium text-muted-foreground">{title}</h3>
      {children}
    </section>
  )
}
