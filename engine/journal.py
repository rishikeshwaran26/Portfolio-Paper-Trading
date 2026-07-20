"""Queryable trade journal — the whole point of this project.

The journal is not a separate store; it's a *view* over a portfolio's
transactions. This module answers the questions you actually care about:

  - "Do my high-confidence trades actually make more money?"
  - "Do my 'technical breakout' trades beat my 'earnings play' trades?"
  - "Show me every losing trade so I can read back my reasoning."
  - "Is my short-selling actually working, separately from my long trades?"

How outcomes are attributed
---------------------------
Confidence and tags are recorded on the OPENING trade (BUY or SHORT). Profit is
only known once you CLOSE it (SELL or COVER). So every closed lot (see
models.ClosedLot) carries a snapshot of the originating opening trade's
confidence and tags together with the realized lot_pnl. Analytics here iterate
over those closed lots — meaning we only ever measure CLOSED trades, because an
open position has no realized outcome yet. This logic is identical for longs
and shorts; only which opening/closing type we look at differs.

Every function takes the list of a portfolio's transactions, so the same code
works whether the data came from memory or from disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from .models import BUY, CLOSING_TYPES, COVER, OPENING_TYPES, SELL, SHORT, Transaction


# --- simple filtered views over transactions --------------------------------
def buys(transactions: Iterable[Transaction]) -> list[Transaction]:
    return [t for t in transactions if t.type == BUY]


def sells(transactions: Iterable[Transaction]) -> list[Transaction]:
    return [t for t in transactions if t.type == SELL]


def shorts(transactions: Iterable[Transaction]) -> list[Transaction]:
    return [t for t in transactions if t.type == SHORT]


def covers(transactions: Iterable[Transaction]) -> list[Transaction]:
    return [t for t in transactions if t.type == COVER]


def openings(transactions: Iterable[Transaction]) -> list[Transaction]:
    """Every position-opening trade: BUY (long) or SHORT (short)."""
    return [t for t in transactions if t.type in OPENING_TYPES]


def closings(transactions: Iterable[Transaction]) -> list[Transaction]:
    """Every position-closing trade: SELL (closes a long) or COVER (closes a
    short). This is what the aggregate analytics below iterate over."""
    return [t for t in transactions if t.type in CLOSING_TYPES]


def by_tag(transactions: Iterable[Transaction], tag: str) -> list[Transaction]:
    """Opening trades carry tags directly; closing trades inherit tags from the
    opening trades they closed. So a tag query returns both the entry and the
    matching exit, for longs and shorts alike."""
    tag = tag.strip().lower()
    out = []
    for t in transactions:
        if t.type in OPENING_TYPES and any(x.lower() == tag for x in t.tags):
            out.append(t)
        elif t.type in CLOSING_TYPES and any(
            any(x.lower() == tag for x in lot.tags) for lot in t.closed_lots
        ):
            out.append(t)
    return out


def by_confidence(transactions: Iterable[Transaction], level: int) -> list[Transaction]:
    return [t for t in transactions if t.type in OPENING_TYPES and t.confidence == level]


def by_outcome(transactions: Iterable[Transaction], profitable: bool) -> list[Transaction]:
    """Closed trades (sells or covers) filtered by whether they realized a
    profit (or a loss)."""
    out = []
    for t in closings(transactions):
        pnl = t.realized_pnl or 0.0
        if profitable and pnl > 0:
            out.append(t)
        elif not profitable and pnl < 0:
            out.append(t)
    return out


def needs_review(transactions: Iterable[Transaction]) -> list[Transaction]:
    """Closed trades (sells or covers) you haven't written a retrospective note on yet."""
    return [t for t in closings(transactions) if not t.review]


# --- aggregate analytics ----------------------------------------------------
@dataclass
class OutcomeStats:
    """A performance summary for one bucket (a confidence level, or a tag)."""

    label: str
    closed_trades: int          # number of closed lots in this bucket
    total_pnl: float            # sum of lot_pnl
    win_rate: float             # fraction of lots with lot_pnl > 0
    avg_pnl: float              # mean lot_pnl per closed lot
    avg_holding_days: float

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "closed_trades": self.closed_trades,
            "total_pnl": self.total_pnl,
            "win_rate": self.win_rate,
            "avg_pnl": self.avg_pnl,
            "avg_holding_days": self.avg_holding_days,
        }


def _stats_from_lots(label: str, lots: list) -> OutcomeStats:
    n = len(lots)
    if n == 0:
        return OutcomeStats(label, 0, 0.0, 0.0, 0.0, 0.0)
    total = sum(l.lot_pnl for l in lots)
    wins = sum(1 for l in lots if l.lot_pnl > 0)
    hold = sum(l.holding_days for l in lots)
    return OutcomeStats(
        label=label,
        closed_trades=n,
        total_pnl=round(total, 2),
        win_rate=round(wins / n, 4),
        avg_pnl=round(total / n, 2),
        avg_holding_days=round(hold / n, 2),
    )


def performance_by_confidence(transactions: Iterable[Transaction]) -> list[OutcomeStats]:
    """Bucket every CLOSED lot (long or short) by the confidence you assigned
    when you opened it, then summarize. This is the direct answer to 'are my
    confident trades better?' — compare total_pnl / win_rate / avg_pnl across
    the 1-5 rows."""
    buckets: dict[Optional[int], list] = {}
    for t in closings(transactions):
        for lot in t.closed_lots:
            buckets.setdefault(lot.confidence, []).append(lot)
    rows = [
        _stats_from_lots(f"confidence {c}" if c is not None else "confidence ?", lots)
        for c, lots in buckets.items()
    ]
    rows.sort(key=lambda s: s.label)
    return rows


def winners_vs_losers(transactions: Iterable[Transaction]) -> dict:
    """Compare your winning trades against your losing ones — longs and shorts
    together, since a win is a win regardless of direction.

    The single most useful line in this whole module is avg_holding_days. If
    your losers are held much LONGER than your winners, that's the classic
    disposition effect — cutting gains early while letting losses run, hoping
    they come back. Seeing that number in black and white is the point of
    keeping a journal at all.

    Operates on closed lots (a trade only has a result once it's closed).
    """
    winners, losers = [], []
    for t in closings(transactions):
        for lot in t.closed_lots:
            (winners if lot.lot_pnl > 0 else losers if lot.lot_pnl < 0 else []).append(lot)

    def bucket(label: str, lots: list) -> dict:
        n = len(lots)
        if n == 0:
            return {
                "label": label, "count": 0, "total_pnl": 0.0, "avg_pnl": 0.0,
                "avg_holding_days": 0.0, "avg_confidence": None,
            }
        confs = [l.confidence for l in lots if l.confidence is not None]
        return {
            "label": label,
            "count": n,
            "total_pnl": round(sum(l.lot_pnl for l in lots), 2),
            "avg_pnl": round(sum(l.lot_pnl for l in lots) / n, 2),
            "avg_holding_days": round(sum(l.holding_days for l in lots) / n, 2),
            "avg_confidence": round(sum(confs) / len(confs), 2) if confs else None,
        }

    w = bucket("winners", winners)
    l = bucket("losers", losers)
    total = w["count"] + l["count"]
    return {
        "winners": w,
        "losers": l,
        "win_rate": round(w["count"] / total, 4) if total else 0.0,
        "closed_trades": total,
        # A positive number here means you hold losers longer than winners.
        "holding_gap_days": round(l["avg_holding_days"] - w["avg_holding_days"], 2),
        # Ratio of average win size to average loss size. >1 means your winners
        # are bigger than your losers, which can make a sub-50% win rate profitable.
        "payoff_ratio": (
            round(abs(w["avg_pnl"]) / abs(l["avg_pnl"]), 2)
            if l["avg_pnl"] not in (0, 0.0) else None
        ),
    }


def performance_by_tag(transactions: Iterable[Transaction]) -> list[OutcomeStats]:
    """Same idea, bucketed by tag. A lot with multiple tags counts once per tag,
    so 'earnings play' and 'mean reversion fade' are compared on equal footing —
    including when one is a long strategy and the other a short one."""
    buckets: dict[str, list] = {}
    for t in closings(transactions):
        for lot in t.closed_lots:
            for tag in (lot.tags or ["(untagged)"]):
                buckets.setdefault(tag, []).append(lot)
    rows = [_stats_from_lots(tag, lots) for tag, lots in buckets.items()]
    rows.sort(key=lambda s: s.total_pnl, reverse=True)
    return rows


def performance_by_side(transactions: Iterable[Transaction]) -> dict:
    """Long trades (BUY->SELL) vs short trades (SHORT->COVER), compared
    side-by-side. Answers 'is my short-selling actually working?' as a
    standalone question, separate from your long-side performance — the two
    are different bets (rising vs falling prices) and mixing them into one
    number would hide whether either one is actually working.
    """
    long_lots, short_lots = [], []
    for t in transactions:
        if t.type == SELL:
            long_lots.extend(t.closed_lots)
        elif t.type == COVER:
            short_lots.extend(t.closed_lots)
    return {
        "long": _stats_from_lots("long", long_lots).to_dict(),
        "short": _stats_from_lots("short", short_lots).to_dict(),
    }
