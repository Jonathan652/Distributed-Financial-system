# Uganda Mobile Money Reference

This project is a Python reference implementation of a regional mobile money architecture.

It keeps one authoritative ledger for strong consistency and lets regional nodes in places like Kampala, Mbarara, Gulu, and Jinja serve traffic locally while synchronizing wallet state immediately after every committed transaction.

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

