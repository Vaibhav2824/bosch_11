import AgentAvatar from '@/components/smoothui/agent-avatar'
import AIApproval from '@/components/smoothui/ai-approval'
import AICitation from '@/components/smoothui/ai-citation'
import AIMessage from '@/components/smoothui/ai-message'
import AIReasoning from '@/components/smoothui/ai-reasoning'
import AIToolCall from '@/components/smoothui/ai-tool-call'
import { ShieldAlert, ShieldCheck, Siren } from 'lucide-react'
import type { ReactNode } from 'react'
import type { DecisionRecord, IncidentDetail, VerificationRecord } from './api'
import { confidenceExplained, describeAction, describeTool, runFacts, SOURCE_LABEL } from './describe'

const agent = <AgentAvatar seed="incident-zero" size={32} />
const human = (
  <span className="flex size-7 items-center justify-center rounded-full bg-muted text-xs font-semibold">
    You
  </span>
)
const pre = 'max-h-96 overflow-auto whitespace-pre-wrap break-all font-mono text-xs leading-snug'

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-4 first:mt-0">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      <div className="mt-1 text-base leading-relaxed">{children}</div>
    </section>
  )
}

/** Citation pills open a link by default; here they jump to the tool call that holds the evidence. */
function EvidencePill({ index, ev, onJump }: {
  index: number
  ev: IncidentDetail['diagnosis']['evidence'][number]
  onJump: (id: string) => void
}) {
  return (
    <span onClickCapture={(e) => { e.preventDefault(); onJump(ev.evidence_id) }}>
      <AICitation
        description={`“${ev.quote}”`}
        label={index + 1}
        title={`${ev.evidence_id} · ${SOURCE_LABEL[ev.source ?? ''] ?? ev.source ?? 'evidence'}`}
        url={`#${ev.evidence_id}`}
      />
    </span>
  )
}

function Investigation({ d }: { d: IncidentDetail }) {
  const facts = runFacts(d)
  const thoughts = d.transcript.filter((e) => e.kind === 'thought' && e.text)
  const byId = Object.fromEntries(d.evidence.map((e) => [e.id, e]))
  const citedAt = Object.fromEntries(d.diagnosis.evidence.map((e, i) => [e.evidence_id, i + 1]))
  const steps = d.transcript.filter((e) => e.kind === 'tool' || e.kind === 'rejected')
  let n = 0
  return (
    <>
      <AIMessage avatar={agent} from="assistant" timestamp={facts.started}>
        <p className="text-sm">
          I investigated with <b>{facts.checks} checks</b> across{' '}
          {facts.sources.map((s) => SOURCE_LABEL[s] ?? s).join(', ') || 'no sources'}
          {facts.took ? <>, taking <b>{facts.took}</b></> : null}. Each result was stored with an evidence ID; my diagnosis
          may only quote text that really appears in those results. {facts.cited > 0
            ? `${facts.cited} of them ended up as cited evidence.`
            : 'None of them made it into an accepted diagnosis.'}
        </p>
      </AIMessage>
      <AIMessage avatar={agent} bubble={false} from="assistant">
        <ol className="flex w-full flex-col gap-3">
          {thoughts.length > 0 && (
            <li>
              <AIReasoning duration={0}>
                {thoughts.map((t, i) => <p key={i} className="mb-1">{t.text}</p>)}
              </AIReasoning>
            </li>
          )}
          {steps.map((e, i) => {
            if (e.kind === 'rejected') {
              return (
                <li key={i}>
                  <p className="mb-1.5 text-sm">
                    <span className="font-medium text-destructive">Diagnosis rejected by the evidence check.</span>{' '}
                    <span className="text-muted-foreground">A claim did not match the recorded evidence, so I had to try again.</span>
                  </p>
                  <AIToolCall name="submit_diagnosis" result={<pre className={pre}>{e.error}</pre>}
                    status="error" summary={e.t} />
                </li>
              )
            }
            const ev = byId[e.evidence_id ?? '']
            const cite = citedAt[e.evidence_id ?? '']
            n += 1
            return (
              <li key={i} id={e.evidence_id} className="scroll-mt-24 rounded-xl target:ring-2 target:ring-ring target:ring-offset-4 target:ring-offset-background">
                <p className="mb-1.5 flex flex-wrap items-baseline gap-x-2 text-sm">
                  <span className="font-mono text-xs text-muted-foreground">{n}.</span>
                  <span className="min-w-0 flex-1">{describeTool(e)}</span>
                  {cite && <span className="rounded-full bg-primary/15 px-2 py-0.5 text-xs font-medium text-primary">cited as evidence {cite}</span>}
                  {ev?.error && <span className="rounded-full bg-destructive/10 px-2 py-0.5 text-xs font-medium text-destructive">tool failed</span>}
                  {ev?.link && (
                    <a className="text-xs font-medium text-primary underline-offset-2 hover:underline" href={ev.link.url}
                      rel="noreferrer" target="_blank">{ev.link.label} ↗</a>
                  )}
                </p>
                <AIToolCall
                  args={<pre className={pre}>{JSON.stringify(e.args ?? {}, null, 1)}</pre>}
                  name={e.name ?? 'tool'}
                  result={ev ? <pre className={pre}>{ev.preview}</pre> : undefined}
                  status={ev?.error ? 'error' : 'success'}
                  summary={`${e.evidence_id} · ${SOURCE_LABEL[ev?.source ?? ''] ?? ''} · ${e.t}`}
                />
              </li>
            )
          })}
        </ol>
      </AIMessage>
    </>
  )
}

function DiagnosisMessage({ d, onJump }: { d: IncidentDetail; onJump: (id: string) => void }) {
  const dx = d.diagnosis
  return (
    <AIMessage avatar={agent} copyText={dx.summary} from="assistant">
      {dx.decision === 'escalate' && (
        <p className="mb-3 flex items-center gap-1.5 font-medium text-amber-700 dark:text-amber-400">
          <ShieldAlert size={16} /> I'm not sure, so I'm escalating to you instead of proposing a fix.
        </p>
      )}
      <Section title="What users are seeing">{dx.summary}</Section>
      {dx.root_cause && (
        <Section title="Root cause">
          <span className="font-mono font-medium">{dx.root_cause.component}</span>: {dx.root_cause.cause}
        </Section>
      )}
      {dx.evidence.length > 0 && (
        <Section title="Why I think so">
          <ol className="space-y-2">
            {dx.evidence.map((ev, i) => (
              <li key={ev.evidence_id}>
                <span className="text-muted-foreground">{SOURCE_LABEL[ev.source ?? ''] ?? ev.source}:</span>{' '}
                “<span className="font-mono text-[13px] break-all">{ev.quote}</span>”. {ev.why}{' '}
                <EvidencePill ev={ev} index={i} onJump={onJump} />
              </li>
            ))}
          </ol>
        </Section>
      )}
      <Section title="How sure I am">
        <b className="tabular-nums">{dx.confidence.toFixed(2)}</b>. {confidenceExplained(dx)}
      </Section>
      {!!dx.alternatives_ruled_out?.length && (
        <Section title="What I ruled out">
          <ul className="list-disc space-y-0.5 pl-4">{dx.alternatives_ruled_out.map((x) => <li key={x}>{x}</li>)}</ul>
        </Section>
      )}
      {!!dx.open_questions?.length && (
        <Section title="Still unknown">
          <ul className="list-disc space-y-0.5 pl-4">{dx.open_questions.map((x) => <li key={x}>{x}</li>)}</ul>
        </Section>
      )}
    </AIMessage>
  )
}

function Proposal({ d, approver, kill, onDecide, resetKey }: {
  d: IncidentDetail
  approver: string
  kill: boolean
  onDecide: (decision: DecisionRecord['event']) => void
  resetKey: number
}) {
  const p = d.payload
  if (!p) {
    return (
      <AIMessage avatar={agent} from="assistant">
        <Section title="Next step">
          I am not proposing any change. Please take over using the findings above; every tool result is
          listed with its evidence ID (incident <code>{d.id}</code>).
        </Section>
      </AIMessage>
    )
  }
  const rollback = d.diagnosis.proposed_action?.rollback
  const what = describeAction(p)
  const details = (
    <div className="space-y-2">
      <p><b className="text-foreground">What will happen:</b> {what}, by sending <code>{p.action}</code> with target{' '}
        <code>{p.target}</code> to the Action API. Nothing else is touched.</p>
      <p><b className="text-foreground">Why:</b> {p.reason}</p>
      {rollback && <p><b className="text-foreground">If it does not help:</b> {rollback}</p>}
      <p><b className="text-foreground">What approving does:</b> records your name, the time and a fingerprint of this
        exact request in <code>logs/actions.jsonl</code>. Without that record the action cannot run. Reject keeps the
        system as it is and leaves the incident with you.</p>
    </div>
  )
  const resolved = d.closed ? (d.closed.event === 'approved' ? 'approve' : 'reject') : undefined
  const blocked = !d.closed && (kill || !approver.trim())
  return (
    <AIMessage avatar={agent} bubble={false} from="assistant">
      <div className="w-full max-w-4xl">
        {blocked ? (
          <div className="rounded-xl border border-border bg-background p-3.5">
            <p className="text-sm font-medium">{what}?</p>
            <div className="mt-1 text-xs leading-relaxed text-muted-foreground">{details}</div>
            <p className="mt-3 rounded-lg bg-muted px-3 py-2 text-xs">
              {kill
                ? 'The kill switch is on, so approvals are blocked. Turn it off at the top to decide.'
                : 'Enter your name at the top. Every decision is recorded with the approver’s name.'}
            </p>
          </div>
        ) : (
          <AIApproval
            key={`${d.id}-${resolved ?? 'open'}-${resetKey}`}
            onDecide={(o) => onDecide(o.id === 'approve' ? 'approved' : 'rejected')}
            options={[
              { id: 'approve', label: `Approve: ${what}`, detail: `as ${approver || '…'}`, destructive: true },
              { id: 'reject', label: 'Reject', detail: 'change nothing, I take over' },
            ]}
            question={`${what}?`}
            resolvedId={resolved}
          >
            {details}
          </AIApproval>
        )}
        {!d.closed && approver.trim() && (
          <button
            className="mt-2 cursor-pointer text-xs text-muted-foreground underline-offset-2 hover:underline"
            onClick={() => onDecide('dry_run')}
            type="button"
          >
            Dry run: show the exact request without approving it
          </button>
        )}
      </div>
    </AIMessage>
  )
}

function VerificationMessage({ v }: { v: VerificationRecord }) {
  const head = {
    verifying: 'Action executed. Checking fresh telemetry to confirm the shop has recovered…',
    verified: `Recovery verified from fresh telemetry: ${v.detail}.`,
    recovery_unconfirmed: `Recovery not confirmed: ${v.detail}. Handing this back to you.`,
  }[v.event]
  return (
    <AIMessage avatar={agent} from="assistant" timestamp={v.t.slice(11, 16)}>
      <div className="flex items-start gap-1.5 text-sm">
        {v.event === 'recovery_unconfirmed'
          ? <ShieldAlert className="mt-0.5 shrink-0 text-destructive" size={16} />
          : <ShieldCheck className="mt-0.5 shrink-0 text-primary" size={16} />}
        <div className="space-y-1">
          <p>{head}</p>
          {v.checks && (
            <ul className="space-y-0.5">
              {v.checks.map((c) => (
                <li key={c.check}>{c.ok ? '✓' : '✗'} {c.check}: <code>{c.value}</code></li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </AIMessage>
  )
}

function DecisionMessages({ r }: { r: DecisionRecord }) {
  const verb = { approved: 'Approved', rejected: 'Rejected', dry_run: 'Asked for a dry run' }[r.event]
  return (
    <>
      <AIMessage avatar={human} from="user" timestamp={r.t.slice(11, 16)}>
        {verb}{r.note ? `: ${r.note}` : ''} <span className="opacity-70">({r.approver})</span>
      </AIMessage>
      <AIMessage avatar={agent} from="assistant" copyText={JSON.stringify(r.payload, null, 2)}>
        {r.event === 'approved' && (
          <div className="flex items-start gap-1.5 text-sm">
            <ShieldCheck className="mt-0.5 shrink-0 text-primary" size={16} />
            <div className="space-y-1">
              <p>Approval recorded for {r.approver} at {r.t.replace('T', ' ')}, fingerprint <code>{r.fingerprint}</code>.</p>
              <p>
                Action API: <b>{r.action_api?.status === 'not_connected' ? 'not connected yet' : r.action_api?.status}</b>.{' '}
                {r.action_api?.status === 'not_connected'
                  ? 'Nothing has changed in the shop. The approved request is waiting in the action log and will run once the Action API is wired in.'
                  : r.action_api?.detail}
              </p>
            </div>
          </div>
        )}
        {r.event === 'rejected' && (
          <p className="text-sm">Rejected and recorded. I will not take any action; the incident stays with you.</p>
        )}
        {r.event === 'dry_run' && (
          <>
            <p className="text-sm">Dry run only, nothing was approved or sent. This is the exact request approval would release:</p>
            <pre className={`${pre} mt-2 rounded-lg bg-muted p-2`}>{JSON.stringify(r.payload, null, 2)}</pre>
          </>
        )}
      </AIMessage>
    </>
  )
}

export default function Thread({ d, approver, kill, onDecide, resetKey }: {
  d: IncidentDetail
  approver: string
  kill: boolean
  onDecide: (decision: DecisionRecord['event']) => void
  /** Bumped when a decision fails, so the approval card un-resolves itself. */
  resetKey: number
}) {
  const jump = (id: string) => {
    history.replaceState(null, '', `#${id}`)
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
  return (
    <div className="flex flex-col gap-5">
      <AIMessage
        avatar={<span className="flex size-7 items-center justify-center rounded-full bg-destructive/10 text-destructive"><Siren size={14} /></span>}
        from="user"
        timestamp={d.transcript[0]?.t}
      >
        <p className="text-xs opacity-70">Alert received</p>
        {d.diagnosis.alert}
      </AIMessage>
      <Investigation d={d} />
      <DiagnosisMessage d={d} onJump={jump} />
      <Proposal approver={approver} d={d} kill={kill} onDecide={onDecide} resetKey={resetKey} />
      {d.decisions.map((r) => <DecisionMessages key={r.t + r.event} r={r} />)}
      {d.verification && <VerificationMessage v={d.verification} />}
    </div>
  )
}
