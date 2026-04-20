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


def interactive_session() -> None:
    base_url = prompt_input("Enter the node or coordinator URL", default="http://127.0.0.1:8082")
    phone_number = prompt_input("Enter your phone number")
    home_region = prompt_region("Enter your home region", default="kampala")
    wallet_directory: dict[str, str] = {}

    wallet_id = create_wallet(base_url, phone_number, home_region)
    wallet_directory[phone_number] = wallet_id
    print(f"Wallet created for {phone_number}: {wallet_id}")

    while True:
        print()
        print("Select an action:")
        print("  1) Check balance")
        print("  2) Deposit")
        print("  3) Withdraw")
        print("  4) Transfer")
        print("  5) Show transactions")
        print("  6) Exit")
        choice = prompt_input("Choose an option")

        if choice == "1":
            wallet = get_wallet(base_url, wallet_id)
            print(f"Balance for {phone_number}: {wallet['balance']}")
            continue

        if choice == "2":
            amount = prompt_amount("Enter deposit amount")
            region = prompt_region("Enter the region to use", default=home_region)
            receipt = do_deposit(base_url, region, wallet_id, amount, f"interactive-deposit-{phone_number}")
            print(f"Deposit successful. New balance: {receipt['wallet']['balance']}")
            continue

        if choice == "3":
            amount = prompt_amount("Enter withdrawal amount")
            region = prompt_region("Enter the region to use", default=home_region)
            receipt = do_withdraw(base_url, region, wallet_id, amount, f"interactive-withdraw-{phone_number}")
            print(f"Withdrawal successful. New balance: {receipt['wallet']['balance']}")
            continue

        if choice == "4":
            recipient_phone = prompt_input("Enter recipient phone number")
            recipient_wallet = wallet_directory.get(recipient_phone)
            if recipient_wallet is None:
                recipient_region = prompt_region("Enter recipient home region", default=home_region)
                recipient_wallet = create_wallet(base_url, recipient_phone, recipient_region)
                wallet_directory[recipient_phone] = recipient_wallet
            amount = prompt_amount("Enter transfer amount")
            region = prompt_region("Enter the region to use", default=home_region)
            receipt = do_transfer(
                base_url,
                region,
                wallet_id,
                recipient_wallet,
                amount,
                f"interactive-transfer-{phone_number}",
            )
            print(
                "Transfer successful. "
                f"Sender balance: {receipt['from_wallet']['balance']}, "
                f"recipient balance: {receipt['to_wallet']['balance']}"
            )
            continue

        if choice == "5":
            transactions = http_json("GET", f"{base_url}/wallets/{wallet_id}/transactions")
            print(json.dumps(transactions, indent=2, sort_keys=True))
            continue

        if choice == "6":
            print("Goodbye.")
            return

        print("Choose a valid option from the menu.")


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
        interactive_session()
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
