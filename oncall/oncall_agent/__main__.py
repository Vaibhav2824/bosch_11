"""
python -m oncall_agent check                         # are all UIs and backends up?
python -m oncall_agent baseline                      # snapshot healthy metrics to baseline.json
python -m oncall_agent tool service_overview         # run one tool by hand
python -m oncall_agent tool get_traces '{"service":"checkout"}'
python -m oncall_agent run "error rate up on checkout"  # full investigation
"""
import json
import sys

from .agent import investigate, pretty
from .tools import TOOLS, _opensearch_url, save_baseline


def check_stack():
    """Is every UI/backend up? Only looks at HTTP status codes; never reads flag values."""
    import requests
    from . import config
    targets = {
        "shop": "http://localhost:8080/",
        "grafana": "http://localhost:8080/grafana/api/health",
        "jaeger": f"{config.JAEGER_URL}/api/v3/services",
        "loadgen": "http://localhost:8080/loadgen/",
        "flags UI": "http://localhost:8080/feature/",
        "prometheus": f"{config.PROM_URL}/-/ready",
    }
    try:
        targets["opensearch"] = _opensearch_url()
    except Exception as e:
        print(f"  FAIL opensearch   {e}")
    ok = True
    for name, url in targets.items():
        try:
            code = requests.get(url, timeout=5).status_code
            good = code < 400
        except Exception as e:
            code, good = type(e).__name__, False
        ok &= good
        print(f"  {'OK  ' if good else 'FAIL'} {name:<11} {code}  {url}")
    return ok


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "baseline":
        print(json.dumps(save_baseline(), indent=2))
    elif cmd == "check":
        ok = check_stack()
        sys.exit(0 if ok else 1)
    elif cmd == "tool":
        name = sys.argv[2]
        args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        print(json.dumps(TOOLS[name](**args), indent=2, default=str))
    elif cmd == "run":
        alert = " ".join(sys.argv[2:]) or "Alert fired: error rate or latency above threshold"
        print(pretty(investigate(alert)))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
