#!/usr/bin/env python3
"""
simfault.py - DEV ONLY stand-in for the organisers' faultctl.

Injects infra faults into the running OpenTelemetry demo using plain Docker,
so the agent has real broken telemetry to look at while you wait for faultctl.
It never reads or writes feature flags (flagd), so it stays clear of Rule 6.
Check with a mentor before relying on it, and never ship it as part of the agent.

Usage:
  python simfault.py list
  python simfault.py stop      <service>            # container stopped
  python simfault.py crashloop <service> [secs]     # keeps restarting (Ctrl+C to end)
  python simfault.py cpu       <service> [cpus]     # CPU starvation, default 0.05
  python simfault.py latency   <service> [ms] [loss%]  # network latency / packet loss
  python simfault.py flood     [users] [rate]       # traffic flood via Locust
  python simfault.py reset                          # undo everything
"""
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

STATE = Path(".simfault_state.json")
LOCUST = "http://localhost:8080/loadgen"
NETSHOOT = "nicolaka/netshoot"
DEFAULT_USERS = 5  # matches LOCUST_USERS in the demo's .env


def sh(*args, check=True):
    r = subprocess.run(args, capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"command failed: {' '.join(args)}\n{r.stderr.strip()}")
    return r.stdout.strip()


def container(service):
    cid = sh("docker", "ps", "-a", "-q",
             "--filter", "label=com.docker.compose.project=opentelemetry-demo",
             "--filter", f"label=com.docker.compose.service={service}")
    if not cid:
        sys.exit(f"no container for service '{service}'. Try: python simfault.py list")
    return cid.splitlines()[0]


def load_state():
    return json.loads(STATE.read_text()) if STATE.exists() else {"stopped": [], "cpu": {}, "latency": []}


def save_state(s):
    STATE.write_text(json.dumps(s, indent=2))


def locust_swarm(users, rate):
    data = urllib.parse.urlencode({"user_count": users, "spawn_rate": rate}).encode()
    with urllib.request.urlopen(f"{LOCUST}/swarm", data=data, timeout=10) as r:
        print(r.read().decode()[:200])


def cmd_list():
    print(sh("docker", "ps", "--format", '{{.Label "com.docker.compose.service"}}\t{{.Status}}'))


def cmd_stop(svc):
    s = load_state()
    sh("docker", "stop", container(svc))
    s["stopped"].append(svc)
    save_state(s)
    print(f"stopped {svc}")


def cmd_crashloop(svc, every=20):
    cid = container(svc)
    print(f"killing {svc} every {every}s, Ctrl+C to stop (container is restarted on exit)")
    try:
        while True:
            sh("docker", "kill", cid, check=False)
            time.sleep(3)
            sh("docker", "start", cid, check=False)
            time.sleep(every)
    except KeyboardInterrupt:
        sh("docker", "start", cid, check=False)
        print("\ncrashloop ended")


def cmd_cpu(svc, cpus=0.05):
    s = load_state()
    cid = container(svc)
    if svc not in s["cpu"]:
        nano = json.loads(sh("docker", "inspect", cid))[0]["HostConfig"]["NanoCpus"]
        s["cpu"][svc] = nano / 1e9  # 0 means unlimited
    sh("docker", "update", "--cpus", str(cpus), cid)
    save_state(s)
    print(f"{svc} limited to {cpus} CPUs")


def cmd_latency(svc, ms=400, loss=0):
    s = load_state()
    rule = ["tc", "qdisc", "replace", "dev", "eth0", "root", "netem", "delay", f"{ms}ms"]
    if float(loss) > 0:
        rule += ["loss", f"{loss}%"]
    sh("docker", "run", "--rm", "--net", f"container:{container(svc)}",
       "--cap-add", "NET_ADMIN", NETSHOOT, *rule)
    if svc not in s["latency"]:
        s["latency"].append(svc)
    save_state(s)
    print(f"{svc}: +{ms}ms delay, {loss}% loss on all its traffic")


def cmd_flood(users=60, rate=10):
    locust_swarm(users, rate)
    print(f"Locust ramping to {users} users. Keep it modest on an 8 GB laptop.")


def cmd_reset():
    s = load_state()
    for svc in s["stopped"]:
        sh("docker", "start", container(svc), check=False)
        print(f"started {svc}")
    for svc, cpus in s["cpu"].items():
        # --cpus 0 does not lift a limit; "unlimited" = every host core
        cpus = cpus or sh("docker", "info", "-f", "{{.NCPU}}")
        sh("docker", "update", "--cpus", str(cpus), container(svc), check=False)
        print(f"restored CPU on {svc}")
    for svc in s["latency"]:
        sh("docker", "run", "--rm", "--net", f"container:{container(svc)}", "--cap-add",
           "NET_ADMIN", NETSHOOT, "tc", "qdisc", "del", "dev", "eth0", "root", check=False)
        print(f"removed netem on {svc}")
    try:
        locust_swarm(DEFAULT_USERS, 1)
    except Exception as e:  # loadgen may be down; not fatal
        print(f"could not reset Locust: {e}")
    STATE.unlink(missing_ok=True)
    print("reset done")


CMDS = {"list": cmd_list, "stop": cmd_stop, "crashloop": cmd_crashloop, "cpu": cmd_cpu,
        "latency": cmd_latency, "flood": cmd_flood, "reset": cmd_reset}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        sys.exit(__doc__)
    fn = CMDS[sys.argv[1]]
    args = [a if not a.replace(".", "").isdigit() else float(a) if "." in a else int(a)
            for a in sys.argv[2:]]
    fn(*args)
