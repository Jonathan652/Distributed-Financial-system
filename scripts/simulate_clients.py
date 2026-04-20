from __future__ import annotations

import argparse
import json
import math
import random
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


REGIONS = ["kampala", "mbarara", "gulu", "jinja"]
DEFAULT_INTERACTIVE_NODE_URLS = [
    "http://127.0.0.1:8082",
    "http://127.0.0.1:8084",
]


def print_header(title: str) -> None:
    print("\n" + "=" * 68)
    print(title)
    print("=" * 68)


def print_kv(key: str, value: str) -> None:
    print(f"{key:<24}: {value}")


def print_receipt(title: str, payload: dict) -> None:
    print_header(title)
    if "wallet" in payload:
        wallet = payload["wallet"]
        print_kv("Wallet ID", wallet["id"])
        print_kv("Balance", wallet["balance"])
        print_kv("Version", str(wallet.get("version", "-")))
    if "from_wallet" in payload and "to_wallet" in payload:
        print_kv("From Wallet", payload["from_wallet"]["id"])
        print_kv("From Balance", payload["from_wallet"]["balance"])
        print_kv("To Wallet", payload["to_wallet"]["id"])
        print_kv("To Balance", payload["to_wallet"]["balance"])
    if "transaction" in payload:
        txn = payload["transaction"]
        print_kv("Transaction ID", txn["id"])
        print_kv("Transaction Type", txn["transaction_type"])
        print_kv("Status", txn["status"])
    print("-" * 68)


def http_json(method: str, url: str, payload: dict | None = None) -> dict:
    body = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url=url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            content = response.read().decode("utf-8")
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8")
        raise RuntimeError(f"HTTP {err.code} for {url}: {detail}") from err


def create_wallet(base_url: str, user_id: str, home_region: str) -> str:
    result = http_json(
        "POST",
        f"{base_url}/wallets",
        {"user_id": user_id, "home_region": home_region},
    )
    return result["id"]


def get_or_create_wallet(base_url: str, user_id: str, home_region: str) -> str:
    """Look up existing wallet by user_id, or create a new one if none exists."""
    try:
        result = http_json("GET", f"{base_url}/wallets?user_id={user_id}")
        wallets = result.get("wallets", [])
        if wallets:
            return wallets[0]["id"]
    except Exception:
        pass

    return create_wallet(base_url, user_id, home_region)


def get_wallet(base_url: str, wallet_id: str) -> dict:
    return http_json("GET", f"{base_url}/wallets/{wallet_id}")


def do_deposit(base_url: str, region: str, wallet_id: str, amount: str, request_id: str) -> dict:
    return http_json(
        "POST",
        f"{base_url}/wallets/{wallet_id}/deposit",
        {"amount": amount, "request_id": request_id},
    )


def do_withdraw(base_url: str, region: str, wallet_id: str, amount: str, request_id: str) -> dict:
    return http_json(
        "POST",
        f"{base_url}/wallets/{wallet_id}/withdraw",
        {"amount": amount, "request_id": request_id},
    )


def do_transfer(
    base_url: str,
    region: str,
    from_wallet_id: str,
    to_wallet_id: str,
    amount: str,
    request_id: str,
) -> dict:
    return http_json(
        "POST",
        f"{base_url}/transfers",
        {
            "from_wallet_id": from_wallet_id,
            "to_wallet_id": to_wallet_id,
            "amount": amount,
            "request_id": request_id,
        },
    )


def prompt_input(prompt: str, default: str | None = None, allow_empty: bool = False) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        value = input(f"{prompt}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        if allow_empty:
            return ""
        print("Please enter a value.")


def prompt_region(prompt: str, default: str | None = None) -> str:
    region = prompt_input(prompt, default=default)
    while region not in REGIONS:
        print(f"Choose one of: {', '.join(REGIONS)}")
        region = prompt_input(prompt, default=default)
    return region


def prompt_amount(prompt: str) -> str:
    while True:
        amount = prompt_input(prompt)
        try:
            value = float(amount)
        except ValueError:
            print("Enter a valid numeric amount.")
            continue

        if value <= 0:
            print("Amount must be greater than zero.")
            continue

        return f"{value:.4f}"


def infer_region_from_node(node_url: str) -> str:
    """Infer user's region from which regional node they're connecting to."""
    try:
        payload = http_json("GET", f"{node_url}/health")
        return payload.get("region", "kampala")
    except Exception:
        return "kampala"


def choose_preferred_node(home_region: str, node_urls: list[str]) -> str:
    if not node_urls:
        raise ValueError("At least one node URL is required")
    slot = sum(home_region.encode("utf-8")) % len(node_urls)
    return node_urls[slot]


def select_healthy_node(node_urls: list[str], preferred: str | None = None) -> str:
    ordered = node_urls
    if preferred is not None and preferred in node_urls:
        ordered = [preferred] + [url for url in node_urls if url != preferred]

    for node_url in ordered:
        try:
            payload = http_json("GET", f"{node_url}/health")
            if payload.get("status") == "ok":
                return node_url
        except Exception:
            continue

    raise RuntimeError("No healthy regional node available")


def interactive_session(node_urls: list[str]) -> None:
    print_header("Mobile Money Guided Client")
    print("Simple and quick. System figures out everything else.")

    phone_number = prompt_input("Enter your phone number")

    preferred_node = choose_preferred_node("kampala", node_urls)
    active_node = select_healthy_node(node_urls, preferred=preferred_node)
    home_region = infer_region_from_node(active_node)
    
    wallet_directory: dict[str, str] = {}

    print_header("Creating Your Wallet")
    print_kv("Phone Number", phone_number)
    print_kv("Home Region (auto-detected from node)", home_region)
    print_kv("Connected Node", active_node)
    wallet_id = get_or_create_wallet(active_node, phone_number, home_region)
    wallet_directory[phone_number] = wallet_id
    print_kv("Wallet ID", wallet_id)
    print("Wallet ready.")

    while True:
        print_header("Main Menu")
        print("1) Check balance")
        print("2) Deposit")
        print("3) Withdraw")
        print("4) Transfer")
        print("5) Show transactions")
        print("6) Exit")
        choice = prompt_input("Enter option number")

        if choice == "1":
            active_node = select_healthy_node(node_urls, preferred=preferred_node)
            wallet = get_wallet(active_node, wallet_id)
            print_header("Balance")
            print_kv("Phone Number", phone_number)
            print_kv("Wallet ID", wallet_id)
            print_kv("Current Balance", wallet["balance"])
            print_kv("Served By Node", active_node)
            continue

        if choice == "2":
            print_header("Deposit Details")
            amount = prompt_amount("Enter amount to deposit")
            active_node = select_healthy_node(node_urls, preferred=preferred_node)
            receipt = do_deposit(active_node, home_region, wallet_id, amount, f"interactive-deposit-{phone_number}")
            print_receipt("Deposit Successful", receipt)
            print_kv("Served By Node", active_node)
            continue

        if choice == "3":
            print_header("Withdrawal Details")
            amount = prompt_amount("Enter amount to withdraw")
            active_node = select_healthy_node(node_urls, preferred=preferred_node)
            receipt = do_withdraw(
                active_node,
                home_region,
                wallet_id,
                amount,
                f"interactive-withdraw-{phone_number}",
            )
            print_receipt("Withdrawal Successful", receipt)
            print_kv("Served By Node", active_node)
            continue

        if choice == "4":
            print_header("Transfer Details")
            active_node = select_healthy_node(node_urls, preferred=preferred_node)
            recipient_phone = prompt_input("Enter recipient phone number")
            recipient_wallet = wallet_directory.get(recipient_phone)
            if recipient_wallet is None:
                recipient_region = infer_region_from_node(active_node)
                recipient_wallet = get_or_create_wallet(active_node, recipient_phone, recipient_region)
                wallet_directory[recipient_phone] = recipient_wallet
                print_kv("Recipient Wallet ID", recipient_wallet)
            amount = prompt_amount("Enter amount to transfer")
            receipt = do_transfer(
                active_node,
                home_region,
                wallet_id,
                recipient_wallet,
                amount,
                f"interactive-transfer-{phone_number}",
            )
            print_receipt("Transfer Successful", receipt)
            print_kv("Served By Node", active_node)
            continue

        if choice == "5":
            active_node = select_healthy_node(node_urls, preferred=preferred_node)
            transactions = http_json("GET", f"{active_node}/wallets/{wallet_id}/transactions")
            print_header("Transaction History")
            print_kv("Wallet ID", wallet_id)
            print_kv("Served By Node", active_node)
            entries = transactions.get("transactions", [])
            print_kv("Total Transactions", str(len(entries)))
            if not entries:
                print("No transactions found.")
            else:
                for index, item in enumerate(entries, start=1):
                    print("-" * 68)
                    print_kv("Entry", str(index))
                    print_kv("Type", item["transaction_type"])
                    print_kv("Amount", item["amount"])
                    print_kv("Status", item["status"])
                    print_kv("Region", item["region"])
                    print_kv("Transaction ID", item["id"])
            continue

        if choice == "6":
            print_header("Session Closed")
            print("Goodbye.")
            return

        print("Invalid option. Please enter a number from 1 to 6.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate concurrent clients across regional nodes")
    parser.add_argument("--base-url", default="http://127.0.0.1:8082")
    parser.add_argument(
        "--node-urls",
        default="",
        help="Comma-separated regional node URLs. If omitted, --base-url is used.",
    )
    parser.add_argument("--clients", type=int, default=10)
    parser.add_argument("--ops", type=int, default=10, help="Operations per client")
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run a guided client session instead of the concurrent simulator",
    )
    args = parser.parse_args()

    if args.interactive:
        node_urls = [args.base_url.rstrip("/")]
        if args.node_urls.strip():
            node_urls = [url.strip().rstrip("/") for url in args.node_urls.split(",") if url.strip()]
        elif args.base_url == "http://127.0.0.1:8082":
            node_urls = DEFAULT_INTERACTIVE_NODE_URLS

        interactive_session(node_urls=node_urls)
        return

    random.seed(42)
    lock = threading.Lock()
    wallets: list[str] = []
    node_urls = [args.base_url]
    if args.node_urls.strip():
        node_urls = [url.strip().rstrip("/") for url in args.node_urls.split(",") if url.strip()]

    print("Creating seed wallets...")
    for i in range(max(4, args.clients // 2)):
        region = REGIONS[i % len(REGIONS)]
        node = random.choice(node_urls)
        wallet_id = create_wallet(node, f"user-{i}@example.com", region)
        wallets.append(wallet_id)
        do_deposit(node, region, wallet_id, "100.0000", f"seed-dep-{i}")

    failures = 0
    successes = 0
    latencies_ms: list[float] = []

    def worker(client_id: int) -> None:
        nonlocal failures, successes
        for op_index in range(args.ops):
            op = random.choice(["deposit", "withdraw", "transfer"])
            region = random.choice(REGIONS)
            request_id = f"c{client_id}-op{op_index}-{op}"
            node = random.choice(node_urls)
            op_start = time.perf_counter()
            try:
                if op == "deposit":
                    wallet_id = random.choice(wallets)
                    amount = random.choice(["1.0000", "2.5000", "5.0000"])
                    do_deposit(node, region, wallet_id, amount, request_id)

                elif op == "withdraw":
                    wallet_id = random.choice(wallets)
                    amount = random.choice(["1.0000", "2.0000", "3.0000"])
                    do_withdraw(node, region, wallet_id, amount, request_id)

                else:
                    from_wallet = random.choice(wallets)
                    to_wallet = random.choice(wallets)
                    if from_wallet == to_wallet:
                        continue
                    amount = random.choice(["0.5000", "1.0000", "1.5000"])
                    do_transfer(node, region, from_wallet, to_wallet, amount, request_id)

                with lock:
                    successes += 1
                    latencies_ms.append((time.perf_counter() - op_start) * 1000)
            except Exception:
                with lock:
                    failures += 1

    print(f"Running {args.clients} clients x {args.ops} operations...")
    start = time.time()
    with ThreadPoolExecutor(max_workers=args.clients) as pool:
        futures = [pool.submit(worker, i) for i in range(args.clients)]
        for future in as_completed(futures):
            future.result()
    duration = time.time() - start

    print(f"Completed in {duration:.2f}s")
    print(f"Successful operations: {successes}")
    print(f"Failed operations (expected some due to insufficient funds/offline nodes): {failures}")
    if duration > 0:
        print(f"Throughput (successful TPS): {successes / duration:.2f}")

    if latencies_ms:
        sorted_latencies = sorted(latencies_ms)

        def percentile(values: list[float], p: float) -> float:
            if not values:
                return 0.0
            rank = max(0, min(len(values) - 1, math.ceil((p / 100.0) * len(values)) - 1))
            return values[rank]

        print(f"Latency p50 (ms): {percentile(sorted_latencies, 50):.2f}")
        print(f"Latency p95 (ms): {percentile(sorted_latencies, 95):.2f}")
        print(f"Latency p99 (ms): {percentile(sorted_latencies, 99):.2f}")
        print(f"Latency max (ms): {sorted_latencies[-1]:.2f}")

    print("Validating wallet balance consistency across all regions...")
    inconsistencies = 0
    for wallet_id in wallets:
        views = [get_wallet(node, wallet_id)["balance"] for node in node_urls]
        if len(set(views)) != 1:
            inconsistencies += 1
            print(f"Inconsistent wallet {wallet_id}: {views}")

    if inconsistencies == 0:
        print("Consistency check passed: all wallets match across all regions.")
    else:
        print(f"Consistency check failed for {inconsistencies} wallet(s).")


if __name__ == "__main__":
    main()
