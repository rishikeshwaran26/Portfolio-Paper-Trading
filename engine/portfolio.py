"""The Portfolio class — one strategy's cash, holdings, and journal.

This is the entire trading engine. It has no idea about JSON, files, the CLI,
or the web. It just takes prices as plain numbers and enforces the rules of
buying and selling. That isolation is deliberate: you can unit-test every rule
here without touching disk or the network, and later the Flask layer just calls
these same methods.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .errors import InsufficientFunds, InsufficientHoldings, InvalidTrade
from .models import (
    BUY,
    SELL,
    ClosedLot,
    Holding,
    Transaction,
    new_id,
    _now_iso,
)

# Confidence is a 1-5 self-rating captured on every buy.
MIN_CONFIDENCE = 1
MAX_CONFIDENCE = 5


def _round2(x: float) -> float:
    """Round to paise. We use float rupees for simplicity; rounding at each
    write keeps stray floating-point dust (e.g. 999.9999997) out of balances."""
    return round(x, 2)


class Portfolio:
    def __init__(self, name: str, cash: float, starting_cash: Optional[float] = None):
        self.name = name
        self.cash = _round2(cash)
        # Remember the starting cash so total-return % has a denominator even
        # after cash has been spent and partially returned by sells.
        self.starting_cash = _round2(starting_cash if starting_cash is not None else cash)
        self.holdings: dict[str, Holding] = {}
        self.transactions: list[Transaction] = []

    # -- buying ---------------------------------------------------------------
    def buy(
        self,
        symbol: str,
        quantity: int,
        price: float,
        reason: str,
        confidence: int,
        tags: Optional[list[str]] = None,
    ) -> Transaction:
        """Buy `quantity` shares of `symbol` at `price`.

        Validates cash, then updates the holding's average price and logs a
        journal entry. Returns the Transaction so the caller can show its id.

        How the average price is recalculated on a repeated buy
        -------------------------------------------------------
        Say you already hold 10 @ 100 (cost basis 1000) and buy 5 more @ 130
        (cost 650). The new average is the total spent divided by total shares:

            new_avg = (10*100 + 5*130) / (10 + 5)
                    = (1000 + 650) / 15
                    = 110.0

        So the average is a *weighted* average — a big buy at a very different
        price pulls the average toward it in proportion to its size. This is why
        it's called dollar-cost (here rupee-cost) averaging.
        """
        symbol = _normalize_symbol(symbol)
        _require_positive_int("quantity", quantity)
        _require_positive_number("price", price)
        if not (MIN_CONFIDENCE <= confidence <= MAX_CONFIDENCE):
            raise InvalidTrade(f"confidence must be {MIN_CONFIDENCE}-{MAX_CONFIDENCE}, got {confidence}")
        if not reason or not reason.strip():
            raise InvalidTrade("a buy needs a reason (your thesis for the journal)")

        cost = _round2(quantity * price)
        if cost > self.cash + 1e-6:  # tiny epsilon so exact-cash buys pass despite float dust
            raise InsufficientFunds(
                f"need ₹{cost:,.2f} but only ₹{self.cash:,.2f} available in '{self.name}'"
            )

        # Update or open the holding using the weighted-average formula above.
        existing = self.holdings.get(symbol)
        if existing:
            total_qty = existing.quantity + quantity
            total_cost = existing.quantity * existing.avg_price + quantity * price
            existing.quantity = total_qty
            existing.avg_price = _round2(total_cost / total_qty)
        else:
            self.holdings[symbol] = Holding(symbol=symbol, quantity=quantity, avg_price=_round2(price))

        self.cash = _round2(self.cash - cost)

        txn = Transaction(
            id=new_id(),
            type=BUY,
            symbol=symbol,
            quantity=quantity,
            price=_round2(price),
            timestamp=_now_iso(),
            reason=reason.strip(),
            confidence=confidence,
            tags=[t.strip() for t in (tags or []) if t.strip()],
            open_quantity=quantity,  # all of this buy is still held, for FIFO journal linking
        )
        self.transactions.append(txn)
        return txn

    # -- selling --------------------------------------------------------------
    def sell(self, symbol: str, quantity: int, price: float, reason: str) -> Transaction:
        """Sell `quantity` shares of `symbol` at `price`.

        Validates you actually hold enough, computes realized P&L, reduces the
        holding, and logs a journal entry.

        Two P&L numbers, and why they can differ
        ----------------------------------------
        1. headline realized_pnl (the money that hit your cash): computed against
           the blended AVERAGE cost —  (price - avg_price) * quantity. This is the
           number that matters for your account balance.

        2. per-lot lot_pnl (inside closed_lots): computed against each ORIGINAL
           buy's price via FIFO —  (price - that_buy_price) * lot_qty. This is what
           the journal analytics use to say 'my confidence-5 trades made X'.

        If you bought at two different prices and sell part of the position, (1)
        and (2) disagree, because (1) blends the cost and (2) tracks the actual
        oldest shares. Both are correct; they answer different questions.
        """
        symbol = _normalize_symbol(symbol)
        _require_positive_int("quantity", quantity)
        _require_positive_number("price", price)
        if not reason or not reason.strip():
            raise InvalidTrade("a sell needs a reason (target hit? stop loss? thesis changed?)")

        holding = self.holdings.get(symbol)
        if not holding or holding.quantity < quantity:
            have = holding.quantity if holding else 0
            raise InsufficientHoldings(
                f"cannot sell {quantity} {symbol}: only {have} held in '{self.name}'"
            )

        # (1) Headline realized P&L against the average cost.
        realized = _round2((price - holding.avg_price) * quantity)

        # (2) FIFO-match this sell against open buys for journal attribution.
        closed_lots = self._match_fifo(symbol, quantity, price)

        # Reduce the position. avg_price stays the same — selling doesn't change
        # the cost basis of the shares you still own.
        holding.quantity -= quantity
        if holding.quantity == 0:
            del self.holdings[symbol]

        self.cash = _round2(self.cash + quantity * price)

        txn = Transaction(
            id=new_id(),
            type=SELL,
            symbol=symbol,
            quantity=quantity,
            price=_round2(price),
            timestamp=_now_iso(),
            reason=reason.strip(),
            realized_pnl=realized,
            closed_lots=closed_lots,
        )
        self.transactions.append(txn)
        return txn

    def _match_fifo(self, symbol: str, quantity: int, sell_price: float) -> list[ClosedLot]:
        """Draw down open buy lots oldest-first, recording which buys (and their
        confidence/tags) this sale closed. Mutates each buy's open_quantity."""
        remaining = quantity
        lots: list[ClosedLot] = []
        for buy in self.transactions:
            if remaining <= 0:
                break
            if buy.type != BUY or buy.symbol != symbol or buy.open_quantity <= 0:
                continue
            take = min(buy.open_quantity, remaining)
            buy.open_quantity -= take
            remaining -= take
            lots.append(
                ClosedLot(
                    buy_id=buy.id,
                    quantity=take,
                    buy_price=buy.price,
                    sell_price=_round2(sell_price),
                    confidence=buy.confidence,
                    tags=list(buy.tags),
                    holding_days=_holding_days(buy.timestamp),
                    lot_pnl=_round2((sell_price - buy.price) * take),
                )
            )
        return lots

    # -- reviews --------------------------------------------------------------
    def review(self, transaction_id: str, outcome_notes: str) -> Transaction:
        """Attach a retrospective note to a transaction after the fact
        (e.g. 'sold too early', 'thesis was right, timing wrong')."""
        if not outcome_notes or not outcome_notes.strip():
            raise InvalidTrade("review needs some notes")
        for txn in self.transactions:
            if txn.id == transaction_id:
                txn.review = outcome_notes.strip()
                return txn
        raise InvalidTrade(f"no transaction with id '{transaction_id}' in '{self.name}'")

    # -- valuation ------------------------------------------------------------
    def unrealized_pnl(self, prices: dict[str, float]) -> float:
        """Total paper profit across all holdings, given a {symbol: price} map.
        Symbols missing from `prices` are valued at their own cost (0 unrealized)
        so a single missing quote can't crash your whole P&L view."""
        total = 0.0
        for symbol, h in self.holdings.items():
            current = prices.get(symbol, h.avg_price)
            total += h.unrealized_pnl(current)
        return _round2(total)

    def realized_pnl(self) -> float:
        """Sum of realized P&L across every sell so far (the booked profit)."""
        return _round2(sum(t.realized_pnl or 0.0 for t in self.transactions if t.type == SELL))

    def holdings_value(self, prices: dict[str, float]) -> float:
        total = 0.0
        for symbol, h in self.holdings.items():
            current = prices.get(symbol, h.avg_price)
            total += h.market_value(current)
        return _round2(total)

    def total_value(self, prices: dict[str, float]) -> float:
        """Everything the strategy is worth right now: idle cash + market value
        of holdings. This is the number the leaderboard ranks strategies by."""
        return _round2(self.cash + self.holdings_value(prices))

    def total_return_pct(self, prices: dict[str, float]) -> float:
        """Total return vs starting cash, as a percentage."""
        if self.starting_cash <= 0:
            return 0.0
        return _round2((self.total_value(prices) - self.starting_cash) / self.starting_cash * 100)

    # -- serialization --------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "cash": self.cash,
            "starting_cash": self.starting_cash,
            "holdings": {s: h.to_dict() for s, h in self.holdings.items()},
            "transactions": [t.to_dict() for t in self.transactions],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Portfolio":
        p = cls(
            name=d["name"],
            cash=float(d["cash"]),
            starting_cash=float(d.get("starting_cash", d["cash"])),
        )
        p.holdings = {s: Holding.from_dict(h) for s, h in (d.get("holdings") or {}).items()}
        p.transactions = [Transaction.from_dict(t) for t in (d.get("transactions") or [])]
        return p


# --- small validation helpers -----------------------------------------------
def _normalize_symbol(symbol: str) -> str:
    if not symbol or not symbol.strip():
        raise InvalidTrade("symbol is required")
    return symbol.strip().upper()


def _require_positive_int(field_name: str, value) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise InvalidTrade(f"{field_name} must be a positive whole number, got {value!r}")


def _require_positive_number(field_name: str, value) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise InvalidTrade(f"{field_name} must be a positive number, got {value!r}")


def _holding_days(buy_timestamp: str) -> float:
    """Days between a buy and now, as a float (fractions of a day included)."""
    try:
        bought = datetime.fromisoformat(buy_timestamp)
    except ValueError:
        return 0.0
    delta = datetime.now(bought.tzinfo) - bought
    return round(delta.total_seconds() / 86400, 4)
