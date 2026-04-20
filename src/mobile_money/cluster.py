from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ledger import LedgerStore
from .money import Money
from .models import OperationReceipt, TransferReceipt, WalletRecord


@dataclass
class RegionalNode:
    name: str
    online: bool = True
    wallet_cache: dict[str, WalletRecord] = field(default_factory=dict)

    def sync_wallet(self, wallet: WalletRecord) -> None:
        self.wallet_cache[wallet.id] = wallet

    def get_cached_wallet(self, wallet_id: str) -> WalletRecord | None:
        return self.wallet_cache.get(wallet_id)


class RegionalCluster:
    def __init__(self, ledger: LedgerStore, regions: list[str]) -> None:
        self.ledger = ledger
        self.nodes = {region: RegionalNode(region) for region in regions}

    def create_wallet(self, user_id: str, home_region: str) -> WalletRecord:
        self._ensure_region_known(home_region)
        wallet = self.ledger.create_wallet(user_id, home_region)
        self._sync_wallet(wallet)
        return wallet

    def deposit(
        self,
        region: str,
        wallet_id: str,
        amount: Money | int | float | str,
        request_id: str | None = None,
    ) -> OperationReceipt:
        self._ensure_active_region(region)
        receipt = self.ledger.deposit(wallet_id, Money.from_value(amount), region, request_id=request_id)
        self._sync_wallet(receipt.wallet)
        return receipt

    def withdraw(
        self,
        region: str,
        wallet_id: str,
        amount: Money | int | float | str,
        request_id: str | None = None,
    ) -> OperationReceipt:
        self._ensure_active_region(region)
        receipt = self.ledger.withdraw(wallet_id, Money.from_value(amount), region, request_id=request_id)
        self._sync_wallet(receipt.wallet)
        return receipt

    def transfer(
        self,
        region: str,
        from_wallet_id: str,
        to_wallet_id: str,
        amount: Money | int | float | str,
        request_id: str | None = None,
    ) -> TransferReceipt:
        self._ensure_active_region(region)
        receipt = self.ledger.transfer(
            from_wallet_id,
            to_wallet_id,
            Money.from_value(amount),
            region,
            request_id=request_id,
        )
        self._sync_wallet(receipt.from_wallet)
        self._sync_wallet(receipt.to_wallet)
        return receipt

    def get_wallet(self, region: str, wallet_id: str) -> WalletRecord:
        self._ensure_region_known(region)
        node = self.nodes[region]
        if not node.online:
            raise RuntimeError(f"Region {region} is offline")

        cached = node.get_cached_wallet(wallet_id)
        if cached is not None:
            return cached

        wallet = self.ledger.get_wallet(wallet_id)
        node.sync_wallet(wallet)
        return wallet

    def get_transactions(self, wallet_id: str):
        return self.ledger.list_transactions_for_wallet(wallet_id)

    def list_regions(self) -> list[dict[str, Any]]:
        return [
            {
                "name": node.name,
                "online": node.online,
                "cached_wallets": len(node.wallet_cache),
            }
            for node in self.nodes.values()
        ]

    def fail_region(self, region: str) -> None:
        self._ensure_region_known(region)
        self.nodes[region].online = False

    def restore_region(self, region: str) -> None:
        self._ensure_region_known(region)
        self.nodes[region].online = True

    def _sync_wallet(self, wallet: WalletRecord) -> None:
        for node in self.nodes.values():
            if node.online:
                node.sync_wallet(wallet)

    def _ensure_region_known(self, region: str) -> None:
        if region not in self.nodes:
            raise ValueError(f"Unknown region: {region}")

    def _ensure_active_region(self, region: str) -> None:
        self._ensure_region_known(region)
        if not self.nodes[region].online:
            raise RuntimeError(f"Region {region} is offline")
