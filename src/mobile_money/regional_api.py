from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import uuid4

from .http_utils import HttpRequestError, request_json


class RegionalNodeState:
    def __init__(self, region: str, coordinator_urls: list[str]) -> None:
        self.region = region
        if not coordinator_urls:
            raise ValueError("At least one coordinator URL is required")

        self.coordinator_urls = [url.rstrip("/") for url in coordinator_urls]
        self.wallet_cache: dict[str, dict[str, Any]] = {}
        self.wallet_owners: dict[str, str] = {}
        self.coordinator_health: dict[str, bool] = {url: True for url in self.coordinator_urls}
        self._last_health_refresh = 0.0
        self._health_ttl_seconds = 3.0
        self.lock = threading.RLock()

    def update_cache(self, wallet_payload: dict[str, Any]) -> None:
        with self.lock:
            self.wallet_cache[wallet_payload["id"]] = wallet_payload

    def get_cached_wallet(self, wallet_id: str) -> dict[str, Any] | None:
        with self.lock:
            return self.wallet_cache.get(wallet_id)

    def remember_wallet_owner(self, wallet_id: str, coordinator_url: str) -> None:
        with self.lock:
            self.wallet_owners[wallet_id] = coordinator_url

    def get_wallet_owner(self, wallet_id: str) -> str | None:
        with self.lock:
            return self.wallet_owners.get(wallet_id)

    def pick_create_coordinator(self, user_id: str, home_region: str) -> str:
        # Deterministic placement ensures clients choose the same coordinator for retries.
        key = f"{home_region}:{user_id}"
        slot = sum(key.encode("utf-8")) % len(self.coordinator_urls)
        ordered = self.coordinator_urls[slot:] + self.coordinator_urls[:slot]

        self._refresh_health_if_stale()
        healthy = [url for url in ordered if self.coordinator_health.get(url, False)]
        if healthy:
            return healthy[0]
        return ordered[0]

    def cache_stats(self) -> dict[str, Any]:
        with self.lock:
            return {
                "cached_wallets": len(self.wallet_cache),
                "known_wallet_owners": len(self.wallet_owners),
                "coordinator_count": len(self.coordinator_urls),
                "healthy_coordinators": sum(1 for value in self.coordinator_health.values() if value),
            }

    def resolve_wallet_owner(self, wallet_id: str) -> str:
        known = self.get_wallet_owner(wallet_id)
        if known is not None and self._coordinator_healthy(known):
            return known

        self.forget_wallet_owner(wallet_id)

        self._refresh_health_if_stale()
        ordered = sorted(self.coordinator_urls, key=lambda url: self.coordinator_health.get(url, False), reverse=True)
        errors: list[str] = []

        for coordinator_url in ordered:
            if not self.coordinator_health.get(coordinator_url, False):
                errors.append(f"{coordinator_url}: unavailable")
                continue

            try:
                payload = request_json(
                    "GET",
                    f"{coordinator_url}/wallets/{wallet_id}?region={self.region}",
                )
                self.update_cache(payload)
                self.remember_wallet_owner(wallet_id, coordinator_url)
                return coordinator_url
            except HttpRequestError as exc:
                message = str(exc)
                if self._error_is_wallet_not_found(message):
                    # Wallet exists on another shard, continue scan.
                    continue
                if self._error_is_connection_issue(message):
                    self._set_coordinator_health(coordinator_url, False)
                    errors.append(f"{coordinator_url}: connection issue")
                    continue
                errors.append(f"{coordinator_url}: {message}")

        if errors and len(errors) == len(self.coordinator_urls):
            raise RuntimeError("All coordinators are unavailable")

        raise ValueError(f"Wallet not found: {wallet_id}")

    def forget_wallet_owner(self, wallet_id: str) -> None:
        with self.lock:
            self.wallet_owners.pop(wallet_id, None)

    def _coordinator_healthy(self, coordinator_url: str) -> bool:
        self._refresh_health_if_stale()
        return self.coordinator_health.get(coordinator_url, False)

    def _refresh_health_if_stale(self) -> None:
        now = time.monotonic()
        with self.lock:
            if now - self._last_health_refresh < self._health_ttl_seconds:
                return

        for coordinator_url in self.coordinator_urls:
            healthy = self._probe_coordinator_health(coordinator_url)
            self._set_coordinator_health(coordinator_url, healthy)

        with self.lock:
            self._last_health_refresh = now

    def _set_coordinator_health(self, coordinator_url: str, healthy: bool) -> None:
        with self.lock:
            self.coordinator_health[coordinator_url] = healthy

    def _probe_coordinator_health(self, coordinator_url: str) -> bool:
        try:
            payload = request_json("GET", f"{coordinator_url}/health", timeout=1)
            return payload.get("status") == "ok"
        except Exception:
            return False

    @staticmethod
    def _error_is_wallet_not_found(message: str) -> bool:
        return "Wallet not found" in message

    @staticmethod
    def _error_is_connection_issue(message: str) -> bool:
        return "Connection failed" in message


class RegionalAPI(BaseHTTPRequestHandler):
    state: RegionalNodeState | None = None

    def do_GET(self) -> None:
        try:
            clean_path = self.path.split("?", 1)[0]

            if clean_path == "/health":
                self._send_json(
                    200,
                    {
                        "status": "ok",
                        "service": "regional-node",
                        "region": self.state.region,
                        **self.state.cache_stats(),
                    },
                )
                return

            if clean_path == "/wallets":
                user_id = self._query_param("user_id")
                if user_id:
                    coordinator_url = self.state.coordinator_urls[0]
                    payload = request_json("GET", f"{coordinator_url}/wallets?user_id={user_id}")
                    self._send_json(200, payload)
                    return
                self._send_json(400, {"error": "user_id query parameter required"})
                return

            if clean_path.startswith("/wallets/") and clean_path.endswith("/transactions"):
                wallet_id = clean_path.split("/")[2]
                coordinator_url = self.state.resolve_wallet_owner(wallet_id)
                payload = self._request_with_owner_fallback(
                    wallet_id,
                    "GET",
                    f"{coordinator_url}/wallets/{wallet_id}/transactions",
                )
                self._send_json(200, payload)
                return

            if clean_path.startswith("/wallets/"):
                wallet_id = clean_path.split("/")[2]
                coordinator_url = self.state.resolve_wallet_owner(wallet_id)
                payload = request_json(
                    "GET",
                    f"{coordinator_url}/wallets/{wallet_id}?region={self.state.region}",
                )
                self.state.update_cache(payload)
                self.state.remember_wallet_owner(wallet_id, coordinator_url)
                self._send_json(200, payload)
                return

            if clean_path == "/coordinators":
                self._send_json(
                    200,
                    {
                        "coordinators": [
                            {"url": url, "healthy": self.state.coordinator_health.get(url, True)}
                            for url in self.state.coordinator_urls
                        ]
                    },
                )
                return

            if self.path == "/cache":
                self._send_json(200, self.state.cache_stats())
                return

            self._send_json(404, {"error": "Not found"})
        except Exception as exc:  # pragma: no cover
            self._send_json(400, {"error": str(exc)})

    def do_POST(self) -> None:
        try:
            payload = self._read_json_body()

            if self.path == "/wallets":
                home_region = payload.get("home_region", self.state.region)
                coordinator_url = self.state.pick_create_coordinator(payload["user_id"], home_region)
                forward = {
                    "user_id": payload["user_id"],
                    "home_region": home_region,
                }
                created = None
                ordered = [coordinator_url] + [url for url in self.state.coordinator_urls if url != coordinator_url]
                last_error: Exception | None = None
                for candidate in ordered:
                    try:
                        created = request_json("POST", f"{candidate}/wallets", forward)
                        coordinator_url = candidate
                        break
                    except Exception as exc:
                        last_error = exc
                        self.state._set_coordinator_health(candidate, False)

                if created is None:
                    raise RuntimeError("No coordinator is available for wallet creation") from last_error

                self.state.update_cache(created)
                self.state.remember_wallet_owner(created["id"], coordinator_url)
                self._send_json(201, created)
                return

            if self.path.startswith("/wallets/") and self.path.endswith("/deposit"):
                wallet_id = self.path.split("/")[2]
                coordinator_url = self.state.resolve_wallet_owner(wallet_id)
                receipt = self._request_with_owner_fallback(
                    wallet_id,
                    "POST",
                    f"{coordinator_url}/deposit",
                    {
                        "region": self.state.region,
                        "wallet_id": wallet_id,
                        "amount": payload["amount"],
                        "request_id": payload.get("request_id"),
                    },
                )
                self.state.update_cache(receipt["wallet"])
                self.state.remember_wallet_owner(wallet_id, self.state.resolve_wallet_owner(wallet_id))
                self._send_json(200, receipt)
                return

            if self.path.startswith("/wallets/") and self.path.endswith("/withdraw"):
                wallet_id = self.path.split("/")[2]
                coordinator_url = self.state.resolve_wallet_owner(wallet_id)
                receipt = self._request_with_owner_fallback(
                    wallet_id,
                    "POST",
                    f"{coordinator_url}/withdraw",
                    {
                        "region": self.state.region,
                        "wallet_id": wallet_id,
                        "amount": payload["amount"],
                        "request_id": payload.get("request_id"),
                    },
                )
                self.state.update_cache(receipt["wallet"])
                self.state.remember_wallet_owner(wallet_id, self.state.resolve_wallet_owner(wallet_id))
                self._send_json(200, receipt)
                return

            if self.path == "/transfers":
                from_wallet_id = payload["from_wallet_id"]
                to_wallet_id = payload["to_wallet_id"]
                from_coordinator = self.state.resolve_wallet_owner(from_wallet_id)
                to_coordinator = self.state.resolve_wallet_owner(to_wallet_id)

                if from_coordinator == to_coordinator:
                    receipt = request_json(
                        "POST",
                        f"{from_coordinator}/transfer",
                        {
                            "region": self.state.region,
                            "from_wallet_id": from_wallet_id,
                            "to_wallet_id": to_wallet_id,
                            "amount": payload["amount"],
                            "request_id": payload.get("request_id"),
                        },
                    )
                else:
                    receipt = self._cross_shard_transfer(
                        from_coordinator=from_coordinator,
                        to_coordinator=to_coordinator,
                        from_wallet_id=from_wallet_id,
                        to_wallet_id=to_wallet_id,
                        amount=payload["amount"],
                        request_id=payload.get("request_id"),
                    )

                self.state.update_cache(receipt["from_wallet"])
                self.state.update_cache(receipt["to_wallet"])
                self.state.remember_wallet_owner(from_wallet_id, from_coordinator)
                self.state.remember_wallet_owner(to_wallet_id, to_coordinator)
                self._send_json(200, receipt)
                return

            self._send_json(404, {"error": "Not found"})
        except Exception as exc:  # pragma: no cover
            self._send_json(400, {"error": str(exc)})

    def _request_with_owner_fallback(
        self,
        wallet_id: str,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            return request_json(method, url, payload)
        except HttpRequestError as exc:
            if not self.state._error_is_connection_issue(str(exc)):
                raise

        self.state.forget_wallet_owner(wallet_id)
        coordinator_url = self.state.resolve_wallet_owner(wallet_id)
        if method == "GET":
            retry_url = f"{coordinator_url}/wallets/{wallet_id}?region={self.state.region}"
            if url.endswith("/transactions"):
                retry_url = f"{coordinator_url}/wallets/{wallet_id}/transactions"
            return request_json(method, retry_url, payload)

        if url.endswith("/deposit"):
            return request_json(method, f"{coordinator_url}/deposit", payload)

        if url.endswith("/withdraw"):
            return request_json(method, f"{coordinator_url}/withdraw", payload)

        return request_json(method, url, payload)

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _query_param(self, param_name: str) -> str | None:
        if "?" not in self.path:
            return None
        query = self.path.split("?", 1)[1]
        for part in query.split("&"):
            key, _, value = part.partition("=")
            if key == param_name:
                return value
        return None

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _cross_shard_transfer(
        self,
        from_coordinator: str,
        to_coordinator: str,
        from_wallet_id: str,
        to_wallet_id: str,
        amount: Any,
        request_id: str | None,
    ) -> dict[str, Any]:
        base_request_id = request_id or str(uuid4())
        withdraw_id = f"{base_request_id}:xfer:out"
        deposit_id = f"{base_request_id}:xfer:in"
        compensation_id = f"{base_request_id}:xfer:refund"

        withdrawn = request_json(
            "POST",
            f"{from_coordinator}/withdraw",
            {
                "region": self.state.region,
                "wallet_id": from_wallet_id,
                "amount": amount,
                "request_id": withdraw_id,
            },
        )

        try:
            deposited = request_json(
                "POST",
                f"{to_coordinator}/deposit",
                {
                    "region": self.state.region,
                    "wallet_id": to_wallet_id,
                    "amount": amount,
                    "request_id": deposit_id,
                },
            )
        except Exception as exc:
            try:
                request_json(
                    "POST",
                    f"{from_coordinator}/deposit",
                    {
                        "region": self.state.region,
                        "wallet_id": from_wallet_id,
                        "amount": amount,
                        "request_id": compensation_id,
                    },
                )
            except Exception as refund_exc:
                raise RuntimeError(
                    "Cross-shard transfer failed and compensation also failed; manual reconciliation required"
                ) from refund_exc
            raise RuntimeError("Cross-shard transfer failed; source wallet has been compensated") from exc

        return {
            "from_wallet": withdrawn["wallet"],
            "to_wallet": deposited["wallet"],
            "out_transaction": withdrawn["transaction"],
            "in_transaction": deposited["transaction"],
        }


def create_regional_server(
    host: str,
    port: int,
    region: str,
    coordinator_url: str,
    coordinator_urls: list[str] | None = None,
) -> ThreadingHTTPServer:
    urls = coordinator_urls if coordinator_urls is not None else [coordinator_url]
    RegionalAPI.state = RegionalNodeState(region=region, coordinator_urls=urls)
    return ThreadingHTTPServer((host, port), RegionalAPI)
