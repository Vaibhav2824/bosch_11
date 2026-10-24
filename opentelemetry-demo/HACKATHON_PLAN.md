# Incident Zero — execution plan

## 1. Outcome

Build an **AI on-call engineer** for the OpenTelemetry Astronomy Shop.  Given a
production alert, it must turn telemetry into an evidence-backed diagnosis,
propose the smallest safe recovery, wait for a human decision, execute only an
approved action through the supplied Action API, verify recovery, and create an
incident report.

The product is successful when the full lifecycle is visible and repeatable:

```text
alert → investigate → diagnose → propose → approve/reject
      → execute through Action API → verify → report
```

It is not enough for an LLM to describe a likely fix.  The system must make
each state, piece of evidence, approval decision, action, and verification
result inspectable.

## 2. Constraints to protect from the start

- Treat telemetry and deployment history as **read-only evidence sources**.
- Never directly change the demo, the feature-flag configuration, `faultctl`,
  or any hidden-test configuration.  The only write path is the supplied
  **Action API**, and it is available only after approval.
- An uncertain result is a valid outcome.  Escalate with the evidence instead
  of fabricating a root cause or executing an unsafe fix.
- Preserve an audit trail: timestamps, tools called, evidence snippets,
  confidence, proposed action, approver, execution result, and verification.
- Do not commit API keys or the supplied test/harness data.
- The event material says both that teams contain five people and that three
  members must commit.  We will have **all five members make a small,
  attributable commit** to remove any ambiguity.

## 3. What already exists in this repository

The repository contains an optional Python agent layer that is the best base
for the hackathon solution:

- `src/agent/` — FastAPI + LangGraph/LangChain agent service.
- `src/mcp/` — MCP service; currently exposes shop operations, not on-call
  diagnostics.
- `compose.agent.yaml` — starts `agent`, `mcp`, and `chatbot` alongside the
  Astronomy Shop.
- `src/flagd/demo.flagd.json` — failure scenarios used by the demo.  It helps
  us understand the application, but it must not be used by the agent as a
  diagnostic shortcut during the event.
- Collector, tracing, logging, metrics, frontend, and feature-flag services
  already run as part of the demo stack.

We will extend `src/agent/` rather than introduce a second service.  It keeps
the architecture small, observable, and easy for judges to run.

## 4. Target architecture

```text
                 read-only                         human-controlled
Alert ──► On-call API ──► evidence tools ──► diagnosis ──► approval UI
              │                │                   │             │
              │                ├─ traces            │             ▼
              │                ├─ metrics            │       approval event
              │                ├─ logs               │             │
              │                ├─ service health     ▼             ▼
              │                └─ deployment history proposed plan Action API
              │                                      │             │
              └──────────── incident state ◄─────────┴──── verify recovery
                                                     │
                                                     ▼
                                               JSON + readable report
```

### 4.1 Service boundaries

`src/agent` will own the workflow, incident state, HTTP API, and report
generation.  Its design must distinguish three kinds of tools:

| Tool class | Permission | Examples | Rule |
| --- | --- | --- | --- |
| Evidence tools | Read-only | search logs, query traces/metrics, health, deployment history | May run during investigation. |
| Decision tools | No side effect | correlate evidence, retrieve prior incident, reviewer critique | May run before approval. |
| Action tool | Write | supplied Action API | Must reject every call unless incident state is `APPROVED`. |

The final Action API contract will be supplied at the event.  We will hide it
behind a small adapter (`action_client.py`) so only that file needs changing
when its endpoint, action names, or request format are revealed.

### 4.2 Incident state machine

Use an explicit workflow state, not an unconstrained chat loop:

```text
NEW → INVESTIGATING → DIAGNOSED → AWAITING_APPROVAL
  ├→ ESCALATED
  └→ REJECTED → CLOSED

AWAITING_APPROVAL → APPROVED → EXECUTING → VERIFYING → RESOLVED
                                         └→ RECOVERY_UNCONFIRMED → ESCALATED
```

Transitions are persisted and logged.  The `execute` function must validate
both `APPROVED` state and an approval token tied to the exact proposed action;
a stale or modified proposal requires a new approval.

### 4.3 Core data model

Use Pydantic models and JSON serialization so reports are reproducible:

- `Alert`: ID, received time, service/symptom, severity, time range, raw alert.
- `Evidence`: tool name, query, time range, result summary, deep link/ID,
  source timestamp, relevance to the hypothesis.
- `Hypothesis`: root cause, affected component, confidence (0–1), supporting
  and contradicting evidence, known uncertainty.
- `ActionProposal`: action ID, human explanation, Action API payload, risk,
  expected result, rollback or escalation path.
- `Approval`: decision, actor, timestamp, exact action fingerprint, note.
- `ActionExecution`: request/response summary, timestamp, success/failure.
- `Verification`: checks run, before/after evidence, final status.
- `Incident`: the aggregate and its state-transition history.

## 5. Required seven-stage flow

### Stage 1 — Detect

**Build:** `POST /incidents` (or the supplied alert integration) creates an
incident from an alert.  A demo button may submit a realistic alert, but the
same API must work without clicking through the UI.

**Done when:** a received alert yields an incident ID, `NEW` state, and an
audit-log event.

### Stage 2 — Investigate with tools

**Build:** bounded, read-only tool wrappers for the allowed telemetry sources.
Start each investigation with a fixed time window around the alert, then query
service error rate/latency, relevant traces, correlated logs, service health,
and deployment history.

**Done when:** every diagnosis has at least two independently useful evidence
items, each with source, time range, and result summary.  Tool failures are
recorded and never silently treated as evidence.

### Stage 3 — Diagnose from evidence

**Build:** an evidence synthesizer that produces a root-cause hypothesis,
affected component, ranked alternatives, confidence, and an explanation of why
the evidence supports it.  Use the LLM only for synthesis; require structured
output validated against the data model.

**Safety rule:** if evidence is insufficient or confidence is below the agreed
threshold, move to `ESCALATED` and show what additional human investigation is
needed.

**Done when:** the agent names a root cause only with cited telemetry evidence,
and can clearly say “I do not know” for ambiguous incidents.

### Stage 4 — Propose a safe fix

**Build:** a small, allow-listed remediation catalog that maps diagnosed
incident types to legal Action API operations.  The proposal explains the
smallest remedy, expected recovery signal, risk, and escalation/rollback plan.

**Done when:** every suggested action is one that the supplied Action API
permits; no raw shell command, direct configuration edit, or invented action
can reach the execution path.

### Stage 5 — Ask for human approval

**Build:** a simple review endpoint and chat-facing approval card/message:

```text
Incident summary | evidence | confidence | proposed action | approve | reject
```

Approving stores an immutable fingerprint of the proposal.  Rejecting closes
the proposal, records optional feedback, and must never execute anything.

**Done when:** attempts to execute before approval, after rejection, or with a
changed action are blocked and auditable.

### Stage 6 — Act safely and verify

**Build:** the Action API adapter executes the approved request and then runs
the verification checks declared in the proposal.  Verification must be based
on fresh telemetry/health data, not merely a successful HTTP response from the
action endpoint.

**Done when:** a recovery is called `RESOLVED` only when health/error/latency
checks improve as expected.  Otherwise call it `RECOVERY_UNCONFIRMED` and
escalate.

### Stage 7 — Report

**Build:** generate the organiser-provided JSON incident schema exactly, plus a
short readable Markdown/HTML report.  Write reports to a clearly documented
`artifacts/incidents/` path excluded from version control, except for sanitized
examples.

**Done when:** each handled incident produces a machine-readable report and a
human-readable timeline containing root cause, evidence, approval, action,
verification, and limitations.

## 6. Implementation sequence

Work in this order; each milestone produces a demonstrable slice rather than
an unfinished subsystem.

### Milestone A — baseline and interfaces

1. Start the Astronomy Shop with the required Compose profiles and record the
   exact command in the README.
2. Confirm that traces, metrics, logs, service health, deployment history, and
   the Action API are accessible through the tools supplied at the event.
3. Capture the organiser’s incident-report JSON schema and Action API contract
   in versioned documentation (never include secrets).
4. Add `docs/architecture.md`, this plan, and a minimal `TEAM.md` template.

**Exit criterion:** the unmodified demo runs and one telemetry lookup works.

### Milestone B — safe workflow skeleton

1. Add the Pydantic incident models and state-transition guard.
2. Add endpoints for create incident, fetch incident, approve/reject, and
   execute approved plan.
3. Persist sanitized state locally for the duration of a demo run.
4. Unit-test forbidden state transitions, especially execution without an
   approval fingerprint.

**Exit criterion:** a mocked incident can move through every legal state;
unsafe transitions are rejected.

### Milestone C — evidence and diagnosis

1. Implement read-only tool adapters one at a time, returning normalized
   `Evidence` objects.
2. Begin with the signal most useful for the first practice incident; do not
   overbuild every query before validating one incident end-to-end.
3. Add deterministic correlation rules (service, time window, error signature)
   before LLM synthesis.
4. Add structured diagnosis output and the low-confidence escalation path.

**Exit criterion:** the agent correctly diagnoses at least three practice
incidents and explains evidence for each.

### Milestone D — approval, action, and verification

1. Wire the Action API adapter behind the state guard.
2. Implement the minimal approval experience—chat command or a small web card.
3. Implement post-action freshness checks and a bounded verification timeout.
4. Save action and verification events into the report timeline.

**Exit criterion:** a full happy path works against a practice incident, and
the blocked-before-approval scenario is demonstrated separately.

### Milestone E — reports, evaluation, and presentation

1. Validate generated JSON against the organiser’s schema.
2. Run every published practice incident; record results and limitations in
   `EVALUATION.md`.
3. Finish README setup, operation, approval safety, kill-switch behavior, and
   known limitations.
4. Prepare a one-page architecture overview and a 5-minute demo script using
   a single clean incident.

**Exit criterion:** all required deliverables are present, a fresh clone can
be started, and the team can reproduce the demo without ad-libbing.

## 7. Team ownership

Replace the placeholders with names before implementation.  Ownership is by
file boundary to minimise merge conflicts.

| Owner | Primary responsibility | First concrete deliverable |
| --- | --- | --- |
| Member A — coordinator | workflow, API contracts, integration | incident state models and transition tests |
| Member B — observability | evidence tools, correlation | normalized telemetry evidence adapter |
| Member C — agent | diagnosis prompt, structured output, confidence/escalation | evidence-to-hypothesis service |
| Member D — safety/actions | Action API adapter, approval guard, verification | action fingerprint + execute/verify path |
| Member E — experience/docs | approval UI/chat, reports, README, evaluation | approval screen and report renderer |

All members should make a meaningful commit early, before files become coupled.
Do integration through short checkpoints and agree before changing shared
models or Compose files.

## 8. Test and evaluation plan

For every practice incident, capture a row in `EVALUATION.md`:

| Incident | Diagnosis | Evidence cited | Confidence | Proposed action | Approval gate | Verification | Result / limitation |
| --- | --- | --- | --- | --- | --- | --- | --- |

Required test cases:

1. Correct diagnosis and approved recovery.
2. Low-confidence incident escalates without action.
3. Rejected proposal causes no side effect.
4. Approval cannot be reused after the proposal changes.
5. Action API error leaves the incident recoverable and reported.
6. Action succeeds but recovery is not observable; status is
   `RECOVERY_UNCONFIRMED`, not falsely resolved.
7. Generated JSON validates against the official schema.

Measure reliability, not just happy paths: diagnosis accuracy, evidence quality,
approval-gate correctness, action success, post-action recovery confirmation,
and false-confidence rate.

## 9. Stretch goals (only after the required path is stable)

1. **Incident memory:** retrieve sanitized reports for similar prior incidents;
   show which prior case influenced the new hypothesis.
2. **Reviewer agent:** independently challenge the primary diagnosis and block
   automatic progression when it finds missing or conflicting evidence.
3. **Calibrated confidence:** compare reported confidence with practice-set
   accuracy and adjust the escalation threshold.
4. **Chat-style approval:** let the on-call reviewer approve/reject through
   the supplied chat surface while retaining the same server-side guard.
5. **Prevention:** after resolution, suggest a code, configuration, dashboard,
   or alerting improvement.  Suggestions remain advisory—never auto-applied.

Do not start a stretch goal while any required flow can still execute an action
without approval, lacks verification, or fails to write a valid report.

## 10. Deliverable checklist

- [ ] Source code, with a README covering setup, running, approval, kill switch,
      and known limitations.
- [ ] One-page architecture overview.
- [ ] JSON and readable reports for handled practice incidents.
- [ ] Evaluation note: correct/incorrect cases and why.
- [ ] Team form: names, ownership, libraries/frameworks, models, and AI coding
      assistance disclosure.
- [ ] All five members have meaningful commits.
- [ ] Five-minute demo rehearsed: alert → evidence → diagnosis → approval →
      Action API → verification → report.

## 11. Demo narrative

1. Trigger or receive a realistic alert for a practice incident.
2. Show the incident ID and the evidence collection timeline.
3. Open the diagnosis: root cause, cited evidence, alternatives, confidence.
4. Show the smallest safe proposed action and why it is safe.
5. Demonstrate that the action is blocked until a human approves it.
6. Approve once; show the Action API log, new telemetry, and verification.
7. Open the final report and explain any limitation honestly.

The memorable proof point is the approval guard: show the agent refusing to
act before approval, then making a transparent, verifiable recovery afterward.
