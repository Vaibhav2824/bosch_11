"""
Diagnosis output. Placeholder until you have the organisers' JSON schema:
swap the field names here and everything else keeps working.
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    evidence_id: str = Field(description="ID returned by a tool call, e.g. ev_3")
    quote: str = Field(description="Exact text copied from that tool output (a value, message or field)")
    why: str = Field(description="What this shows")


class RootCause(BaseModel):
    component: str = Field(description="Failing service or dependency, e.g. payment, valkey-cart")
    cause: str = Field(description="What is wrong, in one or two sentences")


class ProposedAction(BaseModel):
    action: Literal["restart_service", "toggle_feature_flag", "throttle_load_generator", "scale_service", "none"]
    target: str = ""
    reason: str = ""


class TimelineEvent(BaseModel):
    time: str
    event: str


class Diagnosis(BaseModel):
    decision: Literal["diagnosed", "escalate"]
    summary: str = Field(description="One or two sentences on what the user impact is")
    root_cause: Optional[RootCause] = None
    confidence: float = Field(ge=0, le=1)
    evidence: List[Evidence] = Field(default_factory=list)
    alternatives_ruled_out: List[str] = Field(default_factory=list)
    proposed_action: Optional[ProposedAction] = None
    open_questions: List[str] = Field(default_factory=list, description="What is still unknown, especially when escalating")
    timeline: List[TimelineEvent] = Field(default_factory=list)


def _inline(schema):
    """Resolve $ref/$defs and drop anyOf-null so every LLM provider accepts the tool schema."""
    defs = schema.pop("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(dict(defs[node["$ref"].split("/")[-1]]))
            if "anyOf" in node:
                opts = [o for o in node["anyOf"] if o.get("type") != "null"]
                if len(opts) == 1:
                    rest = {k: v for k, v in node.items() if k not in ("anyOf", "default")}
                    return walk({**opts[0], **rest})
            return {k: walk(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(schema)


SUBMIT_SPEC = {"type": "function", "function": {
    "name": "submit_diagnosis",
    "description": "Finish the investigation. Use decision=escalate with your findings if the evidence is weak or "
                   "conflicting. Every evidence item must cite a real evidence_id and a quote copied from it.",
    "parameters": _inline(Diagnosis.model_json_schema()),
}}
