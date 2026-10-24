# Incident Zero approval UI (template)

A chat-style approval UI for the on-call agent (stretch goal 4), built from SmoothUI's AI
components. It shows what the agent did step by step, explains its diagnosis and confidence,
and lets the on-call human approve, reject or dry-run the proposed fix. It also shows whether
each OpenTelemetry demo UI is up and links evidence into Jaeger and Grafana.

It does not need your agent's code to match it. You point it at your agent with environment
variables, and one mapping function translates your agent's JSON.

```
incident_ui/      Python server (stdlib only): config, approval gate, sources, demo stack
web/              React + SmoothUI front end (build once, the server serves it)
sample_runs/      three real incidents from our agent, to try it with no agent running
tests/            approval gate, server guardrails, mapper (pytest)
.env.example      every setting with its default
```

## 1. Try it on the samples (2 minutes)

Needs Python 3.11+ and Node 20+.

```bash
cd web && npm install --legacy-peer-deps && npm run build && cd ..
UI_RUN_DIRS=sample_runs UI_INVESTIGATE=none python -m incident_ui
```

Open http://127.0.0.1:8502. On Windows `cmd`, use `set UI_RUN_DIRS=sample_runs` first.

## 2. Connect your agent

Pick the case that matches your code.

**A. Your agent writes run folders** (like `oncall_agent`: `runs/<id>/diagnosis.json`,
`transcript.jsonl`, `evidence.jsonl`, `report.md`). Run from your project root:

```bash
UI_RUN_DIRS=runs,reports UI_INVESTIGATE=oncall_agent.agent:investigate python -m incident_ui
```

`UI_INVESTIGATE` is whatever function starts an investigation (`module:function`, takes the
alert text, returns the run folder or `{"run_dir": ...}`). Use `none` to hide the alert box.
If the template folder is not inside your project, also set `UI_AGENT_ROOT` to your project root.

**B. Your agent has an HTTP API** (like the plan's FastAPI service with `/incidents`):

```bash
UI_SOURCE=http UI_AGENT_API_URL=http://127.0.0.1:8000 \
UI_AGENT_API_DECIDE=/incidents/{id}/{decision} python -m incident_ui
```

Change `UI_AGENT_API_LIST / GET / CREATE / DECIDE` if your paths differ (see `.env.example`).
With `DECIDE` set, approve and reject are POSTed to your agent with
`{approver, payload, fingerprint, note}`, so your own state machine moves on. Your agent then
calls the Action API, not the UI.

## 3. If your JSON looks different

`normalize()` in `incident_ui/sources.py` is the only code that knows the agent's format.
It already understands:

- our format (`diagnosis.json` with `decision`, `root_cause{component,cause}`, `evidence[]`,
  `proposed_action{action,target,reason}`);
- the hackathon plan's model (`state`, `alert{raw}`, `hypothesis{root_cause, affected_component,
  supporting_evidence[]}`, `action_proposal{action_id, service, explanation, rollback_plan}`,
  `Evidence{tool_name, kind, query, result_summary, deep_link}`);
- common alternative names (each field tries several, e.g. `quote|excerpt|result_summary`).

If a field shows up empty, add your field name to that `_pick(...)` call. Run `pytest` after.
`tests/test_sources.py` has a plan-style example to copy for your own format.

What the UI needs at minimum: an id, the alert text, `decision` (or a state like ESCALATED),
a root cause and confidence when diagnosed, and a proposed action for there to be anything to
approve. Steps, evidence, quotes and the report are shown when present.

## The OpenTelemetry demo

- The header shows Shop, Jaeger, Grafana, Prometheus and Load generator as up or down
  (status codes only, refreshed every 15 s). Click any one to open it.
- Trace evidence links to the trace in Jaeger when the result contains a trace id
  (`example_trace_id`, `trace_id`), otherwise to a Jaeger search for that service. Metrics
  evidence links to Grafana. An agent-supplied `deep_link` takes priority.
- URLs default to the demo behind the frontend proxy on :8080 (`make start` /
  `make start-minimal`). Override with `DEMO_*_URL`.
- Feature flags are off limits (reading them disqualifies the team). Any flagd or
  feature-flag URL is refused at startup and stripped from evidence links.

## Safety

- Every approve, reject and dry run is appended to `logs/actions.jsonl`: approver, time, the
  exact payload and a SHA-256 fingerprint of it.
- The payload is rebuilt on the server from the agent's diagnosis; the browser cannot change it.
- Only incidents the source listed are accepted; each can be approved or rejected once.
- KILL switch (header button, or create a `KILL` file) blocks approvals (HTTP 403).
- Dry runs are never forwarded. The server listens on 127.0.0.1 only.
- **Action API.** In runs mode an approval is POSTed to `UI_ACTION_API_URL` (default
  `http://127.0.0.1:8090/actions`) with `{incident, approver, payload, fingerprint}`. Start the
  local stand-in with `python action_api.py` (restart_service, throttle_load_generator; refuses
  scale_service, feature flags, unapproved or altered requests; logs to `logs/action_api.jsonl`).
  Point the URL at the organisers' Action API when you have it; set it empty to record only.
- **Verify.** After the Action API accepts, the UI polls fresh telemetry (target container
  running and healthy, every service under 2% errors over 2m) until it recovers or
  `UI_VERIFY_TIMEOUT` (360 s) runs out, then logs `verified` or `recovery_unconfirmed`.
- Add `logs/` and `KILL` to your `.gitignore`.

## Develop

```bash
python -m pytest            # 16 tests
cd web && npm run dev       # live reload on :5173, proxies /api to :8502 (keep the server running)
```

Vite is pinned to 6 because Vite 8 needs Node 20.19+. `--legacy-peer-deps` avoids an npm 10.9
install crash. SmoothUI components are in `web/src/components/smoothui/` (added with the shadcn
CLI); `ai-message` and a few 10–11px labels were enlarged locally, so re-adding them with the
CLI would undo that. UI wording for each tool lives in `web/src/describe.ts`; for other tool
names it uses the step's `description`/`relevance` from your agent, or "Ran <tool>".

## Not done

- Act & verify after approval (polling health until recovered) belongs to the agent; the UI
  shows "waiting for Action API" (runs mode) or your agent's reply (http mode).
- The http source asks for each incident to build the list (fine for tens, not thousands).
- Not tested against a live agent with an LLM key from this UI; tested against the samples,
  the mock agent API and the live demo stack's status endpoints.
