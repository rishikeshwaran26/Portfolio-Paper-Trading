"""Data shapes for the trading engine.

Everything here is a plain dataclass with explicit to_dict / from_dict methods.
Why not just use dicts everywhere? Because a dataclass gives us:
  - one place that documents every field (the class definition),
  - type hints so the editor and readers know what a Holding contains,
  - a single choke point (from_dict) to defend against corrupted / old JSON.

Why write to_dict / from_dict by hand instead of using a library?
  - JSON has no idea about datetime, so we convert timestamps to ISO strings
    on the way out and parse them on the way in. Doing it explicitly keeps the
    on-disk format stable and easy to eyeball.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


# --- Transaction types -------------------------------------------------------
BUY = "BUY"
SELL = "SELL"


def _now_iso() -> str:
    """UTC timestamp as an ISO-8601 string. UTC so journal math never breaks
    across DST or if you run this on a machine in another timezone."""
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    """Short unique id for a transaction. uuid4 hex, first 12 chars — long
    enough to never collide in a personal tool, short enough to type in the CLI."""
    return uuid.uuid4().hex[:12]


@dataclass
class ClosedLot:
    """A record, attached to a SELL, of one earlier BUY that the sell closed.

    This is the bridge between average-cost accounting (used for cash/holdings)
    and per-trade journal analytics (used to compare confidence levels / tags).
    Each closed lot remembers the ORIGINAL buy's price, confidence and tags, so
    we can ask 'how did trades I opened at confidence 5 actually turn out?'.

    lot_pnl here is the TRUE per-lot profit: (sell_price - this buy's price) * qty.
    Note this can differ from the sell's headline realized_pnl, which is computed
    against the blended average cost. Both are correct; they answer different
    questions (see Portfolio.sell docstring).
    """

    buy_id: str
    quantity: int
    buy_price: float
    sell_price: float
    confidence: Optional[int]
    tags: list[str]
    holding_days: float
    lot_pnl: float

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ClosedLot":
        return cls(
            buy_id=d["buy_id"],
            quantity=int(d["quantity"]),
            buy_price=float(d["buy_price"]),
            sell_price=float(d["sell_price"]),
            confidence=(int(d["confidence"]) if d.get("confidence") is not None else None),
            tags=list(d.get("tags") or []),
            holding_days=float(d["holding_days"]),
            lot_pnl=float(d["lot_pnl"]),
        )


@dataclass
class Transaction:
    """One buy or sell. This doubles as the trade-journal entry.

    Buy-only fields:  confidence, tags, open_quantity
    Sell-only fields: realized_pnl, closed_lots
    Shared:           reason (the journal thesis), review (added later)

    open_quantity (buys only): how many shares from THIS buy are still held.
    It starts equal to quantity and is drawn down FIFO as sells happen. It is
    what lets a later sell figure out which buys — and therefore which
    confidence/tags — it is closing. Purely for journaling; the cash math does
    not use it.
    """

    id: str
    type: str  # BUY or SELL
    symbol: str
    quantity: int
    price: float
    timestamp: str
    reason: str

    # buy-only
    confidence: Optional[int] = None
    tags: list[str] = field(default_factory=list)
    open_quantity: int = 0

    # sell-only
    realized_pnl: Optional[float] = None
    closed_lots: list[ClosedLot] = field(default_factory=list)

    # added after the position closes, via Portfolio.review()
    review: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["closed_lots"] = [lot.to_dict() for lot in self.closed_lots]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Transaction":
        return cls(
            id=d["id"],
            type=d["type"],
            symbol=d["symbol"],
            quantity=int(d["quantity"]),
            price=float(d["price"]),
            timestamp=d["timestamp"],
            reason=d.get("reason", ""),
            confidence=(int(d["confidence"]) if d.get("confidence") is not None else None),
            tags=list(d.get("tags") or []),
            open_quantity=int(d.get("open_quantity", 0)),
            realized_pnl=(float(d["realized_pnl"]) if d.get("realized_pnl") is not None else None),
            closed_lots=[ClosedLot.from_dict(x) for x in (d.get("closed_lots") or [])],
            review=d.get("review"),
        )


@dataclass
class Holding:
    """A current position in one symbol, average-cost style.

    quantity  = shares held right now
    avg_price = blended cost per share

    On repeated buys, avg_price is recalculated as a weighted average (see
    Portfolio.buy). On sells, quantity drops but avg_price is UNCHANGED — the
    cost basis of the shares you still hold hasn't moved.
    """

    symbol: str
    quantity: int
    avg_price: float

    @property
    def cost_basis(self) -> float:
        """Total rupees currently tied up in this position."""
        return round(self.quantity * self.avg_price, 2)

    def market_value(self, current_price: float) -> float:
        return round(self.quantity * current_price, 2)

    def unrealized_pnl(self, current_price: float) -> float:
        """Paper profit if you sold everything right now at current_price.
        'Unrealized' because you haven't actually sold — it moves every tick."""
        return round((current_price - self.avg_price) * self.quantity, 2)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Holding":
        return cls(
            symbol=d["symbol"],
            quantity=int(d["quantity"]),
            avg_price=float(d["avg_price"]),
        )
