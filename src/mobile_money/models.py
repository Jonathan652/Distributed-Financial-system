from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from .money import Money


class TransactionType(str, Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"


class TransactionStatus(str, Enum):
    COMPLETED = "COMPLETED"
    PENDING = "PENDING"
    FAILED = "FAILED"


@dataclass(frozen=True)
class WalletRecord:
    id: str
    user_id: str
    balance: Money
    version: int
    home_region: str
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "balance": self.balance.to_string(),
            "version": self.version,
            "home_region": self.home_region,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True)
class WalletTransaction:
    id: str
    wallet_id: str
    amount: Money
    transaction_type: TransactionType
    status: TransactionStatus
    region: str
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "wallet_id": self.wallet_id,
            "amount": self.amount.to_string(),
            "transaction_type": self.transaction_type.value,
            "status": self.status.value,
            "region": self.region,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class OperationReceipt:
    wallet: WalletRecord
    transaction: WalletTransaction

    def to_dict(self) -> dict[str, Any]:
        return {
            "wallet": self.wallet.to_dict(),
            "transaction": self.transaction.to_dict(),
        }


@dataclass(frozen=True)
class TransferReceipt:
    from_wallet: WalletRecord
    to_wallet: WalletRecord
    out_transaction: WalletTransaction
    in_transaction: WalletTransaction

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_wallet": self.from_wallet.to_dict(),
            "to_wallet": self.to_wallet.to_dict(),
            "out_transaction": self.out_transaction.to_dict(),
            "in_transaction": self.in_transaction.to_dict(),
        }


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())
