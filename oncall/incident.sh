#!/usr/bin/env bash
# End to end practice run: check stack -> inject fault -> wait -> agent diagnoses -> reset.
# usage:  ./incident.sh stop valkey-cart
#         WAIT=120 ./incident.sh cpu ad 0.05
# The alert text is deliberately generic so the agent has to find the fault itself.
set -euo pipefail
[ $# -ge 1 ] || { echo "usage: ./incident.sh <simfault args>   e.g. stop valkey-cart"; exit 1; }

python -m oncall_agent check || { echo "Stack not healthy, fix that first."; exit 1; }
[ -f baseline.json ] || { echo "No baseline yet, taking one now (stack must be healthy)"; python -m oncall_agent baseline >/dev/null; }

trap 'echo; echo "Resetting fault..."; python simfault.py reset' EXIT
python simfault.py "$@"
echo "Waiting ${WAIT:-90}s for symptoms to show in telemetry..."
sleep "${WAIT:-90}"
python -m oncall_agent run "${ALERT:-Alert fired: error rate or latency above threshold on the shop}"
echo
echo "Latest report:"; ls -td runs/*/ | head -1
