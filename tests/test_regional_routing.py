from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mobile_money.http_utils import HttpRequestError
from mobile_money.regional_api import RegionalNodeState


class RegionalRoutingTests(unittest.TestCase):
    def test_resolve_wallet_owner_skips_unreachable_coordinator(self) -> None:
        state = RegionalNodeState("kampala", ["http://a", "http://b"])

        def fake_request_json(method: str, url: str, payload=None, timeout: int = 10):
            if url == "http://a/health":
                raise HttpRequestError("Connection failed for GET http://a/health: refused")
            if url == "http://b/health":
                return {"status": "ok"}
            if url.startswith("http://b/wallets/"):
                return {"id": "wallet-1", "balance": "0.0000"}
            raise HttpRequestError(f"Connection failed for {method} {url}: refused")

        with patch("mobile_money.regional_api.request_json", side_effect=fake_request_json):
            owner = state.resolve_wallet_owner("wallet-1")

        self.assertEqual(owner, "http://b")
        self.assertEqual(state.get_wallet_owner("wallet-1"), "http://b")

    def test_pick_create_coordinator_prefers_healthy_nodes(self) -> None:
        state = RegionalNodeState("kampala", ["http://a", "http://b"])

        def fake_request_json(method: str, url: str, payload=None, timeout: int = 10):
            if url == "http://a/health":
                raise HttpRequestError("Connection failed for GET http://a/health: refused")
            if url == "http://b/health":
                return {"status": "ok"}
            raise AssertionError(f"Unexpected URL in test: {url}")

        with patch("mobile_money.regional_api.request_json", side_effect=fake_request_json):
            coordinator = state.pick_create_coordinator("alice@example.com", "kampala")

        self.assertEqual(coordinator, "http://b")


if __name__ == "__main__":
    unittest.main()
