import json

import pytest

from incident_ui import config

DIAG = {
    "decision": "diagnosed",
    "alert": "cart down",
    "summary": "carts fail",
    "root_cause": {"component": "cart", "cause": "container exited"},
    "confidence": 0.8,
    "evidence": [{"evidence_id": "ev_1", "quote": "exited", "why": "cart is down"}],
    "proposed_action": {"action": "restart_service", "target": "cart", "reason": "down"},
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Every test gets its own log, KILL file and runs folder with one incident (runs/r1)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "ACTION_LOG", tmp_path / "logs" / "actions.jsonl")
    monkeypatch.setattr(config, "KILL_FILE", tmp_path / "KILL")
    monkeypatch.setattr(config, "SOURCE", "runs")
    monkeypatch.setattr(config, "RUN_DIRS", ["runs"])
    monkeypatch.setattr(config, "ACTION_API_URL", "")  # tests never touch the demo
    run = tmp_path / "runs" / "r1"
    run.mkdir(parents=True)
    (run / "diagnosis.json").write_text(json.dumps(DIAG))
    (run / "evidence.jsonl").write_text(
        json.dumps(
            {
                "id": "ev_1",
                "tool": "container_health",
                "args": {"service": "cart"},
                "time": "2026-10-23T15:00:01",
                "result": {"status": "exited"},
            }
        )
        + "\n"
    )
    return "runs/r1"
