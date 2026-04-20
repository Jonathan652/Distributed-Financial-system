#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/start_regional.sh <region> <coordinator_url>
# Example:
#   ./scripts/start_regional.sh mbarara http://10.0.0.10:8081
# Optional env vars:
#   HOST=0.0.0.0 PORT=8082

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <region> <coordinator_url>"
  exit 1
fi

REGION="$1"
COORDINATOR_URL="$2"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8082}"

PYTHONPATH=src python3 -m mobile_money.main \
  --mode regional \
  --region "$REGION" \
  --host "$HOST" \
  --port "$PORT" \
  --coordinator "$COORDINATOR_URL"
