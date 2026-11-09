"""Project and line item dataclasses. Pure Python, no Qt."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Any

KIND_COST = "cost"
KIND_BENEFIT = "benefit"
KINDS = (KIND_COST, KIND_BENEFIT)
KIND_LABELS = {KIND_COST: "Cost", KIND_BENEFIT: "Benefit"}

TIMING_ONE_TIME = "one_time"
TIMING_MONTHLY = "monthly"
TIMINGS = (TIMING_ONE_TIME, TIMING_MONTHLY)
TIMING_LABELS = {TIMING_ONE_TIME: "One-time", TIMING_MONTHLY: "Monthly"}

MIN_HORIZON = 1
MAX_HORIZON = 600  # 50 years
DEFAULT_HORIZON = 12
MAX_MONTH = MAX_HORIZON
MAX_DISCOUNT_RATE = 100.0
MAX_AMOUNT = 1e15


def new_id() -> str:
    return uuid.uuid4().hex


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _int(value: Any, default: int, low: int, high: int) -> int:
    number = _number(value, float(default))
    return int(min(max(round(number), low), high))


@dataclass(slots=True)
class LineItem:
    """One cost or benefit.

    One-time items happen once, in ``start_month``.
    Monthly items repeat every month from ``start_month`` to ``end_month``
    (inclusive). ``end_month`` of None means "until the end of the horizon".
    """

    name: str = ""
    kind: str = KIND_COST
    amount: float = 0.0
    timing: str = TIMING_ONE_TIME
    start_month: int = 0
    end_month: int | None = None
    id: str = field(default_factory=new_id)

    @property
    def is_cost(self) -> bool:
        return self.kind == KIND_COST

    @property
    def is_monthly(self) -> bool:
        return self.timing == TIMING_MONTHLY

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LineItem:
        kind = _text(data.get("kind"), KIND_COST).lower()
        if kind not in KINDS:
            kind = KIND_COST
        timing = _text(data.get("timing"), TIMING_ONE_TIME).lower()
        if timing not in TIMINGS:
            timing = TIMING_ONE_TIME
        end_raw = data.get("end_month")
        end_month = None if end_raw in (None, "") else _int(end_raw, 0, 0, MAX_MONTH)
        return cls(
            name=_text(data.get("name")),
            kind=kind,
            amount=min(abs(_number(data.get("amount"))), MAX_AMOUNT),
            timing=timing,
            start_month=_int(data.get("start_month"), 0, 0, MAX_MONTH),
            end_month=end_month,
            id=_text(data.get("id")) or new_id(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "amount": self.amount,
            "timing": self.timing,
            "start_month": self.start_month,
            "end_month": self.end_month,
        }


@dataclass(slots=True)
class Project:
    """Any investment: an event, a campaign, a machine, a hire, software."""

    name: str = "New project"
    notes: str = ""
    horizon_months: int = DEFAULT_HORIZON
    discount_rate: float = 0.0  # annual, in percent (8 means 8% a year)
    line_items: list[LineItem] = field(default_factory=list)
    id: str = field(default_factory=new_id)

    def find_item(self, item_id: str) -> LineItem | None:
        for item in self.line_items:
            if item.id == item_id:
                return item
        return None

    def copy(self, new_name: str | None = None) -> Project:
        """Deep copy with fresh ids, for "Duplicate"."""
        data = self.to_dict()
        clone = Project.from_dict(data)
        clone.id = new_id()
        for item in clone.line_items:
            item.id = new_id()
        if new_name is not None:
            clone.name = new_name
        return clone

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Project:
        raw_items = data.get("line_items")
        items: list[LineItem] = []
        if isinstance(raw_items, list):
            items = [LineItem.from_dict(item) for item in raw_items if isinstance(item, dict)]
        rate = _number(data.get("discount_rate"))
        return cls(
            name=_text(data.get("name")) or "Untitled project",
            notes=str(data.get("notes") or ""),
            horizon_months=_int(
                data.get("horizon_months"), DEFAULT_HORIZON, MIN_HORIZON, MAX_HORIZON
            ),
            discount_rate=min(max(rate, 0.0), MAX_DISCOUNT_RATE),
            line_items=items,
            id=_text(data.get("id")) or new_id(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "notes": self.notes,
            "horizon_months": self.horizon_months,
            "discount_rate": self.discount_rate,
            "line_items": [item.to_dict() for item in self.line_items],
        }


@dataclass(slots=True)
class Settings:
    currency_symbol: str = "$"

    @classmethod
    def from_dict(cls, data: Any) -> Settings:
        if not isinstance(data, dict):
            return cls()
        symbol = data.get("currency_symbol")
        if not isinstance(symbol, str):
            symbol = "$"
        return cls(currency_symbol=symbol.strip()[:5])

    def to_dict(self) -> dict[str, Any]:
        return {"currency_symbol": self.currency_symbol}
