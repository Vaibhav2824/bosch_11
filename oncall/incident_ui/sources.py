"""Where incidents come from. Pick one with UI_SOURCE; both return the same normalized shape.

  runs  agent output folders (diagnosis.json, transcript.jsonl, evidence.jsonl, report.md)
  http  the agent's own HTTP API (defaults follow the plan's /incidents endpoints)

If the agent's JSON uses other field names, add them to the alias lists in normalize().
That function is the one place that has to know the agent's format.
"""

import importlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from . import approval, config, demo_stack

# ----------------------------------------------------------------------------- mapping


def _pick(d: dict, *names, default=None):
    """First present, non-empty field among several possible names (supports a.b paths)."""
    for name in names:
        v = d
        for part in name.split("."):
            v = v.get(part) if isinstance(v, dict) else None
        if v not in (None, "", [], {}):
            return v
    return default


TOOL_SOURCE = {
    "service_overview": "metrics",
    "service_detail": "metrics",
    "get_traces": "traces",
    "search_logs": "logs",
    "container_health": "containers",
}


def _source_of(item: dict) -> str:
    s = _pick(item, "source", "kind", "type")
    if s:
        s = str(s).lower()
        for known in ("metrics", "traces", "logs", "containers", "deploy"):
            if known.rstrip("s") in s:
                return known
        return s
    return TOOL_SOURCE.get(str(_pick(item, "tool", "tool_name", "name", default="")), "other")


def _evidence_item(item: dict, i: int) -> dict:
    result = _pick(item, "result", "output", "data", "result_summary", "summary", default={})
    return {
        "id": str(_pick(item, "id", "evidence_id", default=f"ev_{i + 1}")),
        "tool": str(_pick(item, "tool", "tool_name", "name", default="tool")),
        "source": _source_of(item),
        "args": _pick(item, "args", "arguments", "query", "params", default={}),
        "time": str(_pick(item, "time", "timestamp", "source_timestamp", "created_at", default="")),
        "error": bool(_pick(item, "error", "failed"))
        or (isinstance(result, dict) and "error" in result),
        "result": result,
        "description": _pick(item, "description", "relevance", "summary"),
        "link": _pick(item, "link", "deep_link", "url"),
    }


def _citation(c: dict | str, i: int) -> dict:
    if isinstance(c, str):  # a bare evidence id
        return {"evidence_id": c, "quote": c, "why": ""}
    return {
        "evidence_id": str(_pick(c, "evidence_id", "id", "ref", default=f"ev_{i + 1}")),
        "quote": str(
            _pick(c, "quote", "excerpt", "value", "result_summary", "summary", default="")
        ),
        "why": str(_pick(c, "why", "relevance", "explanation", "reason", default="")),
        "source": _pick(c, "source"),
    }


def _ui_evidence(e: dict) -> dict:
    """Full result -> short preview, plus a link into Jaeger/Grafana built from the full result."""
    result = e["result"]
    link = e["link"]
    link = {"label": "Open source", "url": link} if isinstance(link, str) else link
    if link and any(p in str(link.get("url", "")).lower() for p in config.FORBIDDEN_URL_PARTS):
        link = None  # never offer a way into the feature-flag settings
    rest = {k: v for k, v in e.items() if k not in ("result", "link")}
    return {
        **rest,
        "link": link or demo_stack.evidence_link(e, result),
        "preview": json.dumps(result, default=str, indent=1)[:1500],
    }


def normalize(raw: dict, incident_id: str) -> dict:
    """Turn the agent's incident JSON, in any of the shapes we know, into what the UI shows."""
    diag = _pick(raw, "diagnosis", "hypothesis", "result", default=raw)
    state = str(_pick(raw, "state", "status", default="")).upper() or None

    rc = _pick(diag, "root_cause", "rootCause")
    if isinstance(rc, str):
        rc = {
            "component": _pick(diag, "affected_component", "component", default="unknown"),
            "cause": rc,
        }
    elif isinstance(rc, dict):
        rc = {
            "component": _pick(rc, "component", "service", default="unknown"),
            "cause": _pick(rc, "cause", "description", "summary", default=""),
        }

    decision = _pick(diag, "decision")
    if decision not in ("diagnosed", "escalate"):
        decision = "escalate" if (state and "ESCALAT" in state) or not rc else "diagnosed"

    act = _pick(
        raw,
        "proposed_action",
        "action_proposal",
        "proposal",
        "diagnosis.proposed_action",
        "hypothesis.proposed_action",
    )
    if isinstance(act, dict):
        act = {
            "action": str(_pick(act, "action", "action_id", "name", "type", default="none")),
            "target": str(
                _pick(act, "target", "service", "component", "params.service", default="")
            ),
            "reason": str(_pick(act, "reason", "explanation", "why", default="")),
            "rollback": _pick(act, "rollback", "rollback_plan", "escalation"),
        }

    items = [
        x
        for x in _pick(raw, "evidence_items", "tool_results", "observations", default=[])
        if isinstance(x, dict)
    ]
    cites = _pick(diag, "evidence", "supporting_evidence", "citations", default=[])
    if not items and cites and isinstance(cites[0], dict) and _pick(cites[0], "tool", "tool_name"):
        items, cites = (
            cites,
            [{"evidence_id": _pick(c, "id", default=f"ev_{i + 1}")} for i, c in enumerate(cites)],
        )  # plan style: one Evidence list doing both jobs
    evidence = [_evidence_item(x, i) for i, x in enumerate(items)]
    citations = [_citation(c, i) for i, c in enumerate(cites)]
    by_id = {e["id"]: e for e in evidence}
    for c in citations:  # fill quote/source from the evidence it points at
        ev = by_id.get(c["evidence_id"])
        c["source"] = c.get("source") or (ev["source"] if ev else None)
        if ev and (not c["quote"] or c["quote"] == c["evidence_id"]):
            r = ev["result"]
            text = ev["description"] or (r if isinstance(r, str) else json.dumps(r, default=str))
            c["quote"] = str(text)[:300]

    alert = _pick(raw, "alert.raw", "alert.symptom", "alert.message", "alert", "title", default="")
    transcript = _pick(raw, "transcript", "events", "timeline", default=None)
    if not (
        isinstance(transcript, list)
        and transcript
        and isinstance(transcript[0], dict)
        and "kind" in transcript[0]
    ):
        start = str(_pick(raw, "alert.received_at", "created_at", "received_at", default=""))[-8:]
        transcript = [
            {"t": start, "kind": "alert", "alert": alert, "model": _pick(raw, "model", "llm_model")}
        ]
        transcript += [
            {
                "t": e["time"][-8:],
                "kind": "tool",
                "name": e["tool"],
                "args": e["args"],
                "evidence_id": e["id"],
                "description": e["description"],
            }
            for e in evidence
        ]

    conf = _pick(diag, "confidence", default=0)
    return {
        "id": incident_id,
        "state": state,
        "diagnosis": {
            "decision": decision,
            "alert": str(alert),
            "summary": str(_pick(diag, "summary", "impact", "explanation", default="")),
            "root_cause": rc,
            "confidence": float(conf) if isinstance(conf, (int, float)) else 0.0,
            "confidence_model": _pick(diag, "confidence_model"),
            "calibration_note": _pick(diag, "calibration_note", "confidence_note"),
            "evidence_sources": _pick(
                diag,
                "evidence_sources",
                default=sorted({c["source"] for c in citations if c["source"]}),
            ),
            "evidence": citations,
            "alternatives_ruled_out": _pick(
                diag, "alternatives_ruled_out", "alternatives", "ruled_out", default=[]
            ),
            "open_questions": _pick(diag, "open_questions", "unknowns", "uncertainty", default=[]),
            "proposed_action": act if isinstance(act, dict) else None,
        },
        "transcript": transcript,
        "evidence": [_ui_evidence(e) for e in evidence],
        "report": _pick(raw, "report_markdown", "report", "report_md"),
    }


# ----------------------------------------------------------------------------- sources


class RunsSource:
    """Agent output folders, as oncall_agent writes them."""

    def list(self) -> list[str]:
        found = [
            p.parent.as_posix() for d in config.RUN_DIRS for p in Path(d).glob("*/diagnosis.json")
        ]
        return sorted(found, key=lambda p: Path(p, "diagnosis.json").stat().st_mtime, reverse=True)

    def get(self, incident: str) -> dict:
        run = Path(incident)
        raw = json.loads((run / "diagnosis.json").read_text())

        def read(name: str) -> list[dict]:
            f = run / name
            return (
                [json.loads(x) for x in f.read_text().splitlines() if x.strip()]
                if f.exists()
                else []
            )

        raw = {
            "diagnosis": raw,
            "alert": raw.get("alert", ""),
            "proposed_action": raw.get("proposed_action"),
            "transcript": read("transcript.jsonl"),
            "evidence_items": read("evidence.jsonl"),
            "report": (run / "report.md").read_text() if (run / "report.md").exists() else None,
        }
        return normalize(raw, incident)

    def investigate(self, alert: str) -> str:
        if not config.INVESTIGATE:
            raise ValueError("starting investigations is disabled (UI_INVESTIGATE is empty)")
        sys.path.insert(0, str(Path(config.AGENT_ROOT).resolve()))
        module, _, fn = config.INVESTIGATE.partition(":")
        out = getattr(importlib.import_module(module), fn)(alert)
        run_dir = out.get("run_dir") if isinstance(out, dict) else out
        return Path(run_dir).as_posix()

    def forward(self, decision: str, rec: dict) -> dict | None:
        return approval.send_to_action_api(rec) if decision == "approved" else None


class HttpSource:
    """The agent's own API. Endpoints are configurable (UI_AGENT_API_*)."""

    def _call(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(
            config.AGENT_API_URL + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=config.AGENT_API_TIMEOUT) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"agent API {method} {path}: HTTP {e.code} {e.read()[:300]!r}"
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"agent API not reachable at {config.AGENT_API_URL}: {e.reason}"
            ) from e

    @staticmethod
    def _id(x) -> str:
        return str(_pick(x, "id", "incident_id", default=x) if isinstance(x, dict) else x)

    def list(self) -> list[str]:
        data = self._call("GET", config.AGENT_API_LIST)
        rows = (
            _pick(data, "incidents", "items", "data", default=data)
            if isinstance(data, dict)
            else data
        )
        return [self._id(x) for x in rows or []]

    def get(self, incident: str) -> dict:
        return normalize(self._call("GET", config.AGENT_API_GET.format(id=incident)), incident)

    def investigate(self, alert: str) -> str:
        return self._id(self._call("POST", config.AGENT_API_CREATE, {"alert": alert}))

    def forward(self, decision: str, rec: dict) -> dict | None:
        if not config.AGENT_API_DECIDE:
            return {
                "status": "recorded_locally",
                "detail": "UI_AGENT_API_DECIDE is not set, so the agent was not told",
            }
        verb = {"approved": "approve", "rejected": "reject"}[decision]
        path = config.AGENT_API_DECIDE.format(id=rec["incident"], decision=verb)
        res = self._call(
            "POST", path, {k: rec[k] for k in ("approver", "payload", "fingerprint", "note")}
        )
        status = _pick(res, "status", "state", default="sent") if isinstance(res, dict) else "sent"
        return {"status": str(status), "detail": json.dumps(res, default=str)[:300]}


def get_source():
    if config.SOURCE == "runs":
        return RunsSource()
    if config.SOURCE == "http":
        return HttpSource()
    raise ValueError(f"UI_SOURCE must be 'runs' or 'http', not {config.SOURCE!r}")
