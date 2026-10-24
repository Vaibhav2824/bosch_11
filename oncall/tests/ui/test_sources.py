import importlib

import pytest

from incident_ui import config, demo_stack
from incident_ui.sources import RunsSource, normalize

# Shaped like the hackathon plan's data model (Incident / Hypothesis / Evidence / ActionProposal),
# with different field names from oncall_agent: the mapper has to cope with both.
PLAN_STYLE = {
    "id": "inc-7",
    "state": "AWAITING_APPROVAL",
    "alert": {"raw": "checkout p95 above 2s", "received_at": "2026-10-23T15:00:00"},
    "hypothesis": {
        "root_cause": "payment gateway calls hang",
        "affected_component": "payment",
        "confidence": 0.7,
        "supporting_evidence": [
            {
                "id": "e1",
                "tool_name": "jaeger.search",
                "kind": "trace",
                "query": {"service": "checkout"},
                "result_summary": "payment span 4.1s self time",
                "deep_link": "http://localhost:8080/jaeger/ui/trace/abc",
            },
            {
                "id": "e2",
                "tool_name": "prom.query",
                "kind": "metric",
                "query": {"service": "payment"},
                "result_summary": "p95 4.2s vs 0.3s baseline",
            },
        ],
    },
    "action_proposal": {
        "action_id": "restart_service",
        "service": "payment",
        "explanation": "clears hung connections",
        "rollback_plan": "escalate",
    },
}


def test_plan_style_incident_is_understood():
    d = normalize(PLAN_STYLE, "inc-7")
    dx = d["diagnosis"]
    assert d["state"] == "AWAITING_APPROVAL"
    assert dx["decision"] == "diagnosed" and dx["alert"] == "checkout p95 above 2s"
    assert dx["root_cause"] == {"component": "payment", "cause": "payment gateway calls hang"}
    assert dx["proposed_action"]["action"] == "restart_service"
    assert dx["proposed_action"]["target"] == "payment"
    assert dx["proposed_action"]["rollback"] == "escalate"
    assert [e["source"] for e in d["evidence"]] == ["traces", "metrics"]
    assert [c["evidence_id"] for c in dx["evidence"]] == ["e1", "e2"]
    assert dx["evidence"][0]["quote"] == "payment span 4.1s self time"
    assert d["evidence"][0]["link"]["url"].endswith("/trace/abc")
    assert [e["kind"] for e in d["transcript"]] == ["alert", "tool", "tool"]


def test_escalated_state_without_root_cause():
    d = normalize({"state": "ESCALATED", "hypothesis": {"confidence": 0.2}}, "x")
    assert d["diagnosis"]["decision"] == "escalate"
    assert d["diagnosis"]["proposed_action"] is None


def test_runs_folder_round_trip(isolated):
    d = RunsSource().get(isolated)
    assert d["diagnosis"]["root_cause"]["component"] == "cart"
    assert d["evidence"][0]["source"] == "containers"
    assert d["diagnosis"]["evidence"][0]["source"] == "containers"


def test_trace_links_use_the_trace_id_when_present():
    item = {"source": "traces", "args": {"service": "checkout"}}
    link = demo_stack.evidence_link(item, {"error_origins": [{"example_trace_id": "9d30"}]})
    assert link["url"] == f"{config.DEMO['Jaeger']}/trace/9d30"
    assert "service=checkout" in demo_stack.evidence_link(item, {})["url"]


def test_feature_flag_links_are_dropped():
    raw = {
        **PLAN_STYLE,
        "hypothesis": {
            **PLAN_STYLE["hypothesis"],
            "supporting_evidence": [
                {"id": "e1", "tool_name": "x", "deep_link": "http://localhost:8080/feature/"}
            ],
        },
    }
    assert normalize(raw, "inc-7")["evidence"][0]["link"] is None


@pytest.mark.parametrize("url", ["http://flagd:8013", "http://localhost:8080/feature"])
def test_feature_flag_demo_urls_are_refused(monkeypatch, url):
    monkeypatch.setitem(config.DEMO, "Shop", url)
    with pytest.raises(ValueError, match="feature flags"):
        importlib.reload(demo_stack)
    monkeypatch.undo()
    importlib.reload(demo_stack)
