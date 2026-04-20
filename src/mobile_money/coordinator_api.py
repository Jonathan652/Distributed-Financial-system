from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .cluster import RegionalCluster
from .ledger import LedgerStore


class CoordinatorAPI(BaseHTTPRequestHandler):
    cluster: RegionalCluster | None = None

    def do_GET(self) -> None:
        try:
            clean_path = self.path.split("?", 1)[0]

            if clean_path == "/health":
                self._send_json(200, {"status": "ok", "service": "coordinator"})
                return

            if clean_path == "/regions":
                self._send_json(200, {"regions": self.cluster.list_regions()})
                return

            if clean_path == "/wallets":
                user_id = self._query_param("user_id")
                if user_id:
                    wallets = self.cluster.ledger.list_wallets_for_user(user_id)
                    self._send_json(200, {"wallets": [w.to_dict() for w in wallets]})
                    return
                self._send_json(400, {"error": "user_id query parameter required"})
                return

            if clean_path.startswith("/wallets/") and clean_path.endswith("/transactions"):
                wallet_id = clean_path.split("/")[2]
                txns = [txn.to_dict() for txn in self.cluster.get_transactions(wallet_id)]
                self._send_json(200, {"transactions": txns})
                return

            if clean_path.startswith("/wallets/"):
                wallet_id = clean_path.split("/")[2]
                region = self._query_region() or "kampala"
                wallet = self.cluster.get_wallet(region, wallet_id)
                self._send_json(200, wallet.to_dict())
                return

            self._send_json(404, {"error": "Not found"})
        except Exception as exc:  # pragma: no cover
            self._send_json(400, {"error": str(exc)})

    def do_POST(self) -> None:
        try:
            payload = self._read_json_body()

            if self.path == "/wallets":
                wallet = self.cluster.create_wallet(payload["user_id"], payload["home_region"])
                self._send_json(201, wallet.to_dict())
                return

            if self.path == "/deposit":
                receipt = self.cluster.deposit(
                    payload["region"],
                    payload["wallet_id"],
                    payload["amount"],
                    payload.get("request_id"),
                )
                self._send_json(200, receipt.to_dict())
                return

            if self.path == "/withdraw":
                receipt = self.cluster.withdraw(
                    payload["region"],
                    payload["wallet_id"],
                    payload["amount"],
                    payload.get("request_id"),
                )
                self._send_json(200, receipt.to_dict())
                return

            if self.path == "/transfer":
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
                self._send_json(200, {"region": region, "status": "offline"})
                return

            if self.path.startswith("/regions/") and self.path.endswith("/restore"):
                region = self.path.split("/")[2]
                self.cluster.restore_region(region)
                self._send_json(200, {"region": region, "status": "online"})
                return

            self._send_json(404, {"error": "Not found"})
        except Exception as exc:  # pragma: no cover
            self._send_json(400, {"error": str(exc)})

    def _query_region(self) -> str | None:
        if "?" not in self.path:
            return None
        query = self.path.split("?", 1)[1]
        for part in query.split("&"):
            key, _, value = part.partition("=")
            if key == "region":
                return value
        return None

    def _query_param(self, param_name: str) -> str | None:
        if "?" not in self.path:
            return None
        query = self.path.split("?", 1)[1]
        for part in query.split("&"):
            key, _, value = part.partition("=")
            if key == param_name:
                return value
        return None

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


def create_coordinator_server(
    host: str,
    port: int,
    database_path: str,
    regions: list[str],
) -> tuple[ThreadingHTTPServer, LedgerStore]:
    ledger = LedgerStore(database_path=database_path)
    cluster = RegionalCluster(ledger=ledger, regions=regions)
    CoordinatorAPI.cluster = cluster
    return ThreadingHTTPServer((host, port), CoordinatorAPI), ledger
