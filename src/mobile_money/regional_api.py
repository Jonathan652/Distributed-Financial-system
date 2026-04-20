from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from .http_utils import request_json


class RegionalNodeState:
    def __init__(self, region: str, coordinator_url: str) -> None:
        self.region = region
        self.coordinator_url = coordinator_url.rstrip("/")
        self.wallet_cache: dict[str, dict[str, Any]] = {}
        self.lock = threading.RLock()

    def update_cache(self, wallet_payload: dict[str, Any]) -> None:
        with self.lock:
            self.wallet_cache[wallet_payload["id"]] = wallet_payload

    def get_cached_wallet(self, wallet_id: str) -> dict[str, Any] | None:
        with self.lock:
            return self.wallet_cache.get(wallet_id)

    def cache_stats(self) -> dict[str, Any]:
        with self.lock:
            return {"cached_wallets": len(self.wallet_cache)}


class RegionalAPI(BaseHTTPRequestHandler):
    state: RegionalNodeState | None = None

    def do_GET(self) -> None:
        try:
            if self.path == "/health":
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

            if self.path.startswith("/wallets/") and self.path.endswith("/transactions"):
                wallet_id = self.path.split("/")[2]
                payload = request_json("GET", f"{self.state.coordinator_url}/wallets/{wallet_id}/transactions")
                self._send_json(200, payload)
                return

            if self.path.startswith("/wallets/"):
                wallet_id = self.path.split("/")[2]
                payload = request_json(
                    "GET",
                    f"{self.state.coordinator_url}/wallets/{wallet_id}?region={self.state.region}",
                )
                self.state.update_cache(payload)
                self._send_json(200, payload)
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
                forward = {
                    "user_id": payload["user_id"],
                    "home_region": payload.get("home_region", self.state.region),
                }
                created = request_json("POST", f"{self.state.coordinator_url}/wallets", forward)
                self.state.update_cache(created)
                self._send_json(201, created)
                return

            if self.path.startswith("/wallets/") and self.path.endswith("/deposit"):
                wallet_id = self.path.split("/")[2]
                receipt = request_json(
                    "POST",
                    f"{self.state.coordinator_url}/deposit",
                    {
                        "region": self.state.region,
                        "wallet_id": wallet_id,
                        "amount": payload["amount"],
                        "request_id": payload.get("request_id"),
                    },
                )
                self.state.update_cache(receipt["wallet"])
                self._send_json(200, receipt)
                return

            if self.path.startswith("/wallets/") and self.path.endswith("/withdraw"):
                wallet_id = self.path.split("/")[2]
                receipt = request_json(
                    "POST",
                    f"{self.state.coordinator_url}/withdraw",
                    {
                        "region": self.state.region,
                        "wallet_id": wallet_id,
                        "amount": payload["amount"],
                        "request_id": payload.get("request_id"),
                    },
                )
                self.state.update_cache(receipt["wallet"])
                self._send_json(200, receipt)
                return

            if self.path == "/transfers":
                receipt = request_json(
                    "POST",
                    f"{self.state.coordinator_url}/transfer",
                    {
                        "region": self.state.region,
                        "from_wallet_id": payload["from_wallet_id"],
                        "to_wallet_id": payload["to_wallet_id"],
                        "amount": payload["amount"],
                        "request_id": payload.get("request_id"),
                    },
                )
                self.state.update_cache(receipt["from_wallet"])
                self.state.update_cache(receipt["to_wallet"])
                self._send_json(200, receipt)
                return

            self._send_json(404, {"error": "Not found"})
        except Exception as exc:  # pragma: no cover
            self._send_json(400, {"error": str(exc)})

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def create_regional_server(host: str, port: int, region: str, coordinator_url: str) -> HTTPServer:
    RegionalAPI.state = RegionalNodeState(region=region, coordinator_url=coordinator_url)
    return HTTPServer((host, port), RegionalAPI)
