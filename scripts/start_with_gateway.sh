#!/bin/bash

set -e

echo "Starting 2 coordinators..."
python -m mobile_money.main --mode coordinator --port 9001 --db /tmp/coordinator0.sqlite3 &
C0_PID=$!
sleep 1

python -m mobile_money.main --mode coordinator --port 9002 --db /tmp/coordinator1.sqlite3 &
C1_PID=$!
sleep 1

echo "Starting 4 regional nodes..."
python -m mobile_money.main --mode regional --region kampala --port 8082 \
  --coordinators "http://127.0.0.1:9001,http://127.0.0.1:9002" &
R_KAMPALA_PID=$!
sleep 1

python -m mobile_money.main --mode regional --region mbarara --port 8083 \
  --coordinators "http://127.0.0.1:9001,http://127.0.0.1:9002" &
R_MBARARA_PID=$!
sleep 1

python -m mobile_money.main --mode regional --region gulu --port 8084 \
  --coordinators "http://127.0.0.1:9001,http://127.0.0.1:9002" &
R_GULU_PID=$!
sleep 1

python -m mobile_money.main --mode regional --region jinja --port 8085 \
  --coordinators "http://127.0.0.1:9001,http://127.0.0.1:9002" &
R_JINJA_PID=$!
sleep 1

echo "Starting gateway on port 8000..."
python -m mobile_money.main --mode gateway --port 8000 \
  --regional-nodes "http://127.0.0.1:8082,http://127.0.0.1:8083,http://127.0.0.1:8084,http://127.0.0.1:8085" \
  --coordinator-urls "http://127.0.0.1:9001,http://127.0.0.1:9002" &
GATEWAY_PID=$!
sleep 1

echo ""
echo "🚀 System ready!"
echo ""
echo "Gateway (single entry point):        http://127.0.0.1:8000"
echo "Regional nodes:"
echo "  - Kampala:  http://127.0.0.1:8082"
echo "  - Mbarara:  http://127.0.0.1:8083"
echo "  - Gulu:     http://127.0.0.1:8084"
echo "  - Jinja:    http://127.0.0.1:8085"
echo "Coordinators:"
echo "  - Coordinator 0: http://127.0.0.1:9001"
echo "  - Coordinator 1: http://127.0.0.1:9002"
echo ""
echo "Testing gateway health:"
curl -s http://127.0.0.1:8000/health | python -m json.tool
echo ""
echo "To run guided client against gateway: python -m mobile_money.main --mode regional --region kampala --port 8086 http://127.0.0.1:8000"
echo ""
echo "To stop all services, press Ctrl+C..."
echo ""

# Wait for interrupt
trap "echo 'Terminating services...'; kill $C0_PID $C1_PID $R_KAMPALA_PID $R_MBARARA_PID $R_GULU_PID $R_JINJA_PID $GATEWAY_PID 2>/dev/null || true" EXIT

wait
