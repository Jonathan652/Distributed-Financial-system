#!/usr/bin/env bash
set -euo pipefail

# One-time setup per machine:
#   cp scripts/cluster.env.example scripts/cluster.env
#   edit scripts/cluster.env
# Then run:
#   ./scripts/start_regional_node.sh

if [[ -f "scripts/cluster.env" ]]; then
  # shellcheck disable=SC1091
  source "scripts/cluster.env"
fi

HOST="${HOST:-0.0.0.0}"
PORT="${REGIONAL_PORT:-8082}"
REGION="${REGION:-}"
COORDINATOR_URL="${COORDINATOR_URL:-}"
COORDINATORS="${COORDINATORS:-}"

if [[ -z "$REGION" ]]; then
  echo "REGION is required. Set REGION in scripts/cluster.env (kampala|mbarara|gulu|jinja)."
  exit 1
fi

if [[ -z "$COORDINATOR_URL" && -n "$COORDINATORS" ]]; then
  COORDINATOR_URL="${COORDINATORS%%,*}"
fi

if [[ -z "$COORDINATOR_URL" ]]; then
  echo "COORDINATOR_URL is required. Set it in scripts/cluster.env."
  exit 1
fi

PYTHONPATH=src python3 -m mobile_money.main \
  --mode regional \
  --host "$HOST" \
  --port "$PORT" \
  --region "$REGION" \
  --coordinator "$COORDINATOR_URL" \
  --coordinators "$COORDINATORS"