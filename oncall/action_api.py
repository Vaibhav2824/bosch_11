#!/usr/bin/env python3
"""
action_api.py - DEV ONLY stand-in for the organisers' Action API (like simfault.py for faultctl).

The only write path from the agent to the demo. Same four actions as the briefing:
  restart_service <service>         docker restart of that compose service
  throttle_load_generator           Locust back to N users (params.users, default 5)
  scale_service                     Kubernetes only: refused on Docker Compose
  toggle_feature_flag               refused here: flags are off limits for the team

Every call is appended to logs/action_api.jsonl. A call is refused unless it carries an
approver and the SHA-256 fingerprint of its payload (the approval UI sends both).
When the organisers' API is available, point UI_ACTION_API_URL at it and stop this.

  python action_api.py            # listens on 127.0.0.1:8090
  POST /actions  {"payload": {"action", "target", ...}, "approver", "fingerprint"}
  GET  /actions  the call log        GET /health
"""
import hashlib
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.getenv("ACTION_API_PORT", "8090"))
PROJECT = os.getenv("COMPOSE_PROJECT", "opentelemetry-demo")
LOCUST = os.getenv("LOCUST_URL", "http://localhost:8080/loadgen")
LOG = Path(os.getenv("ACTION_API_LOG", "logs/action_api.jsonl"))
NEVER_TOUCH = ("flagd", "flagd-ui")  # feature flags are off limits (Rule 6)


def fingerprint(payload: dict) -> str:  # same as incident_ui.approval.fingerprint
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _container(service: str) -> str:
    out = subprocess.run(
        ["docker", "ps", "-a", "-q",
         "--filter", f"label=com.docker.compose.project={PROJECT}",
         "--filter", f"label=com.docker.compose.service={service}"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    if not out:
        raise ValueError(f"no demo service named {service!r}")
    return out[0]


def restart_service(target: str, params: dict) -> str:
    if not target or target in NEVER_TOUCH:
        raise ValueError(f"restart_service needs a demo service, not {target!r}")
    r = subprocess.run(["docker", "restart", _container(target)], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:300])
    return f"restarted {target}"


def throttle_load_generator(target: str, params: dict) -> str:
    users = int(params.get("users", 5))  # 5 = LOCUST_USERS in the demo's .env
    data = urllib.parse.urlencode({"user_count": users, "spawn_rate": max(1, users // 5)}).encode()
    with urllib.request.urlopen(f"{LOCUST}/swarm", data=data, timeout=10) as r:
        r.read()
    return f"load generator set to {users} users"


def refuse(why: str):
    def act(target: str, params: dict) -> str:
        raise PermissionError(why)
    return act


ACTIONS = {
    "restart_service": restart_service,
    "throttle_load_generator": throttle_load_generator,
    "scale_service": refuse("scale_service is Kubernetes only; the demo runs on Docker Compose"),
    "toggle_feature_flag": refuse("toggle_feature_flag is not available in the local stand-in"),
}


def execute(body: dict) -> tuple[int, dict]:
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    action, target = str(payload.get("action", "")), str(payload.get("target", ""))
    if not str(body.get("approver", "")).strip():
        return 403, {"status": "refused", "detail": "no approver: every action needs a human approval"}
    if body.get("fingerprint") != fingerprint(payload):
        return 403, {"status": "refused", "detail": "fingerprint does not match the payload"}
    if action not in ACTIONS:
        return 400, {"status": "refused", "detail": f"action {action!r} is not in the runbook"}
    try:
        return 200, {"status": "executed", "detail": ACTIONS[action](target, payload.get("params") or {})}
    except PermissionError as e:
        return 403, {"status": "refused", "detail": str(e)}
    except ValueError as e:
        return 400, {"status": "refused", "detail": str(e)}
    except Exception as e:  # docker or Locust failed: report it, the incident stays recoverable
        return 502, {"status": "failed", "detail": f"{type(e).__name__}: {e}"[:300]}


def log(rec: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), **rec}) + "\n")


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, data) -> None:
        raw = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/health":
            return self._json(200, {"ok": True})
        if self.path == "/actions":
            rows = LOG.read_text(encoding="utf-8").splitlines() if LOG.exists() else []
            return self._json(200, [json.loads(x) for x in rows if x.strip()])
        self._json(404, {"error": "no route"})

    def do_POST(self):
        if self.path != "/actions":
            return self._json(404, {"error": "no route"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"status": "refused", "detail": "invalid JSON"})
        code, res = execute(body if isinstance(body, dict) else {})
        log({"request": body, "code": code, **res})
        print(f"{code} {res['status']}: {res['detail']}", flush=True)
        self._json(code, res)


if __name__ == "__main__":
    print(f"Action API (local stand-in) on http://127.0.0.1:{PORT}/actions, log: {LOG}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
