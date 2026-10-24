import pytest

from incident_ui import server
from incident_ui.sources import RunsSource


def test_unknown_or_traversal_ids_are_refused():
    for bad in ("runs/nope", "../etc", "runs/r1/../../x"):
        with pytest.raises(LookupError):
            server.known(RunsSource(), bad)


def test_decide_uses_server_side_payload(isolated):
    rec = server.handle_post(
        RunsSource(),
        "/api/decide",
        {"id": isolated, "decision": "approved", "approver": "v", "payload": {"action": "evil"}},
    )
    assert rec["payload"]["action"] == "restart_service"
    assert rec["action_api"]["status"] == "not_connected"


def test_kill_endpoint_blocks_approval(isolated):
    server.handle_post(RunsSource(), "/api/kill", {"on": True})
    with pytest.raises(PermissionError):
        server.handle_post(
            RunsSource(), "/api/decide", {"id": isolated, "decision": "approved", "approver": "v"}
        )
    assert server.handle_post(RunsSource(), "/api/kill", {"on": False}) == {"kill": False}


def test_state_lists_the_incident(isolated):
    state = server.handle_get(RunsSource(), "/api/state", {})
    assert [i["id"] for i in state["incidents"]] == [isolated]
    assert state["incidents"][0]["decision"] == "diagnosed"
