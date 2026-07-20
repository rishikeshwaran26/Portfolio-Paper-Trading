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
    COVER,
    SELL,
    SHORT,
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
        existing = self.holdings.get(symbol)
        if existing and existing.is_short:
            # Averaging a "buy" into a short's negative quantity would silently
            # net the position instead of properly realizing short P&L via FIFO.
            # Keep the two flows unambiguous: closing a short is always cover().
            raise InvalidTrade(
                f"you have an open short position in {symbol} — use cover() to close it, not buy()"
            )

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
        if holding and holding.is_short:
            raise InvalidTrade(
                f"you have a short position in {symbol} — use cover() to close it, not sell()"
            )
        if not holding or holding.quantity < quantity:
            have = holding.quantity if holding else 0
            raise InsufficientHoldings(
                f"cannot sell {quantity} {symbol}: only {have} held in '{self.name}'"
            )

        # (1) Headline realized P&L against the average cost.
        realized = _round2((price - holding.avg_price) * quantity)

        # (2) FIFO-match this sell against open buys for journal attribution.
        closed_lots = self._match_fifo(symbol, quantity, price, opening_type=BUY)

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

    def _match_fifo(
        self, symbol: str, quantity: int, exit_price: float, opening_type: str
    ) -> list[ClosedLot]:
        """Draw down open BUY (or SHORT) lots oldest-first, recording which
        opening trade (and its confidence/tags) this exit closed. Mutates each
        opening trade's open_quantity.

        `opening_type` is BUY when called from sell(), SHORT when called from
        cover() — same FIFO mechanics, just matched against the other side's
        opening trades. lot_pnl direction flips accordingly: a sell profits
        when exit_price > entry price; a cover profits when exit_price is
        LOWER than the short's entry price, so the sign is inverted for SHORT.
        """
        remaining = quantity
        lots: list[ClosedLot] = []
        for opening in self.transactions:
            if remaining <= 0:
                break
            if opening.type != opening_type or opening.symbol != symbol or opening.open_quantity <= 0:
                continue
            take = min(opening.open_quantity, remaining)
            opening.open_quantity -= take
            remaining -= take
            if opening_type == BUY:
                lot_pnl = (exit_price - opening.price) * take
            else:  # SHORT: profit when you buy back BELOW the price you shorted at
                lot_pnl = (opening.price - exit_price) * take
            lots.append(
                ClosedLot(
                    buy_id=opening.id,
                    quantity=take,
                    buy_price=opening.price,
                    sell_price=_round2(exit_price),
                    confidence=opening.confidence,
                    tags=list(opening.tags),
                    holding_days=_holding_days(opening.timestamp),
                    lot_pnl=_round2(lot_pnl),
                )
            )
        return lots

    # -- short selling ----------------------------------------------------------
    def short(
        self,
        symbol: str,
        quantity: int,
        price: float,
        reason: str,
        confidence: int,
        tags: Optional[list[str]] = None,
    ) -> Transaction:
        """Sell-to-open `quantity` borrowed shares of `symbol` at `price`,
        betting the price falls. Mirrors buy(): same validation, same
        confidence/tags thesis-capture, same weighted-average-on-repeat
        behavior — just building a NEGATIVE holding instead of a positive one.

        You receive the sale proceeds immediately (cash increases), because in
        a real market that's what selling borrowed shares does. The offsetting
        obligation to buy them back shows up as a negative market_value, so
        total_value (cash + holdings_value) is unchanged at the moment you
        open the short — it only moves as the price moves, exactly like a buy.

        Known simplification: no borrow fee / margin interest is modeled, and
        a short can be held indefinitely (real intraday shorting must be
        squared off same-day; that rule isn't enforced here).
        """
        symbol = _normalize_symbol(symbol)
        _require_positive_int("quantity", quantity)
        _require_positive_number("price", price)
        if not (MIN_CONFIDENCE <= confidence <= MAX_CONFIDENCE):
            raise InvalidTrade(f"confidence must be {MIN_CONFIDENCE}-{MAX_CONFIDENCE}, got {confidence}")
        if not reason or not reason.strip():
            raise InvalidTrade("a short needs a reason (your thesis for the journal)")
        existing = self.holdings.get(symbol)
        if existing and not existing.is_short:
            raise InvalidTrade(
                f"you already hold {existing.quantity} {symbol} long — sell that position first"
            )

        if existing:
            # Weighted-average short entry price, same formula as buy() but
            # over the magnitude of the (negative) existing quantity.
            total_qty = abs(existing.quantity) + quantity
            total_cost = abs(existing.quantity) * existing.avg_price + quantity * price
            existing.quantity -= quantity  # more negative = bigger short
            existing.avg_price = _round2(total_cost / total_qty)
        else:
            self.holdings[symbol] = Holding(symbol=symbol, quantity=-quantity, avg_price=_round2(price))

        self.cash = _round2(self.cash + quantity * price)  # proceeds received now

        txn = Transaction(
            id=new_id(),
            type=SHORT,
            symbol=symbol,
            quantity=quantity,
            price=_round2(price),
            timestamp=_now_iso(),
            reason=reason.strip(),
            confidence=confidence,
            tags=[t.strip() for t in (tags or []) if t.strip()],
            open_quantity=quantity,  # all of this short is still open, for FIFO linking
        )
        self.transactions.append(txn)
        return txn

    def cover(self, symbol: str, quantity: int, price: float, reason: str) -> Transaction:
        """Buy-to-close `quantity` shares of an open short position at `price`.

        Mirrors sell(): same two-P&L-numbers structure (headline realized_pnl
        against the blended average short price; per-lot lot_pnl via FIFO
        against each original SHORT's entry price for journal attribution),
        just with the direction of profit inverted — a cover profits when
        `price` is BELOW the average short entry price.
        """
        symbol = _normalize_symbol(symbol)
        _require_positive_int("quantity", quantity)
        _require_positive_number("price", price)
        if not reason or not reason.strip():
            raise InvalidTrade("a cover needs a reason (target hit? stop loss? thesis changed?)")

        holding = self.holdings.get(symbol)
        if holding and not holding.is_short:
            raise InvalidTrade(
                f"you hold {symbol} long, not short — use sell() to close it, not cover()"
            )
        if not holding or abs(holding.quantity) < quantity:
            have = abs(holding.quantity) if holding else 0
            raise InsufficientHoldings(
                f"cannot cover {quantity} {symbol}: only {have} shorted in '{self.name}'"
            )

        # (1) Headline realized P&L against the average short price — profit
        # when you buy back below what you sold at.
        realized = _round2((holding.avg_price - price) * quantity)

        # (2) FIFO-match this cover against open SHORT lots for journal attribution.
        closed_lots = self._match_fifo(symbol, quantity, price, opening_type=SHORT)

        # Reduce the short (move toward zero). avg_price stays the same — it's
        # the average price of the shares still owed, which hasn't changed.
        holding.quantity += quantity
        if holding.quantity == 0:
            del self.holdings[symbol]

        self.cash = _round2(self.cash - quantity * price)  # pay to buy back

        txn = Transaction(
            id=new_id(),
            type=COVER,
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
        """Sum of realized P&L across every closed trade so far — sells AND
        covers both book realized profit, just via opposite-direction bets."""
        return _round2(
            sum(t.realized_pnl or 0.0 for t in self.transactions if t.type in (SELL, COVER))
        )

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
