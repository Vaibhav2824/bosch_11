"""The approval gate. Every decision is appended to the action log; KILL blocks approvals.

Nothing here changes the demo itself. An approval is handed to `forward` (the source's hook):
in "runs" mode that is send_to_action_api() below, in "http" mode the agent's own decide endpoint.
"""

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable

from . import config

DECISIONS = ("approved", "rejected", "dry_run")
VERIFY_EVENTS = ("verifying", "verified", "recovery_unconfirmed")
_log_lock = threading.Lock()


def send_to_action_api(rec: dict) -> dict:
    """The only write path to the demo in "runs" mode: POST the approved request, then verify."""
    if not config.ACTION_API_URL:
        return {"status": "not_connected", "detail": "UI_ACTION_API_URL is empty; approval recorded only"}
    body = {k: rec[k] for k in ("incident", "approver", "payload", "fingerprint")}
    req = urllib.request.Request(
        config.ACTION_API_URL,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:  # refused or failed: report it, never verify
        try:
            res = json.loads(e.read() or b"{}")
        except json.JSONDecodeError:
            res = {}
        return {"status": str(res.get("status", "failed")), "detail": str(res.get("detail", e))[:300]}
    except OSError as e:
        return {"status": "unreachable", "detail": f"Action API at {config.ACTION_API_URL}: {e}"}
    res = res if isinstance(res, dict) else {}
    threading.Thread(target=verify, args=(rec["incident"], rec["payload"]), daemon=True).start()
    return {"status": str(res.get("status", "executed")), "detail": str(res.get("detail", ""))[:300]}


def recovery_checks(payload: dict) -> list[dict]:
    """Fresh telemetry from the agent's own read-only tools, not the Action API's reply."""
    from oncall_agent import tools

    checks = []
    if payload.get("action") == "restart_service":
        rows = tools.container_health(payload.get("target", "")).get("containers", [])
        c = rows[0] if rows else {}
        checks.append({
            "check": f"{payload.get('target')} container running and healthy",
            "ok": c.get("status") == "running" and c.get("health") in (None, "healthy"),
            "value": f"{c.get('status')}, health {c.get('health')}",
        })
    stats = tools._service_stats(window="2m")
    worst, s = max(stats.items(), key=lambda kv: kv[1]["error_pct"] or 0, default=("none", {}))
    pct = s.get("error_pct") or 0
    checks.append({
        "check": f"error rate below {config.VERIFY_MAX_ERROR_PCT}% on every service (last 2m)",
        "ok": bool(stats) and pct < config.VERIFY_MAX_ERROR_PCT,
        "value": f"highest: {worst} {pct}%" if stats else "no metrics from Prometheus",
    })
    return checks


def verify(incident: str, payload: dict) -> dict:
    """Poll until recovered or VERIFY_TIMEOUT_S; unconfirmed recovery goes back to a human."""
    _append({"incident": incident, "event": "verifying", "detail": "checking fresh telemetry"})
    deadline = time.monotonic() + config.VERIFY_TIMEOUT_S
    started = time.monotonic()
    while True:
        try:
            checks = recovery_checks(payload)
        except Exception as e:  # Prometheus or Docker down: keep trying until the deadline
            checks = [{"check": "telemetry readable", "ok": False, "value": f"{type(e).__name__}: {e}"}]
        if all(c["ok"] for c in checks) or time.monotonic() > deadline:
            break
        time.sleep(config.VERIFY_POLL_S)
    ok = all(c["ok"] for c in checks)
    took = round(time.monotonic() - started)
    return _append({
        "incident": incident,
        "event": "verified" if ok else "recovery_unconfirmed",
        "checks": checks,
        "detail": f"recovered after {took}s" if ok
        else f"not recovered within {took}s; escalate to a human (consider rollback)",
    })


def verification(incident: str) -> dict | None:
    rows = [r for r in read_log(incident) if r["event"] in VERIFY_EVENTS]
    return rows[-1] if rows else None


def fingerprint(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def action_payload(incident: str, diag: dict) -> dict | None:
    """The exact request a human approves, or None when there is nothing to approve."""
    a = diag.get("proposed_action") or {}
    if diag.get("decision") != "diagnosed" or a.get("action", "none") in ("none", ""):
        return None
    return {
        "incident": incident,
        "action": a["action"],
        "target": a.get("target", ""),
        "reason": a.get("reason", ""),
    }


def read_log(incident: str | None = None) -> list[dict]:
    if not config.ACTION_LOG.exists():
        return []
    rows = [json.loads(x) for x in config.ACTION_LOG.read_text().splitlines() if x.strip()]
    return [r for r in rows if incident is None or r.get("incident") == incident]


def _append(rec: dict) -> dict:
    config.ACTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), **rec}
    with _log_lock, config.ACTION_LOG.open("a") as f:  # verify() writes from its own thread
        f.write(json.dumps(rec) + "\n")
    return rec


def final_decision(incident: str) -> dict | None:
    """Approve or reject closes the gate; dry runs do not."""
    done = [r for r in read_log(incident) if r["event"] in ("approved", "rejected")]
    return done[-1] if done else None


def kill_on() -> bool:
    return config.KILL_FILE.exists()


def set_kill(on: bool) -> bool:
    if on:
        config.KILL_FILE.write_text("set from approval UI\n")
    elif config.KILL_FILE.exists():
        config.KILL_FILE.unlink()
    return kill_on()


def decide(
    incident: str,
    payload: dict,
    decision: str,
    approver: str,
    note: str = "",
    forward: Callable[[str, dict], dict] | None = None,
) -> dict:
    """Record a decision. Approve/reject are forwarded; dry runs never are; KILL blocks approve."""
    if decision not in DECISIONS:
        raise ValueError(f"unknown decision {decision!r}")
    if not approver.strip():
        raise ValueError("approver name is required")
    if decision == "approved" and kill_on():
        raise PermissionError("kill switch is on; no action may run")
    if decision != "dry_run" and final_decision(incident):
        raise ValueError("this incident was already decided")
    rec = {
        "incident": incident,
        "event": decision,
        "approver": approver.strip(),
        "payload": payload,
        "fingerprint": fingerprint(payload),
        "note": note,
    }
    if decision != "dry_run" and forward and (result := forward(decision, {**rec})):
        rec["action_api"] = result
    return _append(rec)
