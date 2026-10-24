"""Readable incident report (report.md) built from diagnosis.json + evidence. JSON stays the source of truth."""
import json


def _log_groups(evidence_items):
    groups = []
    for it in evidence_items:
        if it["tool"] == "search_logs" and isinstance(it["result"], dict):
            for g in it["result"].get("message_groups", [])[:5]:
                groups.append((it["id"], g))
    return groups


def build_report(diag: dict, evidence_items: list) -> str:
    rc = diag.get("root_cause") or {}
    out = [
        f"# Incident report: {diag.get('alert', '')}",
        "",
        f"**Decision:** {diag['decision']}  ",
        f"**Confidence:** {diag.get('confidence')} ({diag.get('calibration_note', '')})  ",
        f"**Summary:** {diag.get('summary', '')}",
        "",
        "## Root cause",
        f"**{rc.get('component', 'unknown')}**: {rc.get('cause', 'not determined, escalated to on-call human')}",
        "",
        "## Evidence",
    ]
    for ev in diag.get("evidence", []):
        out.append(f"- `{ev['evidence_id']}` ({ev.get('source')}): \"{ev['quote']}\". {ev['why']}")
    if not diag.get("evidence"):
        out.append("- none accepted")

    logs = _log_groups(evidence_items)
    if logs:
        out += ["", "## Log excerpts"]
        for eid, g in logs:
            out.append(f"- `{eid}` {g['service']} [{g.get('severity')}] x{g['count']}: {g['example'][:200]}")

    if diag.get("alternatives_ruled_out"):
        out += ["", "## Ruled out"] + [f"- {a}" for a in diag["alternatives_ruled_out"]]

    a = diag.get("proposed_action")
    out += ["", "## Proposed action (needs human approval)"]
    out.append(f"- {a['action']} {a.get('target', '')}: {a.get('reason', '')}" if a else "- none")

    if diag.get("open_questions"):
        out += ["", "## Open questions"] + [f"- {q}" for q in diag["open_questions"]]

    out += ["", "## Investigation timeline"]
    for it in evidence_items:
        out.append(f"- {it['time']} `{it['id']}` {it['tool']} {json.dumps(it['args'])}")
    for t in diag.get("timeline", []):
        out.append(f"- {t['time']} {t['event']}")
    return "\n".join(out) + "\n"
