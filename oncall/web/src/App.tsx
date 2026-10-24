import AgentAvatar from '@/components/smoothui/agent-avatar'
import AIConversation from '@/components/smoothui/ai-conversation'
import AILoader from '@/components/smoothui/ai-loader'
import AIPromptInput from '@/components/smoothui/ai-prompt-input'
import AISuggestions from '@/components/smoothui/ai-suggestions'
import AITaskList, { type AITask } from '@/components/smoothui/ai-task-list'
import { cn } from '@/lib/utils'
import { Power } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { api, type DecisionRecord, type IncidentDetail, type IncidentSummary, type StackService } from './api'
import { describeAction, runFacts, SOURCE_LABEL, statusLine } from './describe'
import Thread from './Thread'

const TONE = {
  wait: 'border-primary/30 bg-primary/10',
  ok: 'border-primary/30 bg-primary/10',
  warn: 'border-amber-500/40 bg-amber-500/10',
  stop: 'border-destructive/30 bg-destructive/10',
}

function StatusBanner({ d, kill }: { d: IncidentDetail; kill: boolean }) {
  const s = statusLine(d, kill)
  return (
    <p className={cn('mb-6 rounded-xl border px-4 py-3 text-base', TONE[s.tone])} role="status">
      {d.state && <span className="mr-2 rounded-md bg-background/60 px-1.5 py-0.5 font-mono text-xs">{d.state}</span>}
      {s.text}
    </p>
  )
}

/** Is each OpenTelemetry demo UI up? Click through to look yourself. Refreshes every 15 s. */
function StackBar() {
  const [services, setServices] = useState<StackService[]>([])
  useEffect(() => {
    const load = () => api.stack().then((s) => setServices(s.services)).catch(() => setServices([]))
    load()
    const t = setInterval(load, 15_000)
    return () => clearInterval(t)
  }, [])
  if (!services.length) return null
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs" aria-label="OpenTelemetry demo status">
      <span className="text-muted-foreground">Demo:</span>
      {services.map((s) => (
        <a className="flex items-center gap-1 rounded-full border border-border px-2 py-0.5 hover:bg-muted"
          href={s.url} key={s.name} rel="noreferrer" target="_blank" title={`${s.url} · ${s.detail}`}>
          <span className={cn('size-1.5 rounded-full', s.ok ? 'bg-primary' : 'bg-destructive')} />
          {s.name}<span className="sr-only">{s.ok ? ' up' : ' down'}</span>
        </a>
      ))}
    </div>
  )
}

function RunFacts({ d }: { d: IncidentDetail }) {
  const f = runFacts(d)
  const rows: [string, string | undefined][] = [
    ['Model', f.model],
    ['Started', f.started],
    ['Took', f.took],
    ['Checks run', `${f.checks}${f.rejected ? ` (${f.rejected} diagnosis rejected)` : ''}`],
    ['Evidence cited', `${f.cited} of ${f.checks}`],
    ['Incident', d.id],
    ['Agent state', d.state ?? undefined],
  ]
  return (
    <div className="rounded-xl border border-border bg-card p-3.5">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">About this run</p>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        {rows.filter(([, v]) => v).map(([k, v]) => (
          <div className="contents" key={k}>
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="min-w-0 break-words font-mono">{v}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-2.5 flex flex-wrap gap-1">
        {f.sources.map((s) => (
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs" key={s}>{SOURCE_LABEL[s] ?? s}</span>
        ))}
      </div>
    </div>
  )
}

const SUGGESTIONS = [
  'Error rate up on checkout',
  'Checkout requests timing out',
  'Homepage latency above threshold',
].map((label) => ({ id: label, label }))

function readApprover() {
  try { return localStorage.getItem('approver') ?? '' } catch { return '' }
}

/** Action API reply first, then the recovery check from fresh telemetry. */
function actStep(d: IncidentDetail): Pick<AITask, 'status' | 'note'> {
  if (d.closed?.event !== 'approved') return { status: 'pending', note: d.closed ? 'not run' : 'after approval' }
  const v = d.verification
  if (v?.event === 'verified') return { status: 'done', note: v.detail }
  if (v?.event === 'recovery_unconfirmed') return { status: 'failed', note: 'recovery not confirmed' }
  const api = d.closed.action_api?.status ?? 'not sent'
  if (api === 'not_connected') return { status: 'running', note: 'waiting for Action API' }
  if (['refused', 'failed', 'unreachable'].includes(api)) return { status: 'failed', note: `Action API: ${api}` }
  return { status: 'running', note: `${api}, verifying recovery` }
}

function pipeline(d: IncidentDetail): AITask[] {
  const tools = d.transcript.filter((e) => e.kind === 'tool')
  const err = new Set(d.evidence.filter((e) => e.error).map((e) => e.id))
  const escalated = d.diagnosis.decision === 'escalate' || !d.payload
  const gate = escalated ? 'done' : d.closed ? (d.closed.event === 'approved' ? 'done' : 'failed') : 'running'
  return [
    { id: 'detect', label: 'Detect', status: 'done', note: `alert at ${d.transcript[0]?.t ?? '?'}` },
    {
      id: 'investigate', label: 'Investigate', status: 'done', note: `${tools.length} checks`,
      children: tools.map((e, i) => ({
        id: `t${i}`, label: e.name ?? 'tool', note: e.evidence_id,
        status: err.has(e.evidence_id ?? '') ? 'failed' : 'done',
      })),
    },
    {
      id: 'diagnose', label: 'Diagnose', status: 'done',
      note: escalated ? 'escalated, unsure' : `${d.diagnosis.root_cause?.component} · ${d.diagnosis.confidence.toFixed(2)}`,
    },
    {
      id: 'approve', label: 'Ask approval', status: gate,
      note: escalated ? 'nothing to approve'
        : d.closed ? `${d.closed.event} by ${d.closed.approver}` : `waiting: ${describeAction(d.payload!)}`,
    },
    { id: 'act', label: 'Act & verify', ...actStep(d) },
    { id: 'report', label: 'Report', status: d.report ? 'done' : 'pending', note: d.report ? 'report.md written' : undefined },
  ]
}

function Confidence({ d }: { d: IncidentDetail['diagnosis'] }) {
  const pct = Math.round((d.confidence ?? 0) * 100)
  return (
    <div className="rounded-xl border border-border bg-card p-3.5">
      <div className="flex items-baseline justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Confidence</p>
        <p className="font-mono text-lg tabular-nums">{(d.confidence ?? 0).toFixed(2)}</p>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary transition-[width] duration-500" style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{d.calibration_note || 'not calibrated'}</p>
    </div>
  )
}

export default function App() {
  const [incidents, setIncidents] = useState<IncidentSummary[]>([])
  const [kill, setKill] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<IncidentDetail | null>(null)
  const [approver, setApprover] = useState(readApprover)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [resetKey, setResetKey] = useState(0)
  const [canInvestigate, setCanInvestigate] = useState(true)

  const refresh = useCallback(async (id?: string | null) => {
    const s = await api.state()
    setIncidents(s.incidents)
    setKill(s.kill)
    setCanInvestigate(s.can_investigate)
    const pick = id ?? s.incidents[0]?.id ?? null
    setSelected(pick)
    setDetail(pick ? await api.incident(pick) : null)
  }, [])

  useEffect(() => { refresh().catch((e) => setError(String(e.message ?? e))) }, [refresh])
  useEffect(() => { try { localStorage.setItem('approver', approver) } catch { /* private mode */ } }, [approver])
  // While an approved action is being verified, follow it (the server appends the result).
  const verifying = !!detail && actStep(detail).status === 'running' && detail.closed?.action_api?.status !== 'not_connected'
  useEffect(() => {
    if (!verifying) return
    const t = setInterval(() => { refresh(selected).catch(() => {}) }, 5_000)
    return () => clearInterval(t)
  }, [verifying, selected, refresh])

  const run = async (fn: () => Promise<unknown>, id = selected) => {
    setError(null)
    try { await fn() } catch (e) { setError((e as Error).message); setResetKey((k) => k + 1) }
    await refresh(id).catch((e) => setError(String(e.message ?? e)))
  }

  const decide = (decision: DecisionRecord['event']) =>
    run(() => api.decide(selected!, decision, approver))

  const investigate = async (alert: string) => {
    setBusy(true)
    setError(null)
    try {
      const { id } = await api.investigate(alert)
      await refresh(id)
    } catch (e) {
      setError(`Investigation failed: ${(e as Error).message}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-dvh flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-2.5">
        <AgentAvatar seed="incident-zero" size={32} />
        <div>
          <p className="text-sm font-semibold leading-tight">Incident Zero</p>
          <p className="text-xs text-muted-foreground leading-tight">On-call approval</p>
        </div>
        <div className="mr-auto hidden lg:block"><StackBar /></div>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          Approver
          <input
            className="w-36 rounded-lg border border-border bg-background px-2.5 py-1.5 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring"
            onChange={(e) => setApprover(e.target.value)}
            placeholder="your name"
            value={approver}
          />
        </label>
        <button
          aria-pressed={kill}
          className={cn(
            'flex cursor-pointer items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors',
            kill ? 'border-destructive bg-destructive text-white' : 'border-border hover:bg-muted',
          )}
          onClick={() => run(() => api.kill(!kill))}
          type="button"
        >
          <Power size={14} /> KILL {kill ? 'ON' : 'off'}
        </button>
      </header>

      <div className="flex min-h-0 flex-1">
        <nav className="hidden w-80 shrink-0 xl:w-96 overflow-y-auto border-r border-border p-2 md:block" aria-label="Incidents">
          <p className="px-2 py-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">Incidents</p>
          {incidents.map((i) => (
            <button
              className={cn(
                'mb-0.5 flex w-full cursor-pointer items-start gap-2 rounded-lg px-2 py-2 text-left text-sm transition-colors',
                i.id === selected ? 'bg-muted' : 'hover:bg-muted/60',
              )}
              key={i.id}
              onClick={() => run(async () => {}, i.id)}
              type="button"
            >
              <span className={cn('mt-1.5 size-2 shrink-0 rounded-full',
                i.decision === 'diagnosed' ? 'bg-primary' : 'bg-amber-500')} />
              <span className="min-w-0">
                <span className="block truncate">{i.alert || i.id}</span>
                <span className="block truncate font-mono text-xs text-muted-foreground">
                  {i.id} · {(i.confidence ?? 0).toFixed(2)}{i.closed ? ` · ${i.closed}` : ''}
                </span>
              </span>
            </button>
          ))}
        </nav>

        <main className="flex min-w-0 flex-1 flex-col">
          <select
            aria-label="Incident"
            className="mx-4 mt-3 rounded-lg border border-border bg-background px-2.5 py-2 text-sm md:hidden"
            onChange={(e) => run(async () => {}, e.target.value)}
            value={selected ?? ''}
          >
            {incidents.map((i) => (
              <option key={i.id} value={i.id}>{i.decision === 'diagnosed' ? '●' : '○'} {i.id} · {i.alert}</option>
            ))}
          </select>
          {error && (
            <p className="mx-4 mt-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
              {error}
            </p>
          )}
          <AIConversation className="min-h-0 flex-1" contentKey={`${selected}-${detail?.decisions.length}-${detail?.verification?.event}-${busy}`}>
            <div className="grid gap-6 px-6 py-6 lg:grid-cols-[minmax(0,1fr)_360px] 2xl:grid-cols-[minmax(0,1fr)_440px]">
              <div className="min-w-0">
                {detail ? (
                  <>
                    <h1 className="mb-3 text-2xl font-semibold tracking-tight">{detail.diagnosis.alert || detail.id}</h1>
                    <StatusBanner d={detail} kill={kill} />
                    <Thread approver={approver} d={detail} kill={kill} onDecide={decide} resetKey={resetKey} />
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">No incidents yet. Type an alert below to start one.</p>
                )}
                {busy && <AILoader className="mt-5" label="Investigating" showElapsed variant="bar" />}
              </div>
              {detail && (
                <aside className="flex flex-col gap-3 lg:sticky lg:top-5 lg:self-start">
                  <AITaskList className="rounded-xl border border-border bg-card p-3.5" label="Pipeline" tasks={pipeline(detail)} />
                  <Confidence d={detail.diagnosis} />
                  <RunFacts d={detail} />
                </aside>
              )}
            </div>
          </AIConversation>

          {canInvestigate && (
            <div className="w-full px-6 pb-5">
              <AISuggestions className="mb-2" label="Try an alert" onSelect={(s) => investigate(s.label)} suggestions={SUGGESTIONS} />
              <AIPromptInput
                aria-label="New alert to investigate"
                disabled={busy}
                onSubmit={investigate}
                placeholder="Describe a new alert, e.g. 'error rate up on checkout'"
                state={busy ? 'thinking' : 'idle'}
              />
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
