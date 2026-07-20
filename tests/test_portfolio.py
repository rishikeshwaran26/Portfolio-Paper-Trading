"""Unit tests for the core trading rules — no disk, no network.

These document the engine's behaviour as much as they verify it. If you want to
understand a rule, the matching test shows it with concrete numbers.
"""

import pytest

from engine.errors import InsufficientFunds, InsufficientHoldings, InvalidTrade
from engine.portfolio import Portfolio


def make_portfolio(cash=100_000.0):
    return Portfolio(name="Test", cash=cash)


# --- buying ------------------------------------------------------------------
def test_buy_reduces_cash_and_opens_holding():
    p = make_portfolio(100_000)
    p.buy("RELIANCE", 10, 2500, reason="cheap", confidence=4)
    assert p.cash == 75_000.0                 # 100000 - 10*2500
    assert p.holdings["RELIANCE"].quantity == 10
    assert p.holdings["RELIANCE"].avg_price == 2500.0


def test_repeated_buy_recalculates_weighted_average():
    p = make_portfolio(100_000)
    p.buy("TCS", 10, 100, reason="a", confidence=3)
    p.buy("TCS", 5, 130, reason="b", confidence=3)
    # (10*100 + 5*130) / 15 = 1650/15 = 110
    assert p.holdings["TCS"].avg_price == 110.0
    assert p.holdings["TCS"].quantity == 15


def test_buy_rejects_insufficient_cash():
    p = make_portfolio(1000)
    with pytest.raises(InsufficientFunds):
        p.buy("INFY", 10, 200, reason="x", confidence=3)  # needs 2000


def test_buy_requires_reason_and_valid_confidence():
    p = make_portfolio()
    with pytest.raises(InvalidTrade):
        p.buy("INFY", 1, 100, reason="", confidence=3)
    with pytest.raises(InvalidTrade):
        p.buy("INFY", 1, 100, reason="ok", confidence=9)


def test_buy_rejects_non_positive_quantity():
    p = make_portfolio()
    with pytest.raises(InvalidTrade):
        p.buy("INFY", 0, 100, reason="x", confidence=3)


# --- selling -----------------------------------------------------------------
def test_sell_realizes_pnl_against_average_cost():
    p = make_portfolio(100_000)
    p.buy("WIPRO", 10, 400, reason="x", confidence=3)
    txn = p.sell("WIPRO", 5, 500, reason="target hit")
    # (500 - 400) * 5 = 500
    assert txn.realized_pnl == 500.0
    assert p.holdings["WIPRO"].quantity == 5
    assert p.holdings["WIPRO"].avg_price == 400.0  # unchanged by selling
    assert p.cash == 100_000 - 4000 + 2500


def test_sell_full_position_removes_holding():
    p = make_portfolio()
    p.buy("SBIN", 10, 500, reason="x", confidence=2)
    p.sell("SBIN", 10, 550, reason="done")
    assert "SBIN" not in p.holdings


def test_sell_rejects_more_than_held():
    p = make_portfolio()
    p.buy("SBIN", 5, 500, reason="x", confidence=2)
    with pytest.raises(InsufficientHoldings):
        p.sell("SBIN", 10, 550, reason="y")


def test_sell_requires_reason():
    p = make_portfolio()
    p.buy("SBIN", 5, 500, reason="x", confidence=2)
    with pytest.raises(InvalidTrade):
        p.sell("SBIN", 1, 550, reason="")


def test_realized_pnl_can_be_negative():
    p = make_portfolio()
    p.buy("ADANIENT", 10, 3000, reason="x", confidence=1)
    txn = p.sell("ADANIENT", 10, 2500, reason="stop loss")
    assert txn.realized_pnl == -5000.0


# --- fifo lot linking for the journal ---------------------------------------
def test_sell_links_fifo_lots_with_confidence_and_tags():
    p = make_portfolio(100_000)
    p.buy("HDFC", 10, 100, reason="first", confidence=2, tags=["value"])
    p.buy("HDFC", 10, 200, reason="second", confidence=5, tags=["momentum"])
    # Sell 15 -> closes all 10 of the first lot, then 5 of the second (FIFO).
    txn = p.sell("HDFC", 15, 250, reason="scale out")
    assert len(txn.closed_lots) == 2
    first, second = txn.closed_lots
    assert first.quantity == 10 and first.confidence == 2 and first.tags == ["value"]
    assert second.quantity == 5 and second.confidence == 5 and second.tags == ["momentum"]
    # lot P&L is against each lot's OWN buy price:
    assert first.lot_pnl == (250 - 100) * 10   # 1500
    assert second.lot_pnl == (250 - 200) * 5   # 250


def test_open_quantity_tracks_remaining_fifo():
    p = make_portfolio(100_000)
    b1 = p.buy("ITC", 10, 100, reason="a", confidence=3)
    b2 = p.buy("ITC", 10, 100, reason="b", confidence=3)
    p.sell("ITC", 12, 120, reason="x")
    assert b1.open_quantity == 0    # fully consumed
    assert b2.open_quantity == 8    # 2 taken


# --- unrealized p&l / valuation ---------------------------------------------
def test_unrealized_pnl_uses_current_prices():
    p = make_portfolio(100_000)
    p.buy("LT", 10, 1000, reason="x", confidence=4)
    assert p.unrealized_pnl({"LT": 1200}) == 2000.0
    assert p.unrealized_pnl({"LT": 900}) == -1000.0


def test_unrealized_pnl_missing_price_defaults_to_cost():
    p = make_portfolio(100_000)
    p.buy("LT", 10, 1000, reason="x", confidence=4)
    # No price supplied -> valued at cost -> zero unrealized, no crash.
    assert p.unrealized_pnl({}) == 0.0


def test_total_value_and_return_pct():
    p = Portfolio(name="T", cash=10_000, starting_cash=10_000)
    p.buy("X", 10, 500, reason="x", confidence=3)  # spends 5000, cash 5000
    # price rises to 600 -> holdings worth 6000 -> total 11000 -> +10%
    assert p.total_value({"X": 600}) == 11_000.0
    assert p.total_return_pct({"X": 600}) == 10.0


# --- review ------------------------------------------------------------------
def test_review_attaches_note():
    p = make_portfolio()
    p.buy("X", 1, 100, reason="x", confidence=3)
    txn = p.sell("X", 1, 110, reason="y")
    p.review(txn.id, "sold too early")
    assert txn.review == "sold too early"


def test_review_unknown_id_raises():
    p = make_portfolio()
    with pytest.raises(InvalidTrade):
        p.review("nope", "note")


# --- round trip serialization -----------------------------------------------
def test_to_dict_from_dict_round_trip():
    p = make_portfolio(100_000)
    p.buy("A", 10, 100, reason="buy a", confidence=4, tags=["t1"])
    p.buy("A", 5, 120, reason="add a", confidence=5)
    p.sell("A", 8, 150, reason="trim")
    restored = Portfolio.from_dict(p.to_dict())
    assert restored.cash == p.cash
    assert restored.holdings["A"].quantity == p.holdings["A"].quantity
    assert restored.holdings["A"].avg_price == p.holdings["A"].avg_price
    assert len(restored.transactions) == len(p.transactions)
    assert restored.transactions[-1].closed_lots[0].lot_pnl == p.transactions[-1].closed_lots[0].lot_pnl
