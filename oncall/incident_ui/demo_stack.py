"""The OpenTelemetry demo the agent works on: is each UI up, and where to look at evidence.

Only reads HTTP status codes and builds links for a human to click. Never touches flagd or
the feature-flag UI: any configured URL that points there is refused at import.
"""

import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import config

for _name, _url in config.DEMO.items():
    if any(part in _url.lower() for part in config.FORBIDDEN_URL_PARTS):
        raise ValueError(
            f"DEMO URL for {_name} points at feature flags ({_url}); that is not allowed"
        )

CACHE_SECONDS = 10
_cache: tuple[float, list[dict]] = (0.0, [])


def _check(name: str, url: str) -> dict:
    try:
        with urllib.request.urlopen(url + config.DEMO_HEALTH.get(name, "/"), timeout=3) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception as e:  # down, refused, DNS: report it, never raise
        return {"name": name, "url": url, "ok": False, "detail": type(e).__name__}
    return {"name": name, "url": url, "ok": code < 400, "detail": f"HTTP {code}"}


def status() -> list[dict]:
    global _cache
    if time.monotonic() - _cache[0] > CACHE_SECONDS:
        with ThreadPoolExecutor(len(config.DEMO)) as pool:
            rows = list(pool.map(lambda kv: _check(*kv), config.DEMO.items()))
        _cache = (time.monotonic(), rows)
    return _cache[1]


def _find(obj, *keys):
    """First value for any of keys anywhere in a nested result (e.g. example_trace_id)."""
    if isinstance(obj, dict):
        for k in keys:
            if obj.get(k):
                return obj[k]
        obj = list(obj.values())
    if isinstance(obj, list):
        for v in obj:
            if (hit := _find(v, *keys)) is not None:
                return hit
    return None


def evidence_link(item: dict, result) -> dict | None:
    """Where a human can see this evidence in the demo's own tools."""
    args = item.get("args") if isinstance(item.get("args"), dict) else {}
    service = args.get("service") or ""
    jaeger = config.DEMO["Jaeger"]
    if item["source"] == "traces":
        trace = _find(result, "example_trace_id", "trace_id", "traceID")
        if trace:
            return {"label": "Open trace in Jaeger", "url": f"{jaeger}/trace/{trace}"}
        if service:
            query = {"service": service}
            if args.get("kind", "errors") == "errors" and "min_duration" not in args:
                query["tags"] = '{"error":"true"}'
            q = urllib.parse.urlencode(query)
            return {"label": f"Search {service} traces in Jaeger", "url": f"{jaeger}/search?{q}"}
    if item["source"] == "metrics":
        return {"label": "Open Grafana dashboards", "url": f"{config.DEMO['Grafana']}/dashboards"}
    return None
