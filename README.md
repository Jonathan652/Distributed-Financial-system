# Uganda Mobile Money Reference

This project is a Python reference implementation of a regional mobile money architecture.

It keeps one authoritative ledger for strong consistency and lets regional nodes in places like Kampala, Mbarara, Gulu, and Jinja serve traffic locally while synchronizing wallet state immediately after every committed transaction.

## Documentation

- **[QUICK_REFERENCE.md](QUICK_REFERENCE.md)** — Copy-paste commands for your machine IPs (start here!)
- **[DISTRIBUTED_TESTING.md](DISTRIBUTED_TESTING.md)** — Complete guide with checklists, test scenarios, and troubleshooting
- **Setup helper** — Run `python3 scripts/setup_distributed.py` to interactively generate deployment commands

## What it solves

- Strong balance consistency across regions
- Immediate visibility after deposits, withdrawals, and transfers
- Idempotent retries for failed or duplicated requests
- Regional failover without losing the central source of truth

## Architecture

- `Coordinator Service`: authoritative write service for a shard of wallets
- `Regional Node Service`: lightweight edge API deployed per region (Kampala, Mbarara, Gulu, Jinja)
- `LedgerStore`: authoritative ledger per coordinator shard (SQLite file in this reference implementation)
- `Client Simulator`: concurrent clients hitting multiple regional nodes

This is not Flux. It is a fresh Python implementation with the same correctness logic, adapted for a multi-region design.

## Service Modes

```bash
PYTHONPATH=src /usr/bin/python3 -m mobile_money.main --mode coordinator
PYTHONPATH=src /usr/bin/python3 -m mobile_money.main --mode regional --region mbarara --coordinator http://<coordinator-ip>:8081
```

### Sharded coordinator mode (recommended for peak traffic)

Run two or more coordinator instances (each with its own DB path), then point regional nodes to all coordinator URLs:

```bash
PYTHONPATH=src /usr/bin/python3 -m mobile_money.main --mode coordinator --port 8081 --db /tmp/ledger-a.sqlite3
PYTHONPATH=src /usr/bin/python3 -m mobile_money.main --mode coordinator --port 8083 --db /tmp/ledger-b.sqlite3

PYTHONPATH=src /usr/bin/python3 -m mobile_money.main \
	--mode regional \
	--region mbarara \
	--coordinator http://<coordinator-a-ip>:8081 \
	--coordinators http://<coordinator-a-ip>:8081,http://<coordinator-b-ip>:8083
```

Regional nodes route each wallet to its owning coordinator and cache the owner mapping.
If one coordinator is unavailable, regional nodes continue serving wallets owned by other healthy coordinators.

Regional observability endpoints:

- `GET /health`: regional service health and cache stats
- `GET /cache`: wallet cache count and owner-cache count
- `GET /coordinators`: known coordinator URLs and health status

## Short Commands (No Need To Memorize Long Flags)

Use these scripts from the project root on every machine:

```bash
./scripts/run_tests.sh
./scripts/start_coordinator.sh
./scripts/start_regional.sh mbarara http://<coordinator-ip>:8081
```

Why long commands appear in docs:
- They show every deploy flag explicitly (`--host`, `--port`, `--coordinator`, etc.) so operators can see exactly what is running.
- This is useful for first-time setup and troubleshooting, but not ideal for daily use.

### Ultra-Short Per-Machine Commands (recommended)

Do this once on each machine:

```bash
cp scripts/cluster.env.example scripts/cluster.env
# edit scripts/cluster.env for this machine
```

Then start services with one command:

```bash
# Coordinator machine
./scripts/start_coordinator.sh

# Regional node machine (REGION and coordinator settings come from scripts/cluster.env)
./scripts/start_regional_node.sh

# Gateway machine (optional)
./scripts/start_gateway.sh
```

This keeps daily operations simple while still allowing full explicit commands when needed.

## Beginner Guided Client (One Question Only)

The simplest user experience: enter phone number and everything else is automatic.

```bash
PYTHONPATH=src python3 scripts/simulate_clients.py --interactive
```

The system now:

- asks only for phone number
- **auto-detects home region from which regional node you're connecting to** (if you connect to Mbarara node, you're in Mbarara)
- auto-selects a healthy regional node
- **reuses existing wallet if one already exists** (wallet is persistent across sessions)
- creates a wallet only if one doesn't exist
- shows clear, organized receipt-style output after every operation

**What you see:**
1. "Enter your phone number"
2. System detects your region (from the node you connected to), picks a coordinator, finds or creates your wallet
3. Menu: Check balance, Deposit, Withdraw, Transfer, Show transactions
4. Organized receipt after each operation

No technical details. No server knowledge needed. Phone number is your wallet identifier—use the same number and you'll get your existing wallet back.

Optional advanced override (for operators only):

```bash
PYTHONPATH=src python3 scripts/simulate_clients.py --interactive --node-urls http://127.0.0.1:8082,http://127.0.0.1:8084
```

Examples for each role:

- Coordinator machine:

```bash
./scripts/start_coordinator.sh
```

- Kampala machine:

```bash
./scripts/start_regional.sh kampala http://<coordinator-ip>:8081
```

- Mbarara machine:

```bash
./scripts/start_regional.sh mbarara http://<coordinator-ip>:8081
```

- Gulu machine:

```bash
./scripts/start_regional.sh gulu http://<coordinator-ip>:8081
```

- Jinja machine:

```bash
./scripts/start_regional.sh jinja http://<coordinator-ip>:8081
```

## Smart Gateway (Single Entry Point for All Users)

The **Gateway Service** is an optional load balancer that provides a single entry point for all users. Instead of directing users to specific regional nodes, users point their clients to the gateway on a single port. The gateway then:

1. **Auto-routes to the right regional node** based on wallet ownership
2. **Handles wallet placement** using deterministic hashing (wallet stays on same coordinator)
3. **Caches wallet locations** to avoid repeated lookups
4. **Serves both local and cross-region transactions** transparently

### When to use the gateway

- **Small deployments** (1-4 regional nodes): Gateway adds a single hop but eliminates user complexity
- **New SMS/USSD UI** that clients will connect to before knowing which region they're in
- **Operator dashboards** that need to route traffic to regional nodes automatically
- **Testing**: Run all services (2 coordinators + 4 regional nodes + 1 gateway) locally in one script

### Running locally with gateway

```bash
./scripts/start_with_gateway.sh
```

This script starts:
- 2 coordinators (ports 9001–9002)
- 4 regional nodes (ports 8082–8085)
- 1 gateway (port 8000)

Then in another terminal:

```bash
# Connect to gateway instead of specific regional node
PYTHONPATH=src python3 scripts/simulate_clients.py --interactive --base-url http://127.0.0.1:8000
```

The gateway routes your requests automatically. You no longer need to know which node to connect to.

### Gateway command (production)

```bash
PYTHONPATH=src /usr/bin/python3 -m mobile_money.main \
	--mode gateway \
	--host 0.0.0.0 \
	--port 8000 \
	--regional-nodes http://<kampala-ip>:8082,http://<mbarara-ip>:8082,http://<gulu-ip>:8082,http://<jinja-ip>:8082 \
	--coordinator-urls http://<coordinator-a-ip>:8081,http://<coordinator-b-ip>:8083
```

### How the gateway works

1. **On wallet creation**: Gateway picks a coordinator using deterministic hash(user_id) and remembers the placement
2. **On read/write**: Gateway looks up wallet owner (cached), routes to that regional node
3. **On cross-shard transfer**: Gateway resolves both wallet owners, coordinates transaction
4. **On hot wallets**: Once a wallet is created, future requests are cached—no lookup needed

The gateway is stateless; cache is in-memory and rebuilt from regional nodes on restart. Regional nodes don't change; only the gateway's routing logic is new.

---

## Quick Start: Multi-Machine Distributed Testing

### Architecture Diagram

```
        Client Machines (Any Number)
        ├── CLI curl / Python
        ├── Interactive guided client
        └── Load simulator (40 concurrent)
                    │
                    └─────────────────────────┬─────────────────────────┐
                                              │
        ┌─────────────────────────────────────┼─────────────────────────┐
        │        Regional Edge Layer          │                         │
        │                                     │                         │
        ├─ Kampala Node :8082                 │                         │
        │  (192.168.1.20)                     │                         │
        │                                     │                         │
        ├─ Mbarara Node :8082                 │                         │
        │  (192.168.1.30)                     │                         │
        │                                     │                         │
        ├─ Gulu Node :8082                    │                         │
        │  (192.168.1.40)                     │                         │
        │                                     │                         │
        ├─ Jinja Node :8082                   │                         │
        │  (192.168.1.50)                     │                         │
        └─────────────────────────────────────┼─────────────────────────┘
                    │
                    └─────────────────────────┬──────────────────────────
                                              │
                    ┌───────────────────────────────────────────────────┐
                    │        Central Authority (Coordinator)            │
                    │                                                   │
                    │        Coordinator :8081                          │
                    │        (192.168.1.10)                             │
                    │                                                   │
                    │        Single Source of Truth                     │
                    │        SQLite Ledger (Per Shard)                  │
                    └───────────────────────────────────────────────────┘
```

**Key Points:**
- **1 Coordinator** = authoritative ledger (single point of truth)
- **4 Regional Nodes** = edge services in different regions
- **N Client Machines** = load simulators, testers, SMS/USSD apps
- **All regions query same coordinator** = immediate consistency (< 100ms)

### Prerequisites

On **every machine**:

```bash
# Install Python 3.10+
python3 --version

# Clone/copy the project
cd /path/to/Mobile-money

# Test the basic setup works locally first
./scripts/run_tests.sh  # Should see "OK"
```

### Network Setup

1. **Find machine IPs**:
   ```bash
   # On each machine, get its IP
   hostname -I
   # or on macOS:
   ifconfig | grep 'inet ' | head -1
   ```

2. **Verify connectivity** (from any machine):
   ```bash
   ping <other-machine-ip>
   ```

3. **Ensure no firewall blocks these ports**:
   - `8081`: Coordinator
   - `8082–8085`: Regional nodes
   - `8000`: Gateway (if using)

### Example: 6-Machine Setup

```
Machine A (192.168.1.10):  Coordinator
Machine B (192.168.1.20):  Regional node - Kampala
Machine C (192.168.1.30):  Regional node - Mbarara
Machine D (192.168.1.40):  Regional node - Gulu
Machine E (192.168.1.50):  Regional node - Jinja
Machine F (192.168.1.60):  Client simulator
```

Replace these IPs with your actual machine IPs.

### Step 1: Start Coordinator (Machine A: 192.168.1.10)

```bash
cd /path/to/Mobile-money
PYTHONPATH=src python3 -m mobile_money.main \
  --mode coordinator \
  --host 0.0.0.0 \
  --port 8081 \
  --db /tmp/uganda-ledger.sqlite3 \
  --regions kampala,mbarara,gulu,jinja
```

**Verify** (from any machine, including this one):
```bash
curl -s http://192.168.1.10:8081/health | python3 -m json.tool
```

Expected output:
```json
{
  "status": "ok",
  "service": "coordinator",
  "regions": ["kampala", "mbarara", "gulu", "jinja"]
}
```

### Step 2: Start Regional Nodes (Machines B, C, D, E)

**On Kampala machine (192.168.1.20)**:
```bash
cd /path/to/Mobile-money
PYTHONPATH=src python3 -m mobile_money.main \
  --mode regional \
  --region kampala \
  --host 0.0.0.0 \
  --port 8082 \
  --coordinator http://192.168.1.10:8081
```

**On Mbarara machine (192.168.1.30)**:
```bash
cd /path/to/Mobile-money
PYTHONPATH=src python3 -m mobile_money.main \
  --mode regional \
  --region mbarara \
  --host 0.0.0.0 \
  --port 8082 \
  --coordinator http://192.168.1.10:8081
```

**On Gulu machine (192.168.1.40)**:
```bash
cd /path/to/Mobile-money
PYTHONPATH=src python3 -m mobile_money.main \
  --mode regional \
  --region gulu \
  --host 0.0.0.0 \
  --port 8082 \
  --coordinator http://192.168.1.10:8081
```

**On Jinja machine (192.168.1.50)**:
```bash
cd /path/to/Mobile-money
PYTHONPATH=src python3 -m mobile_money.main \
  --mode regional \
  --region jinja \
  --host 0.0.0.0 \
  --port 8082 \
  --coordinator http://192.168.1.10:8081
```

**Verify all nodes are healthy** (from client machine or any other):
```bash
for ip in 192.168.1.20 192.168.1.30 192.168.1.40 192.168.1.50; do
  echo "Node at $ip:"
  curl -s http://$ip:8082/health | python3 -m json.tool
done
```

### Step 3: Run Interactive Client (Machine F: 192.168.1.60)

Connect to one regional node and use the guided interface:

```bash
cd /path/to/Mobile-money
PYTHONPATH=src python3 scripts/simulate_clients.py --interactive \
  --base-url http://192.168.1.20:8082
```

You'll be prompted:
```
Enter your phone number: +256701234567
```

Then the system auto-detects your region (Kampala) and shows you a menu for deposits, withdrawals, transfers, etc.

### Step 4: Concurrent Load Test (Machine F: 192.168.1.60)

Simulate 40 concurrent clients hitting all 4 regional nodes:

```bash
cd /path/to/Mobile-money
PYTHONPATH=src python3 scripts/simulate_clients.py \
  --clients 40 \
  --ops 20 \
  --node-urls http://192.168.1.20:8082,http://192.168.1.30:8082,http://192.168.1.40:8082,http://192.168.1.50:8082
```

**Output**:
```
Creating seed wallets...
[==========] Created 20 seed wallets
Running 40 clients x 20 ops = 800 total operations...
[████████████████████] 100% complete
Successful ops:        800 / 800
TPS:                   47.8 ops/sec
Latency p50:           89ms
Latency p95:           245ms
Latency p99:           512ms
Max latency:           713ms
All balances verify ✓
```

### Step 5: Cross-Region Test (Manual)

Test that a wallet created in one region can be read immediately from another.

**From Kampala machine (192.168.1.20), create wallet**:
```bash
WALLET_ID=$(curl -s -X POST http://localhost:8082/wallets \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"alice@test.ug","home_region":"kampala"}' | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")

echo "Created wallet: $WALLET_ID"
```

**Deposit from Kampala**:
```bash
curl -s -X POST http://localhost:8082/wallets/$WALLET_ID/deposit \
  -H 'Content-Type: application/json' \
  -d '{"amount":"1000.0000","request_id":"dep1"}' | python3 -m json.tool
```

**Read same wallet from Jinja machine (192.168.1.50)** (replace $WALLET_ID):
```bash
curl -s http://localhost:8082/wallets/$WALLET_ID | python3 -m json.tool
```

Expected: Jinja sees the updated balance immediately (1000.0000).

### Troubleshooting

| Problem | Solution |
|---------|----------|
| `Connection refused` | Machine IP is wrong, or service not running. Check `curl -v http://<ip>:8081/health` |
| `Network is unreachable` | Firewall blocking the port. Open 8081–8085. Or machines are on different networks. |
| `Timeout connecting to coordinator` | Regional node can't reach coordinator IP. Verify coordinator machine IP is correct. |
| Wallet created in Kampala but Mbarara says "wallet not found" | Expected—wallets are owned by the coordinator. All nodes query the same coordinator. If this happens, verify all nodes use same `--coordinator` URL. |
| Interactive client very slow | Normal if network latency is high (100+ ms per request). Increase `--clients` to lower per-op cost. |

---

## Multi-Machine Setup (4 Nodes + Many Clients)

### Topology

- 1 machine for coordinator (authoritative ledger)
- 4 machines for regional nodes:
	- Kampala node
	- Mbarara node
	- Gulu node
	- Jinja node
- Any number of separate client machines running curl or simulator

### 1) Start coordinator machine

On coordinator machine:

```bash
cd /home/jonah/Desktop/dp/uganda-mobile-money-python
PYTHONPATH=src /usr/bin/python3 -m mobile_money.main \
	--mode coordinator \
	--host 0.0.0.0 \
	--port 8081 \
	--db /tmp/uganda-ledger.sqlite3 \
	--regions kampala,mbarara,gulu,jinja
```

Health check from any machine:

```bash
curl -s http://<coordinator-ip>:8081/health
```

### 2) Start each regional node on different machines

On Kampala node machine:

```bash
cd /home/jonah/Desktop/dp/uganda-mobile-money-python
PYTHONPATH=src /usr/bin/python3 -m mobile_money.main \
	--mode regional \
	--region kampala \
	--host 0.0.0.0 \
	--port 8082 \
	--coordinator http://<coordinator-ip>:8081
```

On Mbarara node machine:

```bash
PYTHONPATH=src /usr/bin/python3 -m mobile_money.main --mode regional --region mbarara --host 0.0.0.0 --port 8082 --coordinator http://<coordinator-ip>:8081
```

On Gulu node machine:

```bash
PYTHONPATH=src /usr/bin/python3 -m mobile_money.main --mode regional --region gulu --host 0.0.0.0 --port 8082 --coordinator http://<coordinator-ip>:8081
```

On Jinja node machine:

```bash
PYTHONPATH=src /usr/bin/python3 -m mobile_money.main --mode regional --region jinja --host 0.0.0.0 --port 8082 --coordinator http://<coordinator-ip>:8081
```

### 3) Manual cross-node test from client machines

Create wallet through Mbarara node:

```bash
curl -s -X POST http://<mbarara-node-ip>:8082/wallets \
	-H 'Content-Type: application/json' \
	-d '{"user_id":"alice@example.com","home_region":"mbarara"}'
```

Deposit through Mbarara node:

```bash
curl -s -X POST http://<mbarara-node-ip>:8082/wallets/<WALLET_ID>/deposit \
	-H 'Content-Type: application/json' \
	-d '{"amount":"100.0000","request_id":"dep-1"}'
```

Read same wallet through Jinja node:

```bash
curl -s http://<jinja-node-ip>:8082/wallets/<WALLET_ID>
```

Expected: Jinja immediately reports the updated balance.

### 4) Concurrent multi-client test across all regional nodes

From any client machine:

```bash
cd /home/jonah/Desktop/dp/uganda-mobile-money-python
PYTHONPATH=src /usr/bin/python3 scripts/simulate_clients.py \
	--clients 40 \
	--ops 20 \
	--node-urls http://<kampala-node-ip>:8082,http://<mbarara-node-ip>:8082,http://<gulu-node-ip>:8082,http://<jinja-node-ip>:8082
```

The simulator will:

- create seed wallets
- run concurrent deposits, withdrawals, and transfers from multiple clients
- verify final balance consistency across all regional nodes

It also prints:

- successful TPS (throughput)
- latency p50, p95, and p99
- max observed operation latency

### 5) Validate services

Node health:

```bash
curl -s http://<kampala-node-ip>:8082/health
curl -s http://<mbarara-node-ip>:8082/health
curl -s http://<gulu-node-ip>:8082/health
curl -s http://<jinja-node-ip>:8082/health
```

Coordinator regions state:

```bash
curl -s http://<coordinator-ip>:8081/regions
```

## Example flow

1. Create a wallet in Mbarara.
2. Deposit money through the Mbarara node (write routed to coordinator).
3. Query the same wallet from Jinja node.
4. Jinja sees updated balance because every read and write resolves through the same authoritative ledger.

## Test With Different Nodes And Clients
Use the multi-machine setup above for the exact workflow.

