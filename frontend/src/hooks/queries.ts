import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'

import { api } from '@/api/client'
import type {
  AuditEntry,
  Decision,
  DecisionInput,
  Impact,
  ImpactStatus,
  InternalDocument,
  Reviewer,
  UploadVbplInput,
  Vbpl,
} from '@/api/types'

export const queryKeys = {
  vbpls: ['vbpls'] as const,
  impacts: (vbplId: string) => ['impacts', vbplId] as const,
  documents: ['documents'] as const,
  auditTrail: ['audit-trail'] as const,
  reviewers: ['reviewers'] as const,
  evalRuns: ['eval-runs'] as const,
  health: ['health'] as const,
}

export const useVbpls = () =>
  useQuery({
    queryKey: queryKeys.vbpls,
    queryFn: api.listVbpls,
    refetchInterval: (query) => {
      const hasProcessing = query.state.data?.some((v) => v.status === 'processing')
      return hasProcessing ? 1500 : false
    },
  })

export const useImpacts = (vbplId: string | undefined) => {
  const { data: vbpls } = useVbpls()
  const vbpl = vbpls?.find((v) => v.id === vbplId)
  return useQuery({
    queryKey: queryKeys.impacts(vbplId ?? ''),
    queryFn: () => api.listImpacts(vbplId!),
    enabled: Boolean(vbplId),
    // Impacts arrive one by one while the agent drafts the review package. Keep polling until the
    // list has as many impacts as the inbox counts: covers a package started by opening this page
    // and drafts that land after the inbox already left 'processing'.
    refetchInterval: (query) =>
      vbpl?.status === 'processing' || (query.state.data?.length ?? 0) < (vbpl?.impactCount ?? 0)
        ? 2000
        : false,
  })
}

export const useDocuments = () =>
  useQuery({ queryKey: queryKeys.documents, queryFn: api.listDocuments, staleTime: 30_000 })

export const useAuditTrail = () => useQuery({ queryKey: queryKeys.auditTrail, queryFn: api.listAuditTrail })

export const useReviewers = () =>
  useQuery({ queryKey: queryKeys.reviewers, queryFn: api.listReviewers, staleTime: Infinity })

export const useEvalRuns = () => useQuery({ queryKey: queryKeys.evalRuns, queryFn: api.listEvalRuns })

export const useHealth = () =>
  useQuery({ queryKey: queryKeys.health, queryFn: api.getHealth, refetchInterval: 10_000, retry: false })

const STATUS_BY_ACTION: Record<Decision['action'], ImpactStatus> = {
  accept: 'accepted',
  edit: 'accepted',
  reject: 'rejected',
}

interface Snapshot {
  impacts?: Impact[]
  vbpls?: Vbpl[]
  auditTrail?: AuditEntry[]
}

async function snapshot(qc: QueryClient, vbplId: string): Promise<Snapshot> {
  await Promise.all([
    qc.cancelQueries({ queryKey: queryKeys.impacts(vbplId) }),
    qc.cancelQueries({ queryKey: queryKeys.vbpls }),
    qc.cancelQueries({ queryKey: queryKeys.auditTrail }),
  ])
  return {
    impacts: qc.getQueryData(queryKeys.impacts(vbplId)),
    vbpls: qc.getQueryData(queryKeys.vbpls),
    auditTrail: qc.getQueryData(queryKeys.auditTrail),
  }
}

function restore(qc: QueryClient, vbplId: string, snap: Snapshot | undefined) {
  if (!snap) return
  qc.setQueryData(queryKeys.impacts(vbplId), snap.impacts)
  qc.setQueryData(queryKeys.vbpls, snap.vbpls)
  qc.setQueryData(queryKeys.auditTrail, snap.auditTrail)
}

function invalidate(qc: QueryClient, vbplId: string) {
  qc.invalidateQueries({ queryKey: queryKeys.impacts(vbplId) })
  qc.invalidateQueries({ queryKey: queryKeys.vbpls })
  qc.invalidateQueries({ queryKey: queryKeys.auditTrail })
}

/** Replace one impact in the cache and keep the VBPL's pending count in step. */
function writeImpact(qc: QueryClient, next: Impact) {
  let previousStatus: ImpactStatus | undefined
  qc.setQueryData<Impact[]>(queryKeys.impacts(next.vbplId), (list) =>
    list?.map((impact) => {
      if (impact.id !== next.id) return impact
      previousStatus = impact.status
      return next
    }),
  )
  if (!previousStatus) return
  const delta = (next.status === 'pending' ? 1 : 0) - (previousStatus === 'pending' ? 1 : 0)
  qc.setQueryData<Vbpl[]>(queryKeys.vbpls, (list) =>
    list?.map((vbpl) => {
      const pendingCount = vbpl.pendingCount + delta
      return {
        ...vbpl,
        pendingCount,
        status: vbpl.impactCount === 0 ? 'not_found' : pendingCount > 0 ? 'awaiting_review' : 'done',
      }
    }),
  )
}

interface DecideVariables {
  input: DecisionInput
  impact: Impact
  reviewer: Reviewer
}

export function useDecide() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ input }: DecideVariables) => api.decide(input),
    onMutate: async ({ input, impact, reviewer }) => {
      const snap = await snapshot(qc, impact.vbplId)
      const optimistic: Decision = {
        id: `pending-${input.impactId}`,
        impactId: impact.id,
        vbplId: impact.vbplId,
        documentId: impact.documentId,
        action: input.action,
        editedText: input.editedText,
        reasonTags: input.reasonTags,
        reviewer,
        at: new Date().toISOString(),
      }
      writeImpact(qc, {
        ...impact,
        status: STATUS_BY_ACTION[input.action],
        finalText:
          input.action === 'edit'
            ? input.editedText
            : input.action === 'accept'
              ? (input.editedText ?? impact.finalText ?? impact.suggestedText)
              : undefined,
        decision: optimistic,
      })
      const entry: AuditEntry = {
        ...optimistic,
        vbplNumber: qc.getQueryData<Vbpl[]>(queryKeys.vbpls)?.find((v) => v.id === impact.vbplId)?.number ?? '',
        documentCode:
          qc.getQueryData<InternalDocument[]>(queryKeys.documents)?.find((d) => d.id === impact.documentId)?.code ?? '',
        location: impact.location,
        originalText: impact.affectedText,
        suggestedText: impact.suggestedText,
      }
      qc.setQueryData<AuditEntry[]>(queryKeys.auditTrail, (list) => list && [entry, ...list])
      return snap
    },
    onError: (_error, { impact }, snap) => restore(qc, impact.vbplId, snap),
    onSettled: (_data, _error, { impact }) => invalidate(qc, impact.vbplId),
  })
}

interface UndoVariables {
  decision: Decision
  /** The impact as it was before the decision being undone. */
  previous: Impact
}

export function useUndoDecision() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ decision }: UndoVariables) => api.undoDecision(decision.id),
    onMutate: async ({ decision, previous }) => {
      const snap = await snapshot(qc, previous.vbplId)
      writeImpact(qc, previous)
      qc.setQueryData<AuditEntry[]>(queryKeys.auditTrail, (list) => list?.filter((d) => d.id !== decision.id))
      return snap
    },
    onError: (_error, { previous }, snap) => restore(qc, previous.vbplId, snap),
    onSettled: (_data, _error, { previous }) => invalidate(qc, previous.vbplId),
  })
}

export function useResetDemo() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: api.resetDemo, onSuccess: () => qc.invalidateQueries() })
}

export function useDeleteVbpl() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (vbpl: Vbpl) => api.deleteVbpl(vbpl),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.vbpls })
    },
  })
}

export function useUploadVbpl() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: UploadVbplInput) => api.uploadVbpl(input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.vbpls })
    },
  })
}

