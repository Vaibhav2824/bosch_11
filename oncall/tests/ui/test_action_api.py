import action_api
from incident_ui import approval, config

PAYLOAD = {"incident": "runs/r1", "action": "restart_service", "target": "cart", "reason": "down"}


def body(**kw):
    return {"payload": PAYLOAD, "approver": "vaibhav", "fingerprint": approval.fingerprint(PAYLOAD), **kw}


def test_action_api_refuses_without_approval_or_with_a_changed_payload():
    assert action_api.execute(body(approver=""))[0] == 403
    changed = {**PAYLOAD, "target": "payment"}
    assert action_api.execute(body(payload=changed))[0] == 403  # fingerprint was for cart


def test_action_api_refuses_flags_and_unknown_actions(monkeypatch):
    for action, target in [("restart_service", "flagd"), ("toggle_feature_flag", "x"), ("rm -rf", "")]:
        p = {**PAYLOAD, "action": action, "target": target}
        code, res = action_api.execute(body(payload=p, fingerprint=approval.fingerprint(p)))
        assert code in (400, 403) and res["status"] == "refused"


def test_action_api_runs_an_approved_restart(monkeypatch):
    ran = []
    monkeypatch.setitem(action_api.ACTIONS, "restart_service", lambda t, p: ran.append(t) or "ok")
    assert action_api.execute(body()) == (200, {"status": "executed", "detail": "ok"})
    assert ran == ["cart"]


def test_unreachable_action_api_is_reported_not_verified(monkeypatch):
    monkeypatch.setattr(config, "ACTION_API_URL", "http://127.0.0.1:9/actions")
    rec = {"incident": "runs/r1", "approver": "v", "payload": PAYLOAD, "fingerprint": "f"}
    assert approval.send_to_action_api(rec)["status"] == "unreachable"
    assert approval.verification("runs/r1") is None


def test_no_recovery_within_timeout_is_unconfirmed(monkeypatch):
    monkeypatch.setattr(config, "VERIFY_TIMEOUT_S", 0)
    monkeypatch.setattr(
        approval, "recovery_checks", lambda p: [{"check": "errors", "ok": False, "value": "9%"}]
    )
    assert approval.verify("runs/r1", PAYLOAD)["event"] == "recovery_unconfirmed"
    assert approval.verification("runs/r1")["event"] == "recovery_unconfirmed"
    assert approval.final_decision("runs/r1") is None  # verification never closes the gate


def test_action_api_refuses_everything_while_kill_switch_is_on(monkeypatch, tmp_path):
    kill = tmp_path / "KILL"
    kill.write_text("on")
    monkeypatch.setattr(action_api, "KILL_FILE", kill)
    code, res = action_api.execute(body())
    assert code == 423 and res["status"] == "refused"
