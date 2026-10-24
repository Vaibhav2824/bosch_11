import json
from pathlib import Path

from oncall.schema import Diagnosis


ROOT = Path(__file__).parents[1]


def test_sample_bundle_and_diagnosis_are_readable():
    bundle = ROOT / "bundles" / "sample"
    telemetry = json.loads((bundle / "telemetry.json").read_text())
    diagnosis = Diagnosis.model_validate(json.loads((bundle / "diagnosis.json").read_text()))

    assert telemetry["schema"] == "telemetry-bundle-v0"
    assert telemetry["incident_id"] == "sample"
    assert diagnosis.decision == "diagnosed"
