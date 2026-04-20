from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


class Money:
    PRECISION = Decimal("0.0001")

    def __init__(self, amount: Decimal) -> None:
        if amount < 0:
            raise ValueError("Amount cannot be negative")
        self._amount = self._normalize(amount)

    @classmethod
    def from_value(cls, value: Money | int | float | str | Decimal) -> Money:
        if isinstance(value, Money):
            return cls(value._amount)
        amount = Decimal(str(value))
        if amount < 0:
            raise ValueError("Amount cannot be negative")
        return cls(amount)

    @classmethod
    def zero(cls) -> Money:
        return cls(Decimal("0"))

    @staticmethod
    def _normalize(amount: Decimal) -> Decimal:
        return amount.quantize(Money.PRECISION, rounding=ROUND_HALF_UP)

    @property
    def amount(self) -> Decimal:
        return self._amount

    def add(self, other: Money) -> Money:
        return Money(self._amount + other._amount)

    def subtract(self, other: Money) -> Money:
        result = self._amount - other._amount
        if result < 0:
            raise ValueError("Insufficient funds")
        return Money(result)

    def is_greater_than(self, other: Money) -> bool:
        return self._amount > other._amount

    def is_less_than(self, other: Money) -> bool:
        return self._amount < other._amount

    def equals(self, other: Money) -> bool:
        return self._amount == other._amount

    def to_string(self) -> str:
        return f"{self._amount:.4f}"

    def __str__(self) -> str:
        return self.to_string()

    def __repr__(self) -> str:
        return f"Money('{self.to_string()}')"
