// Types mirror src/oncall/ui/api.py and oncall_agent/schema.py.

export type Evidence = { evidence_id: string; quote: string; why: string; source?: string }

export type Diagnosis = {
  decision: 'diagnosed' | 'escalate'
  summary: string
  alert?: string
  root_cause?: { component: string; cause: string } | null
  confidence: number
  confidence_model?: number | null
  calibration_note?: string
  evidence_sources?: string[]
  evidence: Evidence[]
  alternatives_ruled_out?: string[]
  open_questions?: string[]
  proposed_action?: { action: string; target?: string; reason?: string; rollback?: string } | null
}

export type TranscriptEvent = {
  t: string
  kind: 'alert' | 'tool' | 'thought' | 'rejected' | 'diagnosis' | 'llm_error' | 'rate_limited'
  name?: string
  args?: Record<string, unknown>
  evidence_id?: string
  text?: string
  error?: string
  model?: string
  /** Agent-supplied plain-language description of the step, if any. */
  description?: string | null
}

export type EvidenceItem = {
  id: string
  tool: string
  source: string
  args: Record<string, unknown>
  time: string
  error: boolean
  preview: string
  description?: string | null
  /** Where to see this evidence in the demo's own tools (Jaeger, Grafana) or the agent's deep link. */
  link?: { label: string; url: string } | null
}

export type Payload = { incident: string; action: string; target: string; reason: string }

export type DecisionRecord = {
  t: string
  incident: string
  event: 'approved' | 'rejected' | 'dry_run'
  approver: string
  payload: Payload
  fingerprint: string
  note?: string
  action_api?: { status: string; detail: string }
}

/** Recovery check after an executed action, from fresh telemetry (incident_ui/approval.py verify). */
export type VerificationRecord = {
  t: string
  event: 'verifying' | 'verified' | 'recovery_unconfirmed'
  detail: string
  checks?: { check: string; ok: boolean; value: string }[]
}

export type IncidentDetail = {
  id: string
  /** The agent's own workflow state, e.g. AWAITING_APPROVAL, when it reports one. */
  state?: string | null
  diagnosis: Diagnosis
  transcript: TranscriptEvent[]
  evidence: EvidenceItem[]
  payload: Payload | null
  decisions: DecisionRecord[]
  closed: DecisionRecord | null
  verification: VerificationRecord | null
  report: string | null
}

export type IncidentSummary = {
  id: string
  alert: string
  decision: Diagnosis['decision']
  confidence: number
  state?: string | null
  closed: 'approved' | 'rejected' | null
}

export type StackService = { name: string; url: string; ok: boolean; detail: string }

async function call<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, body === undefined ? undefined : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }))
  if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`)
  return data as T
}

export const api = {
  state: () => call<{ incidents: IncidentSummary[]; kill: boolean; source: string; can_investigate: boolean }>('/api/state'),
  stack: () => call<{ services: StackService[] }>('/api/stack'),
  incident: (id: string) => call<IncidentDetail>(`/api/incident?id=${encodeURIComponent(id)}`),
  decide: (id: string, decision: DecisionRecord['event'], approver: string, note = '') =>
    call<DecisionRecord>('/api/decide', { id, decision, approver, note }),
  kill: (on: boolean) => call<{ kill: boolean }>('/api/kill', { on }),
  investigate: (alert: string) => call<{ id: string }>('/api/investigate', { alert }),
}
