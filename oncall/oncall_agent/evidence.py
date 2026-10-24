"""Every tool result is stored with an ID. Diagnoses may only cite IDs and quotes that exist here."""
import json
import re
import time

TOOL_SOURCE = {
    "service_overview": "metrics",
    "service_detail": "metrics",
    "get_traces": "traces",
    "search_logs": "logs",
    "container_health": "containers",
}


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9._%\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


class EvidenceStore:
    def __init__(self):
        self.items = {}

    def add(self, tool: str, args: dict, result) -> str:
        eid = f"ev_{len(self.items) + 1}"
        text = json.dumps(result, default=str)
        self.items[eid] = {
            "id": eid,
            "tool": tool,
            "source": TOOL_SOURCE.get(tool, "other"),
            "args": args,
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "result": result,
            "_norm": normalize(text),
        }
        return eid

    def check_quote(self, eid: str, quote: str):
        if eid not in self.items:
            return f"{eid} does not exist. Valid IDs: {', '.join(self.items) or 'none'}"
        q = normalize(quote or "")
        if len(q) < 3:
            return f"quote for {eid} is empty or too short"
        norm = self.items[eid]["_norm"]
        if q in norm:
            return None
        parts = [normalize(p) for p in re.split(r"[,;\n]", quote or "")]
        parts = [p for p in parts if len(p) >= 3]
        if parts and all(p in norm for p in parts):
            return None
        return f"quote {quote!r} was not found in {eid}. Quote one field or message exactly as shown."

    def source(self, eid: str) -> str:
        return self.items[eid]["source"]

    def dump(self, path):
        with open(path, "w") as f:
            for it in self.items.values():
                f.write(json.dumps({k: v for k, v in it.items() if k != "_norm"}, default=str) + "\n")
