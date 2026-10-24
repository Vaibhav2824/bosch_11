import pytest
from pydantic import ValidationError

from oncall.schema import Diagnosis


def test_escalation_without_root_cause_is_valid():
    result = Diagnosis(
        decision="escalate",
        summary="Independent evidence is insufficient.",
        confidence=0.4,
        open_questions=["Need a trace sample."],
    )
    assert result.root_cause is None


def test_diagnosis_fixture_shape_is_valid():
    result = Diagnosis.model_validate(
        {
            "decision": "diagnosed",
            "summary": "Checkout requests are failing.",
            "root_cause": {
                "component": "checkout",
                "cause": "The checkout dependency is returning errors.",
            },
            "confidence": 0.8,
            "evidence": [
                {
                    "evidence_id": "ev_1",
                    "quote": "error_pct: 42.0",
                    "why": "Metrics show elevated errors.",
                }
            ],
            "proposed_action": {
                "action": "restart_service",
                "target": "checkout",
                "reason": "Restore the failing service.",
                "rollback": "Stop if health checks worsen.",
            },
        }
    )
    assert result.proposed_action.action == "restart_service"


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_confidence_is_bounded(confidence):
    with pytest.raises(ValidationError):
        Diagnosis(
            decision="escalate",
            summary="Invalid confidence.",
            confidence=confidence,
        )


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        Diagnosis(
            decision="escalate",
            summary="Unexpected field.",
            confidence=0.2,
            invented_field=True,
        )
