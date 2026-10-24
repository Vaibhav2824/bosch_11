"""
The investigation loop: alert in, evidence-backed Diagnosis out.
The LLM picks each next tool from what it has seen so far (no giant prompt dump).
"""
import json
import os
import re
import time

import litellm
import logging, warnings
warnings.filterwarnings("ignore")
logging.getLogger("LiteLLM").setLevel(logging.ERROR)
from pydantic import ValidationError

from . import config
from .evidence import EvidenceStore
from .report import build_report
from .schema import SUBMIT_SPEC, Diagnosis
from .tools import TOOL_SPECS, TOOLS

SYSTEM = """You are an on-call SRE investigating a live incident in the OpenTelemetry demo shop
(microservices: frontend, frontend-proxy, cart, checkout, payment, product-catalog, recommendation,
ad, currency, shipping, quote, email, image-provider, plus valkey-cart cache and astronomy-db).

Method:
1. Start with service_overview to see which services deviate from baseline.
2. Narrow down. Errors in a caller often start downstream: use get_traces kind=errors to find the
   ORIGIN of errors, and kind=slow for latency. Use service_detail to see which operation is affected.
3. Confirm with an independent source: search_logs and/or container_health (down, restarting,
   OOM killed, CPU limited, recently restarted).
4. Stop as soon as two independent sources agree, then call submit_diagnosis.

Rules:
- Only state facts that appear in tool output. Every evidence item cites an evidence_id and a quote
  copied exactly from that tool's output (e.g. a number with its field name, or a log message).
- Distinguish symptom from cause. Name the component where the problem originates.
- If evidence is weak, conflicting or missing, use decision="escalate" and list what you found and
  what is unknown. A correct escalation scores better than a confident wrong fix.
- Proposed action must be one of: restart_service, toggle_feature_flag, throttle_load_generator,
  scale_service, none. Never act yourself; a human approves later.
- gRPC status 14 = UNAVAILABLE. If the deepest failing span is a client call such as
  oteldemo.ProductCatalogService/GetProduct, the failing component is the CALLEE (product-catalog),
  not the caller. Errors like "Name or service not known" or "produced zero addresses" mean the callee
  container is down or unreachable: confirm with container_health on the callee.
- Ignore errors that come only from the load-generator.
- Be efficient: usually 3 to 5 tool calls are enough."""


def _assistant_msg(msg):
    out = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        out["tool_calls"] = [{"id": tc.id, "type": "function",
                              "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
                             for tc in msg.tool_calls]
    return out


def _run_tool(name, args):
    fn = TOOLS.get(name)
    if not fn:
        return {"error": f"unknown tool {name}"}
    try:
        return fn(**args)
    except TypeError as e:
        return {"error": f"bad arguments: {e}"}
    except Exception as e:  # tool failures become visible evidence, not crashes
        return {"error": f"{type(e).__name__}: {e}"}


def validate(raw: dict, store: EvidenceStore):
    """Return (Diagnosis, None) or (None, error text for the model)."""
    try:
        d = Diagnosis.model_validate(raw)
    except ValidationError as e:
        return None, f"schema error: {e}"
    errors = [err for ev in d.evidence if (err := store.check_quote(ev.evidence_id, ev.quote))]
    if d.decision == "diagnosed":
        if not d.root_cause:
            errors.append("decision=diagnosed requires root_cause")
        if not d.evidence:
            errors.append("decision=diagnosed requires at least one evidence item")
    if errors:
        return None, "Diagnosis rejected:\n- " + "\n- ".join(errors)
    return d, None


def calibrate(d: Diagnosis, store: EvidenceStore):
    """Cap confidence by how many independent sources back it; escalate if too low."""
    sources = sorted({store.source(ev.evidence_id) for ev in d.evidence})
    cap = {0: 0.3, 1: 0.6, 2: 0.8}.get(len(sources), 0.95)
    out = d.model_dump()
    out["confidence_model"] = d.confidence
    out["confidence"] = round(min(d.confidence, cap), 2)
    out["evidence_sources"] = sources
    out["calibration_note"] = f"{len(sources)} independent source(s) -> confidence capped at {cap}"
    if out["decision"] == "diagnosed" and out["confidence"] < config.ESCALATE_BELOW:
        out["decision"] = "escalate"
        out["calibration_note"] += f"; below {config.ESCALATE_BELOW}, so escalated to a human"
    for ev in out["evidence"]:
        ev["source"] = store.source(ev["evidence_id"])
    return out


def investigate(alert: str, verbose: bool = True):
    store = EvidenceStore()
    run_dir = os.path.join(config.RUNS_DIR, time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(run_dir, exist_ok=True)
    transcript = open(os.path.join(run_dir, "transcript.jsonl"), "w")

    def log(kind, **kw):
        rec = {"t": time.strftime("%H:%M:%S"), "kind": kind, **kw}
        transcript.write(json.dumps(rec, default=str) + "\n")
        transcript.flush()
        if verbose:
            print(f"[{rec['t']}] {kind}: " + json.dumps(kw, default=str)[:300])

    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"ALERT ({time.strftime('%H:%M:%S')}): {alert}\nInvestigate."}]
    tools = TOOL_SPECS + [SUBMIT_SPEC]
    log("alert", alert=alert, model=config.MODEL)
    result = None

    for step in range(1, config.MAX_STEPS + 3):
        last = step >= config.MAX_STEPS  # from here on, only submit_diagnosis is offered
        if step == config.MAX_STEPS:
            messages.append({"role": "user", "content": "Final step: call submit_diagnosis now with the evidence "
                                                        "you have. Use decision=escalate if unsure."})
        resp = None
        for attempt in range(8):
            try:
                resp = litellm.completion(
                    model=config.MODEL, messages=messages, temperature=0,
                    tools=[SUBMIT_SPEC] if last else tools,
                    tool_choice="auto",
                )
                break
            except litellm.RateLimitError as e:
                m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", str(e))
                wait = (int(m.group(1) or 0) * 60 + float(m.group(2)) + 1) if m else 15
                log("rate_limited", wait_s=round(wait, 1), attempt=attempt + 1)
                time.sleep(wait)
            except litellm.BadRequestError as e:
                log("llm_error", error=str(e)[:300])
                messages.append({"role": "user", "content": "Your last tool call was malformed. Call the tool "
                                                            "again with valid JSON arguments matching its schema."})
                break
        if resp is None:
            if attempt == 7:
                raise RuntimeError("still rate limited after 8 retries; use a key with higher limits")
            continue
        msg = resp.choices[0].message
        messages.append(msg)
        if msg.content:
            log("thought", text=msg.content)
        if not msg.tool_calls:
            messages.append({"role": "user", "content": "Call a tool, or submit_diagnosis if you are done."})
            continue

        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            if name == "submit_diagnosis":
                d, err = validate(args, store)
                if d:
                    result = calibrate(d, store)
                    log("diagnosis", decision=result["decision"], confidence=result["confidence"])
                    content = "accepted"
                else:
                    log("rejected", error=err)
                    content = err
            else:
                res = _run_tool(name, args)
                eid = store.add(name, args, res)
                log("tool", step=step, name=name, args=args, evidence_id=eid)
                content = json.dumps({"evidence_id": eid, "result": res}, default=str, separators=(",", ":"))[:2500]
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})
        if result:
            break

    if not result:  # budget ran out without a valid diagnosis
        result = {"decision": "escalate", "summary": f"Investigation of '{alert}' did not converge.",
                  "root_cause": None, "confidence": 0.0, "evidence": [],
                  "open_questions": ["Agent hit its step budget; see evidence.jsonl for what it looked at."],
                  "calibration_note": "no valid diagnosis submitted"}
        log("diagnosis", decision="escalate", confidence=0.0, note="budget exhausted")

    result["alert"] = alert
    result["evidence_ids_collected"] = list(store.items)
    with open(os.path.join(run_dir, "diagnosis.json"), "w") as f:
        json.dump(result, f, indent=2, default=str)
    store.dump(os.path.join(run_dir, "evidence.jsonl"))
    with open(os.path.join(run_dir, "report.md"), "w") as f:
        f.write(build_report(result, list(store.items.values())))
    transcript.close()
    result["run_dir"] = run_dir
    return result


def pretty(r):
    lines = [f"\n=== {r['decision'].upper()}  (confidence {r.get('confidence')}) ===", r.get("summary", "")]
    if r.get("root_cause"):
        lines.append(f"Root cause: {r['root_cause']['component']}: {r['root_cause']['cause']}")
    for ev in r.get("evidence", []):
        lines.append(f"  [{ev['evidence_id']}/{ev.get('source')}] \"{ev['quote']}\": {ev['why']}")
    if r.get("proposed_action"):
        a = r["proposed_action"]
        lines.append(f"Proposed: {a['action']} {a.get('target', '')} ({a.get('reason', '')})")
    for q in r.get("open_questions", []):
        lines.append(f"  ? {q}")
    if r.get("calibration_note"):
        lines.append(f"({r['calibration_note']})")
    lines.append(f"Saved to {r.get('run_dir')}")
    return "\n".join(lines)
