"""
Read-only telemetry tools. Each returns a compact summary (not raw dumps) so the
LLM can reason over it. None of them touch flagd / feature flags.
"""
import json
import math
import os
import re
import subprocess
import time
from collections import Counter, defaultdict

import requests

from . import config

TIMEOUT = 45
PROJECT = os.getenv("COMPOSE_PROJECT", "opentelemetry-demo")


# ---------------------------------------------------------------- Prometheus
def _prom(query: str):
    r = requests.get(f"{config.PROM_URL}/api/v1/query", params={"query": query}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["data"]["result"]


def _by(result, label):
    out = {}
    for s in result:
        key = s["metric"].get(label)
        v = float(s["value"][1])
        if key is None or math.isnan(v) or math.isinf(v):
            continue
        out[key] = v
    return out


def _r(x, n=2):
    return None if x is None else round(x, n)


def _service_stats(window="2m", offset=""):
    off = f" offset {offset}" if offset else ""
    calls = "traces_span_metrics_calls_total"
    dur = "traces_span_metrics_duration_milliseconds_bucket"
    rps = _by(_prom(f"sum by (service_name) (rate({calls}[{window}]{off}))"), "service_name")
    err = _by(_prom(
        f'sum by (service_name) (rate({calls}{{status_code="STATUS_CODE_ERROR"}}[{window}]{off}))'
    ), "service_name")
    p95 = _by(_prom(
        f"histogram_quantile(0.95, sum by (le, service_name) (rate({dur}[{window}]{off})))"
    ), "service_name")
    stats = {}
    for svc in set(rps) | set(p95):
        if svc in config.IGNORE_SERVICES:
            continue
        r = rps.get(svc, 0.0)
        e = err.get(svc, 0.0)
        stats[svc] = {
            "rps": _r(r),
            "error_pct": _r(100 * e / r if r > 0 else 0.0, 1),
            "p95_ms": _r(p95.get(svc), 0),
        }
    return stats


def _load_baseline():
    if os.path.exists(config.BASELINE_FILE):
        with open(config.BASELINE_FILE) as f:
            return json.load(f), "saved baseline"
    return _service_stats(window="5m", offset="15m"), "same metrics 15 minutes ago"


def save_baseline():
    stats = _service_stats(window="5m")
    with open(config.BASELINE_FILE, "w") as f:
        json.dump(stats, f, indent=2)
    return stats


def service_overview(window: str = "2m"):
    """Per service RPS, error % and p95 latency now vs baseline, ranked by how anomalous they look."""
    now = _service_stats(window)
    base, base_src = _load_baseline()
    rows, missing = [], []
    for svc, cur in now.items():
        b = base.get(svc, {})
        score = 0.0
        if b:
            score += max(cur["error_pct"] - (b.get("error_pct") or 0), 0) / 5
            if cur["p95_ms"] and b.get("p95_ms"):
                score += max(cur["p95_ms"] / b["p95_ms"] - 1, 0)
            if b.get("rps"):
                score += max(1 - cur["rps"] / b["rps"], 0)
        else:
            score += cur["error_pct"] / 5
        rows.append({"service": svc, **cur, "baseline": b or None, "anomaly_score": _r(score)})
    for svc, b in base.items():
        if svc not in now and svc not in config.IGNORE_SERVICES:
            missing.append({"service": svc, "baseline": b,
                            "note": "no spans at all in the current window (service may be down)"})
    rows.sort(key=lambda x: x["anomaly_score"], reverse=True)
    return {"window": window, "baseline_source": base_src, "services": rows,
            "services_without_traffic": missing}


def service_detail(service: str, window: str = "2m"):
    """Per operation (span name) breakdown for one service: RPS, error %, p95."""
    calls = "traces_span_metrics_calls_total"
    dur = "traces_span_metrics_duration_milliseconds_bucket"
    sel = f'service_name="{service}"'
    rps = _by(_prom(f"sum by (span_name) (rate({calls}{{{sel}}}[{window}]))"), "span_name")
    err = _by(_prom(
        f'sum by (span_name) (rate({calls}{{{sel},status_code="STATUS_CODE_ERROR"}}[{window}]))'
    ), "span_name")
    p95 = _by(_prom(
        f"histogram_quantile(0.95, sum by (le, span_name) (rate({dur}{{{sel}}}[{window}])))"
    ), "span_name")
    ops = []
    for op in set(rps) | set(p95):
        r = rps.get(op, 0.0)
        ops.append({"operation": op, "rps": _r(r),
                    "error_pct": _r(100 * err.get(op, 0.0) / r if r > 0 else 0.0, 1),
                    "p95_ms": _r(p95.get(op), 0)})
    ops.sort(key=lambda o: (o["error_pct"], o["p95_ms"] or 0), reverse=True)
    return {"service": service, "window": window, "operations": ops[:12]}


# ---------------------------------------------------------------- Jaeger (api/v3)
def _v3_spans(resp_text):
    """Parse a Jaeger api/v3 response (OTLP JSON, possibly one JSON object per line) into flat spans."""
    objs = []
    try:
        objs = [json.loads(resp_text)]
    except ValueError:
        for line in resp_text.splitlines():
            line = line.strip()
            if line:
                try:
                    objs.append(json.loads(line))
                except ValueError:
                    pass
    spans = []
    for o in objs:
        body = o.get("result", o) if isinstance(o, dict) else {}
        for rs in body.get("resourceSpans") or body.get("resource_spans") or []:
            svc = "?"
            for a in (rs.get("resource") or {}).get("attributes", []):
                if a.get("key") == "service.name":
                    svc = (a.get("value") or {}).get("stringValue", "?")
            for ss in rs.get("scopeSpans") or rs.get("scope_spans") or []:
                for s in ss.get("spans", []):
                    attrs = {a["key"]: next(iter((a.get("value") or {"x": None}).values()), None)
                             for a in s.get("attributes", [])}
                    status = s.get("status") or {}
                    is_err = status.get("code") in (2, "2", "STATUS_CODE_ERROR", "ERROR")
                    msg = status.get("message") or ""
                    for ev in s.get("events", []):
                        for a in ev.get("attributes", []):
                            if a.get("key") == "exception.message" and not msg:
                                msg = next(iter((a.get("value") or {"x": ""}).values()), "")
                    start = int(s.get("startTimeUnixNano") or 0)
                    end = int(s.get("endTimeUnixNano") or 0)
                    spans.append({
                        "trace": s.get("traceId"), "id": s.get("spanId"), "parent": s.get("parentSpanId") or None,
                        "service": svc, "op": s.get("name"), "dur_us": max(end - start, 0) / 1000.0,
                        "error": is_err, "msg": str(msg)[:200],
                        "code": attrs.get("rpc.grpc.status_code") or attrs.get("http.response.status_code")
                                or attrs.get("http.status_code"),
                    })
    return spans


def get_traces(service: str, kind: str = "errors", lookback: str = "10m", limit: int = 20,
               min_duration: str = "500ms"):
    """
    Jaeger api/v3. kind="errors": error traces through `service`, reduced to the deepest failing span
    (where the error originated, often downstream). kind="slow": span with the largest self time.
    """
    from datetime import datetime, timedelta, timezone
    unit = {"s": 1, "m": 60, "h": 3600}[lookback[-1]]
    now = datetime.now(timezone.utc)
    start = now - timedelta(seconds=int(lookback[:-1]) * unit)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    params = {"query.service_name": service, "query.start_time_min": start.strftime(fmt),
              "query.start_time_max": now.strftime(fmt),
              # errors are usually a minority of traces, so pull more and filter here
              "query.search_depth": 40 if kind == "errors" else 20}
    if kind == "slow":
        params["query.duration_min"] = min_duration
    base = (config.JAEGER_URL or "http://localhost:8080/jaeger/ui").rstrip("/")
    r = requests.get(f"{base}/api/v3/traces", params=params, timeout=TIMEOUT)
    if r.status_code == 400 and "query.duration_min" in params:  # older gateways: filter client side
        params.pop("query.duration_min")
        r = requests.get(f"{base}/api/v3/traces", params=params, timeout=TIMEOUT)
    if r.status_code == 404:  # v3 returns 404 when nothing matches
        spans = []
    else:
        r.raise_for_status()
        spans = _v3_spans(r.text)

    traces = defaultdict(dict)
    for s in spans:
        traces[s["trace"]][s["id"]] = s

    origins, examples, matched = Counter(), {}, 0
    for tid, sp in traces.items():
        children = defaultdict(list)
        for s in sp.values():
            if s["parent"] in sp:
                children[s["parent"]].append(s["id"])
        if kind == "errors":
            err = {k for k, s in sp.items() if s["error"]}
            if not err:
                continue
            matched += 1

            def has_err_desc(sid):
                return any(c in err or has_err_desc(c) for c in children[sid])

            for sid in err:
                if has_err_desc(sid):
                    continue  # a child failed first, so this is not the origin
                s = sp[sid]
                key = (s["service"], s["op"], s["msg"], str(s["code"]))
                origins[key] += 1
                examples.setdefault(key, tid)
        else:
            root_dur = max(s["dur_us"] for s in sp.values())
            min_us = _to_us(min_duration)
            if root_dur < min_us:
                continue
            matched += 1
            best = max(sp.values(), key=lambda s: s["dur_us"] - sum(sp[c]["dur_us"] for c in children[s["id"]]))
            self_us = best["dur_us"] - sum(sp[c]["dur_us"] for c in children[best["id"]])
            key = (best["service"], best["op"])
            origins[key] += max(self_us, 0) / 1000.0
            examples.setdefault(key, tid)

    if kind == "errors":
        top = [{"origin_service": k[0], "operation": k[1], "error_message": k[2], "status_code": k[3],
                "count": n, "example_trace_id": examples[k]} for k, n in origins.most_common(6)]
        return {"service": service, "kind": kind, "lookback": lookback, "traces_scanned": len(traces),
                "traces_with_errors": matched, "error_origins": top}
    top = [{"service": k[0], "operation": k[1], "total_self_time_ms": round(v), "example_trace_id": examples[k]}
           for k, v in origins.most_common(6)]
    return {"service": service, "kind": kind, "lookback": lookback, "min_duration": min_duration,
            "traces_scanned": len(traces), "slow_traces": matched, "biggest_self_time_spans": top}


def _to_us(d):
    for suf, mult in (("ms", 1000), ("us", 1), ("s", 1_000_000), ("m", 60_000_000)):
        if d.endswith(suf):
            return float(d[: -len(suf)]) * mult
    return float(d)



# ---------------------------------------------------------------- OpenSearch logs
_os_url_cache = None


def _opensearch_url():
    global _os_url_cache
    if config.OPENSEARCH_URL:
        return config.OPENSEARCH_URL
    if _os_url_cache:
        return _os_url_cache
    out = subprocess.run(["docker", "ps", "--filter", "label=com.docker.compose.service=opensearch",
                          "--format", "{{.Ports}}"], capture_output=True, text=True).stdout
    m = re.search(r":(\d+)->9200/tcp", out)
    if not m:
        raise RuntimeError("could not find OpenSearch host port; set OPENSEARCH_URL")
    _os_url_cache = f"http://localhost:{m.group(1)}"
    return _os_url_cache


def _shape(body):
    s = body if isinstance(body, str) else json.dumps(body, default=str)
    s = re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27,}", "<uuid>", s)
    s = re.sub(r"\b[0-9a-f]{16,}\b", "<hex>", s)
    s = re.sub(r"\d+", "<n>", s)
    return s[:160]


def search_logs(service: str = "", level: str = "error", pattern: str = "", minutes: int = 10,
                limit: int = 200):
    """
    Recent logs from OpenSearch, grouped by message shape with counts.
    level: "error" (error/fatal/critical), "warn" (adds warnings) or "any".
    With no service, also returns error log counts per service.
    """
    must = [{"range": {"observedTimestamp": {"gte": f"now-{int(minutes)}m"}}}]
    if service:
        must.append({"term": {"resource.service.name.keyword": service}})
    if level == "error":
        must.append({"query_string": {"query": "severity.text:(error OR fatal OR critical)"}})
    elif level == "warn":
        must.append({"query_string": {"query": "severity.text:(error OR fatal OR critical OR warn OR warning)"}})
    if pattern:
        must.append({"match_phrase": {"body": pattern}})
    q = {"size": limit, "sort": [{"observedTimestamp": "desc"}], "query": {"bool": {"filter": must}},
         "aggs": {"by_service": {"terms": {"field": "resource.service.name.keyword", "size": 20}}}}
    r = requests.post(f"{_opensearch_url()}/{config.LOG_INDEX}/_search", json=q, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    hits = data["hits"]["hits"]
    groups = {}
    for h in hits:
        src = h["_source"]
        svc = (src.get("resource") or {}).get("service.name") or src.get("resource.service.name") or "?"
        body = src.get("body")
        sev = (src.get("severity") or {}).get("text") if isinstance(src.get("severity"), dict) else src.get("severity.text")
        key = (svc, _shape(body))
        g = groups.setdefault(key, {"service": svc, "severity": sev, "count": 0,
                                    "example": (body if isinstance(body, str) else json.dumps(body, default=str))[:300],
                                    "latest": src.get("observedTimestamp"), "trace_id": src.get("traceId")})
        g["count"] += 1
    top = sorted(groups.values(), key=lambda g: g["count"], reverse=True)[:8]
    out = {"service": service or "all", "level": level, "minutes": minutes,
           "total_matching": data["hits"]["total"]["value"] if isinstance(data["hits"]["total"], dict) else data["hits"]["total"],
           "message_groups": top}
    if not service:
        out["count_by_service"] = {b["key"]: b["doc_count"] for b in data["aggregations"]["by_service"]["buckets"]
                                   if b["key"] not in config.IGNORE_SERVICES}
    return out


# ---------------------------------------------------------------- Docker container health
def _ago(iso):
    # Docker gives e.g. 2026-10-23T08:30:12.123456789Z (always UTC)
    from datetime import datetime, timezone
    try:
        t = datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        return int((datetime.now(timezone.utc) - t).total_seconds())
    except Exception:
        return None


def container_health(service: str = ""):
    """Status, restarts, OOM kills, exit code, uptime, CPU/memory use and CPU limit per container."""
    args = ["docker", "ps", "-a", "-q", "--filter", f"label=com.docker.compose.project={PROJECT}"]
    if service:
        args += ["--filter", f"label=com.docker.compose.service={service}"]
    ids = subprocess.run(args, capture_output=True, text=True).stdout.split()
    if not ids:
        return {"error": f"no containers found for {service or 'compose services'}"}
    info = json.loads(subprocess.run(["docker", "inspect", *ids], capture_output=True, text=True).stdout)
    stats = {}
    st = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}", *ids],
                        capture_output=True, text=True).stdout
    for line in st.splitlines():
        try:
            s = json.loads(line)
            stats[s["ID"][:12]] = s
        except Exception:
            pass
    rows = []
    for c in info:
        svc = c["Config"]["Labels"].get("com.docker.compose.service")
        if svc in config.IGNORE_SERVICES:
            continue
        state = c["State"]
        s = stats.get(c["Id"][:12], {})
        nano = c["HostConfig"].get("NanoCpus") or 0
        up = _ago(state.get("StartedAt", "")) if state.get("Running") else None
        rows.append({
            "service": svc,
            "status": state.get("Status"),
            "health": (state.get("Health") or {}).get("Status"),
            "restart_count": c.get("RestartCount", 0),
            "oom_killed": state.get("OOMKilled"),
            "exit_code": state.get("ExitCode"),
            "uptime_s": up,
            "recently_started": up is not None and up < 900,
            "cpu_pct": s.get("CPUPerc"),
            "mem": s.get("MemUsage"),
            "mem_pct": s.get("MemPerc"),
            "cpu_limit": round(nano / 1e9, 3) if nano else "unlimited",
        })

    def badness(r):
        return (r["status"] != "running", bool(r["oom_killed"]), r["restart_count"], r["recently_started"])

    rows.sort(key=badness, reverse=True)
    return {"containers": rows if service else rows[:15]}


# ---------------------------------------------------------------- registry for the LLM
TOOLS = {
    "service_overview": service_overview,
    "service_detail": service_detail,
    "get_traces": get_traces,
    "search_logs": search_logs,
    "container_health": container_health,
}

TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "service_overview",
        "description": "Start here. RPS, error % and p95 latency for every service now vs baseline, ranked by anomaly, "
                       "plus services that have stopped producing spans.",
        "parameters": {"type": "object", "properties": {
            "window": {"type": "string", "description": "PromQL range, e.g. 2m or 5m", "default": "2m"}}}}},
    {"type": "function", "function": {
        "name": "service_detail",
        "description": "Per operation breakdown (RPS, error %, p95) for one service, to see which endpoint/RPC is failing.",
        "parameters": {"type": "object", "required": ["service"], "properties": {
            "service": {"type": "string"}, "window": {"type": "string", "default": "2m"}}}}},
    {"type": "function", "function": {
        "name": "get_traces",
        "description": "Jaeger traces through a service. kind=errors finds where errors ORIGINATE (deepest failing span, "
                       "often a downstream service). kind=slow finds the span with the most self time in slow traces.",
        "parameters": {"type": "object", "required": ["service"], "properties": {
            "service": {"type": "string"},
            "kind": {"type": "string", "enum": ["errors", "slow"], "default": "errors"},
            "lookback": {"type": "string", "default": "10m"},
            "min_duration": {"type": "string", "default": "500ms", "description": "only for kind=slow"}}}}},
    {"type": "function", "function": {
        "name": "search_logs",
        "description": "Recent logs grouped by message with counts. Leave service empty to get error counts per service.",
        "parameters": {"type": "object", "properties": {
            "service": {"type": "string", "default": ""},
            "level": {"type": "string", "enum": ["error", "warn", "any"], "default": "error"},
            "pattern": {"type": "string", "default": "", "description": "phrase that must appear in the log body"},
            "minutes": {"type": "integer", "default": 10}}}}},
    {"type": "function", "function": {
        "name": "container_health",
        "description": "Docker state per service: running/exited, restart count, OOM killed, uptime (recent restarts or "
                       "redeploys), CPU and memory use, CPU limit. Leave service empty for all.",
        "parameters": {"type": "object", "properties": {"service": {"type": "string", "default": ""}}}}},
]