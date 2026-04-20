#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/start_coordinator.sh
# Optional env vars:
#   HOST=0.0.0.0 PORT=8081 DB_PATH=/tmp/uganda-ledger.sqlite3 REGIONS=kampala,mbarara,gulu,jinja

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8081}"
DB_PATH="${DB_PATH:-/tmp/uganda-ledger.sqlite3}"
REGIONS="${REGIONS:-kampala,mbarara,gulu,jinja}"

PYTHONPATH=src python3 -m mobile_money.main \
  --mode coordinator \
  --host "$HOST" \
  --port "$PORT" \
  --db "$DB_PATH" \
  --regions "$REGIONS"
