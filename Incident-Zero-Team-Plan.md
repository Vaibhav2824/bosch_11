# Incident Zero — 5-person battle plan (Bosch × PES hackathon)

## Context
The task is to build an **AI On-Call Engineer** for the OpenTelemetry Demo (Astronomy Shop). The agent has to do 7 steps: Detect → Investigate → Diagnose → Propose → Get approval → Act & verify → Report. There are also **5 stretch goals**: incident memory, a reviewer agent, calibrated confidence, chat-style approval, and prevention. That's **12 goals** in total.

Scoring is out of 100:
- Checkpoint 1, Eyes: 10
- Checkpoint 2, Brain: 20
- Checkpoint 3, Hands: 20
- Checkpoint 4, hidden unseen incidents: 30
- Judges: 20
- Each student is also assessed individually.

Hard constraints from the slides:
- **Only Vaibhav (member A) runs the demo.** The other 4 develop against the organisers' **offline incident bundles** and against bundles A records from his live demo. They must **not** connect to A's laptop over the venue Wi-Fi, because rules out-of-scope #5 forbids "anything outside your own laptop / venue network".
- **No code before 09:15.** No commits are allowed between Day 1 18:45 and Day 2 09:00 either. The evening is for study only.
- **Code freeze is Day 2 at 14:00.** The milestone slide says 14:00 and the deliverables slide says 16:30. Plan for the earlier time.
- **Disqualification triggers:**
  - reading flagd settings (flagd files, flag UI or flag API)
  - touching the demo source, faultctl or the scoring harness
  - hard-coding answers to the practice incidents
  - changing anything except through the Action API after human approval
- **LLM: Groq free tier.** Limits checked today: `openai/gpt-oss-120b`, `openai/gpt-oss-20b` and `qwen/qwen3.8-27b` each allow **30 RPM, 1K RPD, 8K TPM, 200K TPD per org**. 8K tokens per minute is the binding constraint, so the design must be token-frugal.
- **Every member must commit code**, and all 5 of us must be able to explain and change any part of it.

---

## Architecture (one picture to share with the team)

```
            ┌────────────── Source (Live on A's laptop | Offline bundle on B–E laptops) ─────────────┐
            │ Prometheus :9090 (spanmetrics) · Jaeger via :8080/jaeger · OpenSearch · docker inspect │
            └───────────────────────────────▲────────────────────────────────────────────────────────┘
                                            │ tools return {summary ≤1.2K tokens, evidence[E#]}
 detect ──► investigate (ReAct, LLM picks next tool, ≤6 calls) ──► diagnose (JSON + cited E#s)
   ▲                                                                     │
   │ poll RED metrics                                   evidence validator + reviewer agent (2nd model)
   │                                                                     │ confidence < τ → ESCALATE (report, no action)
 report ◄── verify (poll health) ◄── act (Action API) ◄── approval interrupt ◄── propose (runbook allowlist only)
   │            │ not recovered → rollback + escalate        ▲ CLI y/N or Streamlit chat · dry-run · KILL switch
   └─► memory store + prevention suggestion (alert rule / config)
```

**Stack.** Everything is free, current and minimal:

| Need | Choice | Why |
|---|---|---|
| Orchestration | **LangGraph** `StateGraph` with `interrupt()` and a SQLite checkpointer | The nodes match the 7 steps one-to-one, human-in-the-loop pause/resume is native, and the graph diagram can be exported for the architecture page |
| LLM | **langchain-groq** `ChatGroq`, using `gpt-oss-120b` for investigate/diagnose, `qwen3.8-27b` for the reviewer and `gpt-oss-20b` as a cheap fallback | Each model has its own quota, and using a different model family gives the reviewer a genuinely independent opinion |
| Schemas | **Pydantic v2** (generate the models from the provided JSON schema with `datamodel-code-generator`) | Structured output that is valid against the scored schema |
| Telemetry calls | **httpx** to the Prometheus HTTP API, Jaeger `/api/traces` and OpenSearch `_search`; the `docker` CLI for container state | No SDK bloat |
| Log compression | **drain3** (log template mining) | Turns 5,000 log lines into about 10 templates with counts, which keeps us inside Groq's per-minute token limit |
| Incident memory | **fastembed** (`BAAI/bge-small-en-v1.5`, ONNX) plus numpy cosine similarity over a JSON store; Jaccard similarity if the model download fails | Local, free, fast |
| Approval UI | **Streamlit** (`st.chat_message` and buttons) | A chat UI in about 150 lines |
| Quality | **pytest**, **ruff**, and GitHub Actions CI that runs the eval on the offline bundles | The judges score "testing" |
| Environment | Python 3.11 with **uv** | Fast, reproducible installs |

**Token discipline.** This is what makes the Groq free tier viable.
1. Python does the heavy lifting deterministically before anything reaches the LLM:
   - RED-metric anomaly ranking per service, as a z-score against a 15-minute baseline
   - error spans grouped by service, operation and status
   - drain3 log templates
   - The LLM only sees summaries of at most about 1.2K tokens per tool call, and every fact carries an evidence ID.
2. A stable system prompt goes first, so Groq's cached tokens don't count against the limits.
3. The budget is at most about 20K tokens and at most 8 LLM calls per incident.
4. The rate limiter reads `retry-after` and the `x-ratelimit-*` headers and falls back down the model chain on a 429.
5. During development, LLM calls go through a record/replay cache (hash of messages → response), so re-running the eval costs nothing. The cache is **off** for the hidden test.
6. During development, each member uses their **own** Groq account key. The hidden test runs on A's laptop with a single key and the model fallback chain. No key rotation to dodge limits (that breaks Groq's terms of service).
7. If every model is rate-limited, a deterministic fallback escalates with the top anomalies as findings. The slides count escalation as a correct outcome.

**Safety, which judges score directly:**
- Default mode is `--dry-run`; live mode needs the `--live` flag.
- Every Action API call requires an approval record (who, when, the exact payload).
- The kill switch is a `KILL` file, a Streamlit toggle or Ctrl-C. It is checked before every action and inside the verify loop.
- The tool layer has a **denylist** for flagd hosts and ports (`flagd`, `:8013`, `:8016`, `/feature`). CI also greps `src/` for those strings.
- Every proposed, approved, executed, verified or rolled-back action goes to an append-only `logs/actions.jsonl`.
- The runbook is a generic **symptom → allowed action** table (restart service, toggle flag, throttle the load generator; scaling only on Kubernetes) with a reason and a rollback for each entry. It is never keyed by practice-incident ID. **Ask a mentor at kickoff** to confirm that a service→flag runbook built from public demo docs is acceptable.
- Every claim in a diagnosis must cite an evidence ID. The validator rejects IDs that don't exist or values that don't match what was recorded, and that lowers confidence. If no claim survives validation, the agent escalates.

---

## Lanes and ownership of the 12 goals (equal load)

Suggested mapping by strength: A = Vaibhav (hosts the demo). The strongest Python/LLM person takes C. The person most comfortable with UI takes D. The person most comfortable with stats/data takes E. Whoever knows infra/Linux best takes B.

| Member | Lane | Required goals | Stretch goals | Other deliverables they own |
|---|---|---|---|---|
| **A – Vaibhav** | Live Ops | **R1 Detect**, **R6 Act & verify** (with rollback and kill-switch enforcement) | – | Runs the live demo and faultctl, records live bundles for the team, hosts the hidden test, writes the README "Setup / How to run" |
| **B** | Eyes | **R2 Investigate** (metrics and traces tools, Live and Offline sources) | **S1 Incident memory**, **S5 Prevention** | Offline-bundle adapter, team form |
| **C** | Brain | **R3 Diagnose with evidence** | **S2 Reviewer agent** | LangGraph orchestration, `state.py`, prompts, architecture overview |
| **D** | Hands/Safety | **R4 Propose safe fix**, **R5 Human approval** (dry-run, approval gate); also builds the logs, container and deploy tools | **S4 Chat-style approval** (Streamlit) | Runbook, mock Action API, README "Approval gate & kill switch" |
| **E** | Quality | **R7 Report** | **S3 Calibrated confidence** | Evidence store and validator, eval harness, evaluation note, schema compliance |

That is 7 required + 5 stretch = 12 goals, each with exactly one owner.

**File ownership** prevents merge conflicts. Work on trunk and run `git pull --rebase` before every push. Only the owner edits a file. To change a shared file, message its owner.

```
src/oncall/config.py detect.py act.py ............................ A
src/oncall/sources/{live,offline}.py tools/{metrics,traces}.py memory.py prevention.py ... B
src/oncall/state.py graph.py llm.py prompts.py diagnose.py reviewer.py ... C
src/oncall/tools/{logs,containers,deploys}.py runbook.yaml propose.py approval.py mock_action_api.py ui/app.py ... D
src/oncall/evidence.py schema.py report.py calibrate.py eval/ ................ E
tests/test_<yourfile>.py ......................................... each owner
```
Adapt the paths to the organisers' **template repository**. Fork it rather than starting fresh.

**Interface contract**, frozen by **Day 1 13:30** so everyone can work in parallel:
- Tool signature: `tool(**args) -> ToolResult(summary: str, evidence: list[Evidence])`
- `Evidence(id, source, query, value, ts)`
- `Source` protocol with methods `prom_range`, `traces`, `logs`, `containers`, `deploys`
- `IncidentState` fields defined in `state.py`

---

## Timeline: one task per member per phase, all five commit every phase

### Now (setup window), before code is allowed
No code until 09:15 and the event clock. **Everyone:** create a Groq account and key, install Python 3.11, uv and git, and read the LangGraph human-in-the-loop docs and the 2-page tool-calling primer.
- **A:** let `docker compose pull` finish all 28 images.
  - If the laptop has less than 16 GB RAM, use minimal mode. Note that Kafka faults can't be reproduced then.

### Day 1 · 12:00–13:00 · Setup → Checkpoint 0 (13:00)
| A | B | C | D | E |
|---|---|---|---|---|
| Demo up with load. Inject and reset one practice incident with faultctl. Confirm the Action API answers. Commit `config.py` with live URLs (Prometheus `:9090`, Jaeger via `:8080/jaeger`, OpenSearch through `docker compose port opensearch 9200`) | Fork the template and add the 4 collaborators. Set up `uv`, ruff, pytest and a CI workflow. Commit the package skeleton by 12:15 | `llm.py`: ChatGroq model chain, 429/`retry-after` handling, record/replay cache. Smoke-test one tool call | Read the Action API contract. Commit Pydantic action models and `mock_action_api.py` so the 4 laptops without the demo can test actions | Unpack the offline bundles and the JSON output schema. Commit `schema.py` (generated) and `eval/practice.yaml` (the 10 incidents) |

### Day 1 · 13:00–15:30 · "The agent can see" → **Checkpoint 1 Eyes (10 pts)**
Ask for: a live run on one practice incident plus the architecture sketch.

| A | B | C | D | E |
|---|---|---|---|---|
| **R1** `detect.py`: poll spanmetrics error rate and p95 latency per service, plus container restarts, and emit an `Alert` | **R2** `metrics.py` (PromQL templates and RED anomaly ranking) and `traces.py` (error spans grouped, slowest operations, downstream origin of errors), each with Live and Offline sources | `state.py` (frozen 13:30) and `graph.py`: detect → investigate ReAct loop (the LLM picks the next tool, capped at 6 calls) → symptom summary. Architecture sketch | `logs.py` (OpenSearch plus drain3 templates), `containers.py` (state, restarts, OOMKilled, CPU/mem), `deploys.py` (image and start-time history). Flagd **denylist** in the HTTP client | `evidence.py` (IDs plus per-tool token budget), `eval/run.py` v0: run every offline bundle and save the outputs |

- **14:45:** everyone pushes.
- **14:45–15:30:** A pulls and does the live run on his laptop. The others fix bugs from the offline runs.

### Day 1 · 15:30–18:30 · "The agent can diagnose" → **Checkpoint 2 Brain (20 pts)**
Ask for: a correct root cause, with evidence and confidence in the JSON schema, on at least 3 mentor-chosen incidents.

| A | B | C | D | E |
|---|---|---|---|---|
| Run all 10 practice incidents live (inject → agent → reset). **Record each as a bundle** in the offline format and push them for the team. Tune detection thresholds. Start `act.py` in dry-run only | Baseline-vs-incident comparison tool; service dependency map from traces (separates the root service from propagated errors); `memory.py` store skeleton | **R3** `diagnose.py`: structured output (component, cause, confidence, cited evidence IDs) and an "unsure → escalate" branch. Tune prompts against the eval failures | **R4** `runbook.yaml` plus `propose.py` (allowlisted action, parameters, reason, rollback). **R5** `approval.py`: CLI gate requiring a typed `yes`, plus dry-run, against the mock Action API | Evidence **validator**. Eval harness accuracy table over the 10 incidents; log (stated confidence, correct?) for S3. **R7** `report.py` v1 (JSON plus Markdown) |

- **18:30–18:45 wrap-up:** push everything.
- **10-minute explain-back:** each member explains the next member's lane, in the rotation A→B→C→D→E→A.
- No commits overnight.

### Day 2 · 09:00–09:30 · Alignment
Read the mentor feedback and make a fix list. Each owner takes their own items.

### Day 2 · 09:30–12:00 · "The agent can act safely" → **Checkpoint 3 Hands (20 pts)**
Ask for: one full run from alert to verified recovery, with the action log.

| A | B | C | D | E |
|---|---|---|---|---|
| **R6** `act.py` live: execute the approved action, then a verify loop (3 checks × 30 s: error rate and p95 back to baseline, containers healthy). If not recovered: **rollback, then escalate**. Kill switch enforced. Live full-loop rehearsals | **S1** memory wired in: the top-3 similar past reports become *hints*, which must be re-verified with fresh evidence. **S5** `prevention.py`: Prometheus alert-rule YAML (parse-checked) plus a config/code suggestion | **S2** `reviewer.py`: `qwen3.8-27b` tries to disprove the diagnosis from the evidence table. On disagreement: one re-investigation, then escalate. Wire `interrupt()` and resume through the full graph | **S4** Streamlit chat UI: incident feed, diagnosis card with evidence, reviewer verdict, proposed action, **Approve / Reject / Dry-run**, a **KILL** toggle and the action-log view, resuming the graph via `Command(resume=…)` | **S3** `calibrate.py`: reliability bins, ECE/Brier, isotonic mapping to a calibrated confidence and the escalation threshold τ, plus a reliability chart for the demo. Final report includes the timeline, action log and prevention |

### Day 2 · 12:00–13:30 · Harden, document, prepare the submission
No new features.

| A | B | C | D | E |
|---|---|---|---|---|
| Clean run from scratch (fresh clone, `uv sync`, follow the README exactly) and a hidden-test readiness checklist. Write README "Setup / How to run" | Tests for the tools on bundles; **team form** (members, who built what, models: gpt-oss-120b/20b, qwen3.8-27b, plus AI coding assistants used, plus libraries) | **Architecture overview** (one page plus the LangGraph Mermaid export) | Safety tests (no action without approval, kill switch blocks, denylist enforced). Write README "Approval gate & kill switch" | **Evaluation note** (which practice incidents were right or wrong, and why). Commit practice incident reports to `reports/` |

### Day 2 · 13:30–14:00 · Final verification
- E runs schema validation on every report.
- Everyone ticks off the 5 deliverables: source plus README, architecture, incident reports, evaluation note, team form.
- Final push by **13:55**.

### 14:00–15:30 · Checkpoint 4, hidden test (30 pts), on A's laptop
- **Before:** fresh Groq quota checked, replay cache off, `--live`, laptop plugged in with other apps closed, and the demo healthy with load running.
- **During:** A operates. The rest are on standby with no commits.

### 16:30 · 5-minute demo: one minute per member, in pipeline order
1. **A:** inject an incident, show the alert firing.
2. **B:** tools and evidence, plus the memory hit.
3. **C:** diagnosis and the reviewer challenge.
4. **D:** approve live in the chat UI, with the kill switch shown.
5. **E:** verified recovery, the report, the calibration chart and prevention.

Close by stating the known limitations honestly (rule 7).

**Individual interview preparation.** Each member must be able to explain:
1. their own lane line by line,
2. the end-to-end flow,
3. their rotation partner's lane.

---

## Equal-work checklist (use at every checkpoint)
- [ ] Each member has at least 2 commits in this phase, in their own files, using conventional-commit messages.
- [ ] Each member has one demo-able piece in this phase (see the tables above).
- [ ] Each member owns 2–3 of the 12 goals, plus one deliverable section.
- [ ] Explain-back done (Day 1 18:30, Day 2 12:00).

## Risks and fallbacks
- **A's laptop is a single point of failure.** All logic is developed and tested offline on 4 laptops. The organisers have images on USB. Keep a second clone of the repo on B's laptop.
- **Groq limits.** Mitigations: compression, the model chain, the prompt-cache prefix, the dev replay cache, and deterministic escalation. Watch `x-ratelimit-remaining-tokens` and log it.
- **Unknown formats** (template, offline bundles, Action API). Each is adapted in the first hour by its owner (B, E, D).
- **Disqualification.** Mitigations: the denylist plus the CI grep check; a rule that nobody opens the flag UI while testing the agent; no faultctl or flagd calls in `src/`; no incident-ID logic.
- **Network latency or packet-loss faults** have no runbook action, so the agent escalates with evidence. The slides say this scores better than a wrong fix.

## Verification
- **Offline (every laptop):** `uv run pytest` and `uv run python -m eval.run --bundles bundles/` print an accuracy table for the 10 practice incidents, and every output validates against the provided JSON schema.
- **Live (A):** `faultctl inject <incident>`, then `uv run oncall watch --live`. The alert fires, the diagnosis appears in the Streamlit UI, approve, the action executes, verification shows recovery, and the report is written. Then `faultctl reset`.
- **Safety:** reject results in no Action API call; the `KILL` file halts mid-run; a flagd URL raises an error; dry-run prints the payload only.
- **Freeze readiness:** a fresh clone on A's laptop works by following only the README.

## After approval
Publish this plan as a private, shareable page so the team can open it on their phones, then hand each member their lane card.
