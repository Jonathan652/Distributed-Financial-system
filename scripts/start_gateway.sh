#!/usr/bin/env bash
set -euo pipefail

# One-time setup per machine:
#   cp scripts/cluster.env.example scripts/cluster.env
#   edit scripts/cluster.env
# Then run:
#   ./scripts/start_gateway.sh

if [[ -f "scripts/cluster.env" ]]; then
  # shellcheck disable=SC1091
  source "scripts/cluster.env"
fi

HOST="${HOST:-0.0.0.0}"
PORT="${GATEWAY_PORT:-8000}"
REGIONAL_NODES="${REGIONAL_NODES:-}"
COORDINATOR_URLS="${COORDINATOR_URLS:-}"

if [[ -z "$REGIONAL_NODES" ]]; then
  echo "REGIONAL_NODES is required in scripts/cluster.env."
  exit 1
fi

if [[ -z "$COORDINATOR_URLS" ]]; then
  echo "COORDINATOR_URLS is required in scripts/cluster.env."
  exit 1
fi

PYTHONPATH=src python3 -m mobile_money.main \
  --mode gateway \
  --host "$HOST" \
  --port "$PORT" \
  --regional-nodes "$REGIONAL_NODES" \
  --coordinator-urls "$COORDINATOR_URLS"