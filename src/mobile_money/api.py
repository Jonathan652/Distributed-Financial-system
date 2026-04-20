from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from .cluster import RegionalCluster


class MobileMoneyAPI(BaseHTTPRequestHandler):
    cluster: RegionalCluster | None = None

    def do_GET(self) -> None:
        try:
            if self.path == "/regions":
                self._send_json(200, {"regions": self.cluster.list_regions()})
                return

            if self.path.startswith("/regions/") and "/wallets/" in self.path:
                region, wallet_id = self._parse_region_and_wallet_id()
                wallet = self.cluster.get_wallet(region, wallet_id)
                self._send_json(200, wallet.to_dict())
                return

            if self.path.startswith("/wallets/") and self.path.endswith("/transactions"):
                wallet_id = self.path.split("/")[2]
                transactions = [transaction.to_dict() for transaction in self.cluster.get_transactions(wallet_id)]
                self._send_json(200, {"transactions": transactions})
                return

            self._send_json(404, {"error": "Not found"})
        except Exception as exc:  # pragma: no cover - HTTP boundary
            self._send_json(400, {"error": str(exc)})

    def do_POST(self) -> None:
        try:
            payload = self._read_json_body()

            if self.path == "/wallets":
                wallet = self.cluster.create_wallet(payload["user_id"], payload["home_region"])
                self._send_json(201, wallet.to_dict())
                return

            if self.path.startswith("/regions/") and self.path.endswith("/deposit"):
                region, wallet_id = self._parse_region_and_wallet_id()
                receipt = self.cluster.deposit(region, wallet_id, payload["amount"], payload.get("request_id"))
                self._send_json(200, receipt.to_dict())
                return

            if self.path.startswith("/regions/") and self.path.endswith("/withdraw"):
                region, wallet_id = self._parse_region_and_wallet_id()
                receipt = self.cluster.withdraw(region, wallet_id, payload["amount"], payload.get("request_id"))
                self._send_json(200, receipt.to_dict())
                return

            if self.path == "/transfers":
                receipt = self.cluster.transfer(
                    payload["region"],
                    payload["from_wallet_id"],
                    payload["to_wallet_id"],
                    payload["amount"],
                    payload.get("request_id"),
                )
                self._send_json(200, receipt.to_dict())
                return

            if self.path.startswith("/regions/") and self.path.endswith("/fail"):
                region = self.path.split("/")[2]
                self.cluster.fail_region(region)
                self._send_json(200, {"status": "offline", "region": region})
                return

            if self.path.startswith("/regions/") and self.path.endswith("/restore"):
                region = self.path.split("/")[2]
                self.cluster.restore_region(region)
                self._send_json(200, {"status": "online", "region": region})
                return

            self._send_json(404, {"error": "Not found"})
        except Exception as exc:  # pragma: no cover - HTTP boundary
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

    def _parse_region_and_wallet_id(self) -> tuple[str, str]:
        parts = self.path.strip("/").split("/")
        if len(parts) < 4:
            raise ValueError("Invalid region wallet route")
        return parts[1], parts[3]


def create_http_server(cluster: RegionalCluster, host: str = "127.0.0.1", port: int = 8081) -> HTTPServer:
    MobileMoneyAPI.cluster = cluster
    return HTTPServer((host, port), MobileMoneyAPI)
