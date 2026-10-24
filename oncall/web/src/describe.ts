// Plain-language wording for what the agent did. Tool text follows TOOL_SPECS in oncall_agent/tools.py.
import type { DecisionRecord, IncidentDetail, Payload, TranscriptEvent } from './api'

type Args = Record<string, unknown>

const TOOLS: Record<string, (a: Args) => string> = {
  service_overview: (a) =>
    `Compared every service's requests/s, error rate and p95 latency over the last ${a.window ?? '2m'} with the healthy baseline, and checked for services that stopped reporting.`,
  service_detail: (a) =>
    `Broke ${a.service ?? 'one service'} down per operation to see which endpoint or RPC is failing.`,
  get_traces: (a) =>
    a.kind === 'slow'
      ? `Searched slow traces through ${a.service} to find the span that spends the most time itself.`
      : `Followed failing traces through ${a.service} down to the deepest failing span, where the errors start.`,
  search_logs: (a) =>
    a.service
      ? `Read recent ${a.level === 'any' ? '' : `${a.level ?? 'error'} `}logs from ${a.service}${a.pattern ? ` containing "${a.pattern}"` : ''}, grouped by message.`
      : 'Counted recent error logs per service to see who is complaining.',
  container_health: (a) =>
    `Checked Docker state for ${a.service || 'all services'}: running or exited, restarts, OOM kills, uptime, CPU and memory.`,
}

export const SOURCE_LABEL: Record<string, string> = {
  metrics: 'Metrics (Prometheus)',
  traces: 'Traces (Jaeger)',
  logs: 'Logs (OpenSearch)',
  containers: 'Containers (Docker)',
}

export function describeTool(e: TranscriptEvent): string {
  return e.description || TOOLS[e.name ?? '']?.(e.args ?? {}) || `Ran ${e.name}.`
}

const ACTIONS: Record<string, (t: string) => string> = {
  restart_service: (t) => `Restart the ${t} service`,
  toggle_feature_flag: (t) => `Toggle the ${t} feature flag`,
  throttle_load_generator: () => 'Throttle the load generator',
  scale_service: (t) => `Scale the ${t} service`,
}

export function describeAction(p: Payload): string {
  return ACTIONS[p.action]?.(p.target) ?? `${p.action} ${p.target}`
}

/** "11:02:10" → seconds since midnight, for durations within one run. */
const secs = (t?: string) => (t ? t.split(':').reduce((s, x) => s * 60 + Number(x), 0) : NaN)

export function runFacts(d: IncidentDetail) {
  const start = d.transcript[0]
  const end = d.transcript[d.transcript.length - 1]
  const took = secs(end?.t) - secs(start?.t)
  const cited = new Set(d.diagnosis.evidence.map((e) => e.evidence_id))
  return {
    model: d.transcript.find((e) => e.kind === 'alert')?.model,
    started: start?.t,
    took: Number.isFinite(took) && took >= 0 ? `${Math.floor(took / 60)}m ${took % 60}s` : undefined,
    checks: d.transcript.filter((e) => e.kind === 'tool').length,
    rejected: d.transcript.filter((e) => e.kind === 'rejected').length,
    sources: [...new Set(d.evidence.map((e) => e.source))],
    cited: d.evidence.filter((e) => cited.has(e.id)).length,
  }
}

/** One sentence on where this incident stands and what the human needs to do. */
export function statusLine(d: IncidentDetail, kill: boolean): { tone: 'wait' | 'ok' | 'warn' | 'stop'; text: string } {
  const p = d.payload
  const c: DecisionRecord | null = d.closed
  if (!p) {
    return {
      tone: 'warn',
      text: d.diagnosis.decision === 'escalate'
        ? 'The agent could not confirm a root cause with enough evidence, so it is handing this to you. Nothing will be changed automatically.'
        : 'The agent found a cause but has no safe action to propose. Nothing will be changed automatically.',
    }
  }
  const v = d.verification
  if (c?.event === 'approved' && v && v.event !== 'verifying') {
    return v.event === 'verified'
      ? { tone: 'ok', text: `${c.approver} approved "${describeAction(p)}". The Action API ran it and recovery is verified (${v.detail}).` }
      : { tone: 'warn', text: `${c.approver} approved "${describeAction(p)}" and it ran, but recovery is not confirmed (${v.detail}).` }
  }
  if (c?.event === 'approved') {
    return {
      tone: 'ok',
      text: `${c.approver} approved "${describeAction(p)}" at ${c.t.slice(11, 16)}. ` + (c.action_api?.status === 'not_connected'
        ? 'The approval is recorded; the action runs once the Action API is connected.'
        : `The Action API answered: ${c.action_api?.status ?? 'nothing'}${d.verification ? '; checking that the shop recovered' : ''}.`),
    }
  }
  if (c?.event === 'rejected') {
    return { tone: 'stop', text: `${c.approver} rejected the proposed action. No change will be made.` }
  }
  return {
    tone: kill ? 'stop' : 'wait',
    text: kill
      ? `Waiting on you to decide on "${describeAction(p)}", but the kill switch is on, so nothing can be approved.`
      : `The agent found the root cause and is waiting for you to approve: ${describeAction(p)}.`,
  }
}

export function confidenceExplained(dx: IncidentDetail['diagnosis']): string {
  const n = dx.evidence_sources?.length ?? 0
  if (dx.decision === 'escalate' && !dx.evidence.length) return 'No diagnosis passed the evidence check, so there is no confidence to report.'
  const model = dx.confidence_model != null ? `The model rated itself ${dx.confidence_model.toFixed(2)}. ` : ''
  const sources = dx.evidence_sources?.length ? ` It is backed by ${n} independent source(s): ${dx.evidence_sources.join(', ')}.` : ''
  // The capping rule below is oncall_agent's calibrate(); only claim it when that ran (it writes the note).
  if (!dx.calibration_note?.includes('capped')) return `${model}This is the confidence the agent reported.${sources}`
  return `${model}Confidence is capped by how many independent sources agree: none → 0.3, 1 source → 0.6, 2 → 0.8, 3 or more → 0.95. This diagnosis has ${n} (${dx.evidence_sources?.join(', ') || 'none'}), so it is ${dx.confidence.toFixed(2)}. Below 0.55 the agent escalates instead of proposing a fix.`
}
