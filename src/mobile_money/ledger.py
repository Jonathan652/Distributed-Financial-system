from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .money import Money
from .models import (
    OperationReceipt,
    TransactionStatus,
    TransactionType,
    TransferReceipt,
    WalletRecord,
    WalletTransaction,
    new_id,
    now_utc,
)


class LedgerStore:
    def __init__(self, database_path: str | Path = ":memory:") -> None:
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(database_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = NORMAL")
        self._initialize_schema()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _initialize_schema(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS wallets (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    balance TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    home_region TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS wallet_transactions (
                    id TEXT PRIMARY KEY,
                    wallet_id TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    transaction_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    region TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    FOREIGN KEY (wallet_id) REFERENCES wallets(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    request_id TEXT PRIMARY KEY,
                    operation TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._connection.commit()

    def create_wallet(self, user_id: str, home_region: str) -> WalletRecord:
        wallet = WalletRecord(
            id=new_id(),
            user_id=user_id,
            balance=Money.zero(),
            version=0,
            home_region=home_region,
            created_at=now_utc(),
            updated_at=now_utc(),
        )

        with self._lock:
            self._connection.execute(
                """
                INSERT INTO wallets (id, user_id, balance, version, home_region, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    wallet.id,
                    wallet.user_id,
                    wallet.balance.to_string(),
                    wallet.version,
                    wallet.home_region,
                    wallet.created_at.isoformat(),
                    wallet.updated_at.isoformat(),
                ),
            )
            self._connection.commit()

        return wallet

    def get_wallet(self, wallet_id: str) -> WalletRecord:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM wallets WHERE id = ?",
                (wallet_id,),
            ).fetchone()

        if row is None:
            raise ValueError(f"Wallet not found: {wallet_id}")

        return self._wallet_from_row(row)

    def list_wallets_for_user(self, user_id: str) -> list[WalletRecord]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM wallets WHERE user_id = ? ORDER BY created_at ASC",
                (user_id,),
            ).fetchall()
        return [self._wallet_from_row(row) for row in rows]

    def list_transactions_for_wallet(self, wallet_id: str) -> list[WalletTransaction]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM wallet_transactions WHERE wallet_id = ? ORDER BY created_at DESC",
                (wallet_id,),
            ).fetchall()
        return [self._transaction_from_row(row) for row in rows]

    def deposit(
        self,
        wallet_id: str,
        amount: Money,
        region: str,
        request_id: str | None = None,
    ) -> OperationReceipt:
        return self._adjust_balance(wallet_id, amount, region, TransactionType.DEPOSIT, request_id, 1)

    def withdraw(
        self,
        wallet_id: str,
        amount: Money,
        region: str,
        request_id: str | None = None,
    ) -> OperationReceipt:
        return self._adjust_balance(wallet_id, amount, region, TransactionType.WITHDRAWAL, request_id, -1)

    def transfer(
        self,
        from_wallet_id: str,
        to_wallet_id: str,
        amount: Money,
        region: str,
        request_id: str | None = None,
    ) -> TransferReceipt:
        if from_wallet_id == to_wallet_id:
            raise ValueError("Cannot transfer to the same wallet")

        if request_id is not None:
            cached = self._load_idempotent_result(request_id)
            if cached is not None:
                return self._transfer_receipt_from_payload(cached)

        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                source = self.get_wallet(from_wallet_id)
                destination = self.get_wallet(to_wallet_id)

                if source.balance.is_less_than(amount):
                    raise ValueError("Insufficient funds")

                updated_source = self._store_wallet(
                    source,
                    source.balance.subtract(amount),
                    source.version + 1,
                )
                updated_destination = self._store_wallet(
                    destination,
                    destination.balance.add(amount),
                    destination.version + 1,
                )

                out_transaction = self._store_transaction(
                    wallet_id=from_wallet_id,
                    amount=amount,
                    region=region,
                    transaction_type=TransactionType.TRANSFER_OUT,
                    status=TransactionStatus.COMPLETED,
                    metadata={"counterparty_wallet_id": to_wallet_id},
                )
                in_transaction = self._store_transaction(
                    wallet_id=to_wallet_id,
                    amount=amount,
                    region=region,
                    transaction_type=TransactionType.TRANSFER_IN,
                    status=TransactionStatus.COMPLETED,
                    metadata={"counterparty_wallet_id": from_wallet_id},
                )

                receipt = TransferReceipt(
                    from_wallet=updated_source,
                    to_wallet=updated_destination,
                    out_transaction=out_transaction,
                    in_transaction=in_transaction,
                )

                if request_id is not None:
                    self._store_idempotent_result(request_id, "transfer", receipt.to_dict())

                self._connection.commit()
                return receipt
            except Exception:
                self._connection.rollback()
                raise

    def _adjust_balance(
        self,
        wallet_id: str,
        amount: Money,
        region: str,
        transaction_type: TransactionType,
        request_id: str | None,
        direction: int,
    ) -> OperationReceipt:
        if request_id is not None:
            cached = self._load_idempotent_result(request_id)
            if cached is not None:
                return self._operation_receipt_from_payload(cached)

        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                wallet = self.get_wallet(wallet_id)
                if direction < 0 and wallet.balance.is_less_than(amount):
                    raise ValueError("Insufficient funds")

                updated_balance = wallet.balance.add(amount) if direction > 0 else wallet.balance.subtract(amount)
                updated_wallet = self._store_wallet(wallet, updated_balance, wallet.version + 1)
                transaction = self._store_transaction(
                    wallet_id=wallet_id,
                    amount=amount,
                    region=region,
                    transaction_type=transaction_type,
                    status=TransactionStatus.COMPLETED,
                    metadata={},
                )
                receipt = OperationReceipt(wallet=updated_wallet, transaction=transaction)

                if request_id is not None:
                    self._store_idempotent_result(request_id, transaction_type.value.lower(), receipt.to_dict())

                self._connection.commit()
                return receipt
            except Exception:
                self._connection.rollback()
                raise

    def _store_wallet(self, wallet: WalletRecord, balance: Money, version: int) -> WalletRecord:
        updated = WalletRecord(
            id=wallet.id,
            user_id=wallet.user_id,
            balance=balance,
            version=version,
            home_region=wallet.home_region,
            created_at=wallet.created_at,
            updated_at=now_utc(),
        )
        self._connection.execute(
            """
            UPDATE wallets
            SET balance = ?, version = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                updated.balance.to_string(),
                updated.version,
                updated.updated_at.isoformat(),
                updated.id,
            ),
        )
        return updated

    def _store_transaction(
        self,
        wallet_id: str,
        amount: Money,
        region: str,
        transaction_type: TransactionType,
        status: TransactionStatus,
        metadata: dict[str, Any],
    ) -> WalletTransaction:
        transaction = WalletTransaction(
            id=new_id(),
            wallet_id=wallet_id,
            amount=amount,
            transaction_type=transaction_type,
            status=status,
            region=region,
            created_at=now_utc(),
            metadata=metadata,
        )
        self._connection.execute(
            """
            INSERT INTO wallet_transactions (id, wallet_id, amount, transaction_type, status, region, created_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transaction.id,
                transaction.wallet_id,
                transaction.amount.to_string(),
                transaction.transaction_type.value,
                transaction.status.value,
                transaction.region,
                transaction.created_at.isoformat(),
                json.dumps(transaction.metadata, sort_keys=True),
            ),
        )
        return transaction

    def _store_idempotent_result(self, request_id: str, operation: str, payload: dict[str, Any]) -> None:
        self._connection.execute(
            """
            INSERT OR REPLACE INTO idempotency_keys (request_id, operation, payload, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (request_id, operation, json.dumps(payload, sort_keys=True), now_utc().isoformat()),
        )

    def _load_idempotent_result(self, request_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT payload FROM idempotency_keys WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload"])

    def _wallet_from_row(self, row: sqlite3.Row) -> WalletRecord:
        return WalletRecord(
            id=row["id"],
            user_id=row["user_id"],
            balance=Money.from_value(row["balance"]),
            version=int(row["version"]),
            home_region=row["home_region"],
            created_at=self._parse_dt(row["created_at"]),
            updated_at=self._parse_dt(row["updated_at"]),
        )

    def _transaction_from_row(self, row: sqlite3.Row) -> WalletTransaction:
        return WalletTransaction(
            id=row["id"],
            wallet_id=row["wallet_id"],
            amount=Money.from_value(row["amount"]),
            transaction_type=TransactionType(row["transaction_type"]),
            status=TransactionStatus(row["status"]),
            region=row["region"],
            created_at=self._parse_dt(row["created_at"]),
            metadata=json.loads(row["metadata"]),
        )

    def _parse_dt(self, value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _operation_receipt_from_payload(self, payload: dict[str, Any]) -> OperationReceipt:
        return OperationReceipt(
            wallet=self._wallet_from_dict(payload["wallet"]),
            transaction=self._transaction_from_dict(payload["transaction"]),
        )

    def _transfer_receipt_from_payload(self, payload: dict[str, Any]) -> TransferReceipt:
        return TransferReceipt(
            from_wallet=self._wallet_from_dict(payload["from_wallet"]),
            to_wallet=self._wallet_from_dict(payload["to_wallet"]),
            out_transaction=self._transaction_from_dict(payload["out_transaction"]),
            in_transaction=self._transaction_from_dict(payload["in_transaction"]),
        )

    def _wallet_from_dict(self, payload: dict[str, Any]) -> WalletRecord:
        return WalletRecord(
            id=payload["id"],
            user_id=payload["user_id"],
            balance=Money.from_value(payload["balance"]),
            version=int(payload["version"]),
            home_region=payload["home_region"],
            created_at=self._parse_dt(payload["created_at"]),
            updated_at=self._parse_dt(payload["updated_at"]),
        )

    def _transaction_from_dict(self, payload: dict[str, Any]) -> WalletTransaction:
        return WalletTransaction(
            id=payload["id"],
            wallet_id=payload["wallet_id"],
            amount=Money.from_value(payload["amount"]),
            transaction_type=TransactionType(payload["transaction_type"]),
            status=TransactionStatus(payload["status"]),
            region=payload["region"],
            created_at=self._parse_dt(payload["created_at"]),
            metadata=payload.get("metadata", {}),
        )
