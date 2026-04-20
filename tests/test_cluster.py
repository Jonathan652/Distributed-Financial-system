from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mobile_money.cluster import RegionalCluster
from mobile_money.ledger import LedgerStore


class RegionalClusterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.ledger = LedgerStore(os.path.join(self.tempdir.name, "ledger.sqlite3"))
        self.cluster = RegionalCluster(self.ledger, ["kampala", "mbarara", "gulu", "jinja"])

    def tearDown(self) -> None:
        self.ledger.close()
        self.tempdir.cleanup()

    def test_deposit_syncs_across_regions_immediately(self) -> None:
        wallet = self.cluster.create_wallet("alice@example.com", "mbarara")

        self.cluster.deposit("mbarara", wallet.id, "100.0000")

        mbarara_view = self.cluster.get_wallet("mbarara", wallet.id)
        jinja_view = self.cluster.get_wallet("jinja", wallet.id)

        self.assertEqual(mbarara_view.balance.to_string(), "100.0000")
        self.assertEqual(jinja_view.balance.to_string(), "100.0000")

    def test_transfer_prevents_double_spend(self) -> None:
        alice = self.cluster.create_wallet("alice@example.com", "kampala")
        bob = self.cluster.create_wallet("bob@example.com", "gulu")

        self.cluster.deposit("kampala", alice.id, 50)

        with self.assertRaises(ValueError):
            self.cluster.transfer("gulu", alice.id, bob.id, 60)

        alice_after = self.cluster.get_wallet("jinja", alice.id)
        bob_after = self.cluster.get_wallet("mbarara", bob.id)

        self.assertEqual(alice_after.balance.to_string(), "50.0000")
        self.assertEqual(bob_after.balance.to_string(), "0.0000")

    def test_idempotent_retry_does_not_double_apply(self) -> None:
        wallet = self.cluster.create_wallet("carol@example.com", "jinja")

        self.cluster.deposit("jinja", wallet.id, 25, request_id="request-123")
        self.cluster.deposit("kampala", wallet.id, 25, request_id="request-123")

        updated = self.cluster.get_wallet("kampala", wallet.id)
        self.assertEqual(updated.balance.to_string(), "25.0000")


if __name__ == "__main__":
    unittest.main()
