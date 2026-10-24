"""Every knob in one place, read from environment variables. See .env.example."""

import os
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in _env(name, default).split(",") if x.strip()]


# --- UI server -------------------------------------------------------------------------
PORT = int(_env("UI_PORT", "8502"))
HOST = "127.0.0.1"  # local only, on purpose
WEB_DIST = Path(_env("UI_WEB_DIST", str(Path(__file__).resolve().parent.parent / "web" / "dist")))
ACTION_LOG = Path(_env("UI_ACTION_LOG", "logs/actions.jsonl"))
KILL_FILE = Path(_env("UI_KILL_FILE", "KILL"))

# --- Where incidents come from: "runs" (agent output folders) or "http" (agent API) -------
SOURCE = _env("UI_SOURCE", "runs")

# runs: folders that each contain diagnosis.json (+ transcript.jsonl, evidence.jsonl, report.md)
RUN_DIRS = _list("UI_RUN_DIRS", "runs,reports")
# Function the UI calls to start an investigation, "module:function", taking the alert text and
# returning the new run folder (str) or a dict with "run_dir". "none" disables the alert box.
INVESTIGATE = _env("UI_INVESTIGATE", "oncall_agent.agent:investigate")
if INVESTIGATE.lower() in ("none", "off"):
    INVESTIGATE = ""
AGENT_ROOT = _env("UI_AGENT_ROOT", ".")  # put on sys.path so INVESTIGATE can be imported

# http: the agent's own API. {id} and {decision} are filled in. Empty DECIDE = record locally only.
AGENT_API_URL = _env("UI_AGENT_API_URL", "http://127.0.0.1:8000").rstrip("/")
AGENT_API_LIST = _env("UI_AGENT_API_LIST", "/incidents")
AGENT_API_GET = _env("UI_AGENT_API_GET", "/incidents/{id}")
AGENT_API_CREATE = _env("UI_AGENT_API_CREATE", "/incidents")
AGENT_API_DECIDE = _env("UI_AGENT_API_DECIDE", "")
AGENT_API_TIMEOUT = float(_env("UI_AGENT_API_TIMEOUT", "600"))

# runs: where approved actions go (action_api.py stand-in by default). Empty = record only.
ACTION_API_URL = _env("UI_ACTION_API_URL", "http://127.0.0.1:8090/actions")
VERIFY_TIMEOUT_S = float(_env("UI_VERIFY_TIMEOUT", "360"))  # frontend gRPC backoff alone is ~2 min
VERIFY_POLL_S = float(_env("UI_VERIFY_POLL", "10"))
VERIFY_MAX_ERROR_PCT = float(_env("UI_VERIFY_MAX_ERROR_PCT", "2"))

# --- OpenTelemetry demo (Astronomy Shop), defaults match `make start` / `make start-minimal` ---
DEMO = {
    "Shop": _env("DEMO_SHOP_URL", "http://localhost:8080"),
    "Jaeger": _env("DEMO_JAEGER_URL", "http://localhost:8080/jaeger/ui"),
    "Grafana": _env("DEMO_GRAFANA_URL", "http://localhost:8080/grafana"),
    "Prometheus": _env("DEMO_PROMETHEUS_URL", "http://localhost:9090"),
    "Load generator": _env("DEMO_LOADGEN_URL", "http://localhost:8080/loadgen"),
}
# Health check path per service (appended to the URL above).
DEMO_HEALTH = {
    "Shop": "/",
    "Jaeger": "/api/v3/services",  # Jaeger v2 API
    "Grafana": "/api/health",
    "Prometheus": "/-/ready",
    "Load generator": "/",
}

# Reading feature-flag settings is a disqualification: these must never be called or linked.
FORBIDDEN_URL_PARTS = ("flagd", ":8013", ":8016", ":4000", "/feature")
