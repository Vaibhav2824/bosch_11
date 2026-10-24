<<<<<<< HEAD
# On-call agent (Eyes + Brain)

Alert in, evidence-backed diagnosis out. Read-only: it never changes the system and never reads feature flags.

## Setup (Python 3.11)
    pip install -r requirements.txt
    export OPENAI_API_KEY=...            # or ANTHROPIC_API_KEY / GEMINI_API_KEY
    export AGENT_MODEL=gpt-4o-mini       # any litellm model string

Defaults assume `make start-minimal`: Prometheus on :9090, Jaeger at :8080/jaeger/ui,
OpenSearch port auto-detected through Docker. Override with PROM_URL, JAEGER_URL, OPENSEARCH_URL.

## Practice incident, one command
    ./incident.sh stop valkey-cart        # check, inject, wait 90s, diagnose, reset

## Use
    python -m oncall_agent check                            # all UIs and backends up?
    python -m oncall_agent baseline                         # once, while healthy
    python -m oncall_agent tool service_overview            # check each tool by hand
    python -m oncall_agent tool get_traces '{"service":"frontend"}'
    python -m oncall_agent tool search_logs
    python -m oncall_agent tool container_health
    python -m oncall_agent run "error rate up on checkout"  # full investigation

Each run writes runs/<time>/ with diagnosis.json, report.md, evidence.jsonl and transcript.jsonl.

## How it decides
- Tools: service_overview (Prometheus spanmetrics vs baseline), service_detail, get_traces
  (Jaeger, finds the deepest failing span = error origin, or biggest self time for latency),
  search_logs (OpenSearch otel-logs-*), container_health (Docker state, restarts, OOM, CPU limit).
- The LLM chooses each next tool from what it has seen. Budget: AGENT_MAX_STEPS (12).
- Every tool result gets an evidence ID. submit_diagnosis is rejected unless each cited quote
  really appears in the cited evidence, so evidence cannot be invented.
- Confidence is capped by independent sources (1 source 0.6, 2 sources 0.8, 3+ 0.95).
  Below AGENT_ESCALATE_BELOW (0.55) it escalates to a human with its findings.

## Known limitations
- schema.py is a placeholder until we have the organisers' JSON schema.
- Locust's ask_agent task fails in minimal mode (no agent service); load-generator is ignored.
- Kafka path (accounting, fraud-detection) is not running in minimal mode.
=======
# Incident Zero (BOSCH team 11)

AI on-call engineer for the OpenTelemetry Astronomy Shop: detect, investigate, diagnose,
propose, get approval, act and verify, report.

## Dev setup

```bash
uv sync
cp .env.example .env   # add your own GROQ_API_KEY
uv run ruff check . && uv run ruff format --check .
uv run pytest
```

Code lives in `src/oncall/`. Each file has one owner (see the docstring at its top);
message the owner before editing someone else's file. `git pull --rebase` before every push.

Sections still to write: Setup / How to run (A), Approval gate and kill switch (D),
known limitations.
>>>>>>> 2ef832121fd19b481206d6bf4ba94813fed9329d
