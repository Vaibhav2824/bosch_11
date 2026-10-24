import pytest
from conftest import DIAG

from incident_ui import approval


def payload():
    return approval.action_payload("runs/r1", DIAG)


def test_nothing_to_approve_when_escalated_or_none():
    assert approval.action_payload("i", {**DIAG, "decision": "escalate"}) is None
    assert approval.action_payload("i", {**DIAG, "proposed_action": {"action": "none"}}) is None


def test_approval_is_logged_and_forwarded_once():
    sent = []
    rec = approval.decide(
        "runs/r1",
        payload(),
        "approved",
        "vaibhav",
        forward=lambda d, r: sent.append(d) or {"status": "ok", "detail": ""},
    )
    assert rec["fingerprint"] == approval.fingerprint(payload())
    assert sent == ["approved"] and rec["action_api"]["status"] == "ok"
    with pytest.raises(ValueError):
        approval.decide("runs/r1", payload(), "rejected", "vaibhav")


def test_dry_run_is_never_forwarded_and_keeps_the_gate_open():
    rec = approval.decide("runs/r1", payload(), "dry_run", "vaibhav", forward=lambda d, r: 1 / 0)
    assert "action_api" not in rec
    assert approval.final_decision("runs/r1") is None


def test_kill_switch_blocks_approval_but_not_reject():
    approval.set_kill(True)
    with pytest.raises(PermissionError):
        approval.decide("runs/r1", payload(), "approved", "vaibhav")
    approval.decide("runs/r1", payload(), "rejected", "vaibhav")
    assert approval.final_decision("runs/r1")["event"] == "rejected"


def test_approver_required():
    with pytest.raises(ValueError):
        approval.decide("runs/r1", payload(), "approved", "  ")
