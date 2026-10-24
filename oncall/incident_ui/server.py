"""JSON API for the web UI, plus the built UI itself (web/dist). Binds to 127.0.0.1 only."""

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import approval, config, demo_stack
from .sources import get_source

MAX_BODY = 64_000
_investigating = threading.Lock()  # ponytail: one investigation at a time, queue if needed


def known(source, incident: str) -> str:
    """Only incidents the source itself listed; blocks path tricks in ?id=."""
    if incident not in source.list():
        raise LookupError(f"unknown incident {incident!r}")
    return incident


def summary(source, incident: str) -> dict:
    d = source.get(incident)
    closed = approval.final_decision(incident)
    return {
        "id": incident,
        "alert": d["diagnosis"]["alert"],
        "decision": d["diagnosis"]["decision"],
        "confidence": d["diagnosis"]["confidence"],
        "state": d["state"],
        "closed": closed and closed["event"],
    }


def detail(source, incident: str) -> dict:
    d = source.get(known(source, incident))
    return {
        **d,
        "payload": approval.action_payload(incident, d["diagnosis"]),
        "decisions": [r for r in approval.read_log(incident) if r["event"] in approval.DECISIONS],
        "closed": approval.final_decision(incident),
        "verification": approval.verification(incident),
    }


def handle_get(source, path: str, query: dict) -> dict:
    if path == "/api/state":
        return {
            "incidents": [summary(source, i) for i in source.list()],
            "kill": approval.kill_on(),
            "source": config.SOURCE,
            "can_investigate": config.SOURCE == "http" or bool(config.INVESTIGATE),
        }
    if path == "/api/incident":
        return detail(source, query.get("id", [""])[0])
    if path == "/api/stack":
        return {"services": demo_stack.status()}
    raise LookupError(f"no route {path}")


def handle_post(source, path: str, body: dict) -> dict:
    if path == "/api/decide":
        incident = known(source, str(body.get("id", "")))
        # Rebuilt on the server from the agent's own diagnosis, never taken from the browser.
        payload = approval.action_payload(incident, source.get(incident)["diagnosis"])
        if payload is None:
            raise ValueError("this incident has no action to approve")
        return approval.decide(
            incident,
            payload,
            str(body.get("decision", "")),
            str(body.get("approver", "")),
            str(body.get("note", ""))[:500],
            forward=source.forward,
        )
    if path == "/api/kill":
        return {"kill": approval.set_kill(bool(body.get("on")))}
    if path == "/api/investigate":
        alert = str(body.get("alert", "")).strip()[:500]
        if not alert:
            raise ValueError("alert text is required")
        if not _investigating.acquire(blocking=False):
            raise ValueError("an investigation is already running")
        try:
            return {"id": source.investigate(alert)}
        finally:
            _investigating.release()
    raise LookupError(f"no route {path}")


class Handler(SimpleHTTPRequestHandler):
    source = None  # set in main()

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(config.WEB_DIST), **kw)

    def _json(self, code: int, data) -> None:
        raw = json.dumps(data, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _guard(self, fn):
        try:
            self._json(200, fn())
        except LookupError as e:
            self._json(404, {"error": str(e)})
        except PermissionError as e:
            self._json(403, {"error": str(e)})
        except ValueError as e:
            self._json(400, {"error": str(e)})
        except Exception as e:  # agent down, missing key, rate limit: report, don't crash
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def do_GET(self):
        url = urlparse(self.path)
        if url.path.startswith("/api/"):
            return self._guard(lambda: handle_get(self.source, url.path, parse_qs(url.query)))
        return super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._json(413, {"error": "body too large"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid JSON"})
        self._guard(lambda: handle_post(self.source, urlparse(self.path).path, body))


def main():
    Handler.source = get_source()
    print(f"Approval UI on http://{config.HOST}:{config.PORT}  (source: {config.SOURCE})")
    if not config.WEB_DIST.exists():
        print(f"  web UI not built yet: run `npm run build` in web/ (looked in {config.WEB_DIST})")
    ThreadingHTTPServer((config.HOST, config.PORT), Handler).serve_forever()
