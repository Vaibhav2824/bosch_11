"""Provisional output contract owned by E.

The organisers' final JSON schema was not present in the starter repository.
These models follow the frozen team contract and are intentionally independent
of any particular practice incident.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EvidenceCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    quote: str = Field(min_length=3)
    why: str = Field(min_length=1)


class RootCause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component: str = Field(min_length=1)
    cause: str = Field(min_length=1)


class ProposedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal[
        "restart_service",
        "toggle_feature_flag",
        "throttle_load_generator",
        "scale_service",
        "none",
    ]
    target: str = ""
    reason: str = ""
    rollback: str = ""


class TimelineEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time: str = Field(min_length=1)
    event: str = Field(min_length=1)


class Diagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["diagnosed", "escalate"]
    summary: str = Field(min_length=1)
    root_cause: RootCause | None = None
    confidence: float = Field(ge=0, le=1)
    evidence: list[EvidenceCitation] = Field(default_factory=list)
    alternatives_ruled_out: list[str] = Field(default_factory=list)
    proposed_action: ProposedAction | None = None
    open_questions: list[str] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)

    @classmethod
    def from_json(cls, payload: str) -> "Diagnosis":
        return cls.model_validate_json(payload)
