from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .console import format_request_log
from .http_utils import HttpRequestError, request_json


class GatewayState:
    """Gateway routing state: knows about all regional nodes and distributed coordinators."""

    def __init__(self, regional_node_urls: list[str], coordinator_urls: list[str]) -> None:
        if not regional_node_urls:
            raise ValueError("At least one regional node URL is required")
        if not coordinator_urls:
            raise ValueError("At least one coordinator URL is required")

        self.regional_node_urls = [url.rstrip("/") for url in regional_node_urls]
        self.coordinator_urls = [url.rstrip("/") for url in coordinator_urls]
        self.wallet_owners: dict[str, str] = {}  # wallet_id → regional_node_url
        self.user_regions: dict[str, str] = {}  # user_id → region
        self.lock = threading.RLock()

    def remember_wallet_owner(self, wallet_id: str, regional_node_url: str) -> None:
        with self.lock:
            self.wallet_owners[wallet_id] = regional_node_url

    def get_wallet_owner(self, wallet_id: str) -> str | None:
        with self.lock:
            return self.wallet_owners.get(wallet_id)

    def remember_user_region(self, user_id: str, region: str) -> None:
        with self.lock:
            self.user_regions[user_id] = region

    def get_user_region(self, user_id: str) -> str | None:
        with self.lock:
            return self.user_regions.get(user_id)

    def pick_regional_node_for_creation(self, user_id: str) -> str:
        """Deterministically pick a regional node for wallet creation."""
        slot = sum(user_id.encode("utf-8")) % len(self.regional_node_urls)
        return self.regional_node_urls[slot]

    def resolve_wallet_owner_node(self, wallet_id: str) -> str:
        """Find which regional node owns this wallet."""
        known = self.get_wallet_owner(wallet_id)
        if known is not None:
            return known

        for regional_node_url in self.regional_node_urls:
            try:
                payload = request_json("GET", f"{regional_node_url}/wallets/{wallet_id}")
                self.remember_wallet_owner(wallet_id, regional_node_url)
                return regional_node_url
            except HttpRequestError:
                continue

        raise ValueError(f"Wallet not found: {wallet_id}")


class GatewayAPI(BaseHTTPRequestHandler):
    state: GatewayState | None = None

    def log_message(self, format: str, *args: Any) -> None:
        client_ip = self.client_address[0] if self.client_address else "-"
        status = str(args[1]) if len(args) > 1 else "-"
        request_line = str(args[0]).strip('"') if args else self.requestline
        print(format_request_log("gateway", client_ip, request_line, status))

    def do_GET(self) -> None:
        try:
            clean_path = self.path.split("?", 1)[0]

            if clean_path == "/health":
                self._send_json(200, {"status": "ok", "service": "gateway", "mode": "load-balancer"})
                return

            if clean_path == "/regional-nodes":
                self._send_json(200, {"regional_nodes": self.state.regional_node_urls})
                return

            if clean_path.startswith("/wallets/") and clean_path.endswith("/transactions"):
                wallet_id = clean_path.split("/")[2]
                regional_node = self.state.resolve_wallet_owner_node(wallet_id)
                payload = request_json("GET", f"{regional_node}/wallets/{wallet_id}/transactions")
                self._send_json(200, payload)
                return

            if clean_path.startswith("/wallets/"):
                wallet_id = clean_path.split("/")[2]
                regional_node = self.state.resolve_wallet_owner_node(wallet_id)
                payload = request_json("GET", f"{regional_node}/wallets/{wallet_id}")
                self._send_json(200, payload)
                return

            self._send_json(404, {"error": "Not found"})
        except Exception as exc:
            self._send_json(400, {"error": str(exc)})

    def do_POST(self) -> None:
        try:
            payload = self._read_json_body()

            if self.path == "/wallets":
                user_id = payload["user_id"]
                home_region = payload.get("home_region", "kampala")

                regional_node = self.state.pick_regional_node_for_creation(user_id)
                self.state.remember_user_region(user_id, home_region)

                created = request_json("POST", f"{regional_node}/wallets", payload)
                self.state.remember_wallet_owner(created["id"], regional_node)
                self._send_json(201, created)
                return

            if self.path.startswith("/wallets/") and self.path.endswith("/deposit"):
                wallet_id = self.path.split("/")[2]
                regional_node = self.state.resolve_wallet_owner_node(wallet_id)
                receipt = request_json("POST", f"{regional_node}/wallets/{wallet_id}/deposit", payload)
                self._send_json(200, receipt)
                return

            if self.path.startswith("/wallets/") and self.path.endswith("/withdraw"):
                wallet_id = self.path.split("/")[2]
                regional_node = self.state.resolve_wallet_owner_node(wallet_id)
                receipt = request_json("POST", f"{regional_node}/wallets/{wallet_id}/withdraw", payload)
                self._send_json(200, receipt)
                return

            if self.path == "/transfers":
                from_wallet_id = payload["from_wallet_id"]
                to_wallet_id = payload["to_wallet_id"]

                from_node = self.state.resolve_wallet_owner_node(from_wallet_id)
                to_node = self.state.resolve_wallet_owner_node(to_wallet_id)

                if from_node == to_node:
                    receipt = request_json("POST", f"{from_node}/transfers", payload)
                else:
                    receipt = request_json("POST", f"{from_node}/transfers", payload)

                self.state.remember_wallet_owner(from_wallet_id, from_node)
                self.state.remember_wallet_owner(to_wallet_id, to_node)
                self._send_json(200, receipt)
                return

            self._send_json(404, {"error": "Not found"})
        except Exception as exc:
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


def create_gateway_server(
    host: str,
    port: int,
    regional_node_urls: list[str],
    coordinator_urls: list[str],
) -> ThreadingHTTPServer:
    state = GatewayState(regional_node_urls=regional_node_urls, coordinator_urls=coordinator_urls)
    GatewayAPI.state = state
    return ThreadingHTTPServer((host, port), GatewayAPI)
