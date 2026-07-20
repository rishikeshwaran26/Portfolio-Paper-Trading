"""Short selling: sell-to-open (SHORT) and buy-to-close (COVER).

The whole risk in this feature is SIGN CONVENTIONS — a short profits when the
price FALLS, which is the opposite of everything else in the engine. These
tests pin down the direction of every number so a future refactor can't
silently flip one.
"""

import pytest

from api import create_app
from engine.errors import InsufficientFunds, InsufficientHoldings, InvalidTrade
from engine.journal import performance_by_side, performance_by_tag, winners_vs_losers
from engine.portfolio import Portfolio


def _p(cash=1_000_000) -> Portfolio:
    return Portfolio(name="S", cash=cash)


# --- opening a short ---------------------------------------------------------
def test_short_creates_negative_holding():
    p = _p()
    p.short("RELIANCE", 10, 1300, reason="overextended", confidence=4)
    h = p.holdings["RELIANCE"]
    assert h.quantity == -10          # negative == short
    assert h.avg_price == 1300.0      # entry price stays POSITIVE
    assert h.is_short is True


def test_short_credits_cash_immediately():
    """Selling borrowed shares puts the proceeds in your account right away."""
    p = _p(100_000)
    p.short("X", 10, 500, reason="fade", confidence=3)
    assert p.cash == 105_000.0        # +10*500


def test_short_does_not_change_total_value_at_open():
    """Opening a short is value-neutral at the moment of opening: cash goes up,
    but you now owe shares worth exactly that much."""
    p = _p(100_000)
    before = p.total_value({"X": 500})
    p.short("X", 10, 500, reason="fade", confidence=3)
    assert p.total_value({"X": 500}) == before


def test_short_requires_reason_and_confidence():
    p = _p()
    with pytest.raises(InvalidTrade):
        p.short("X", 10, 100, reason="", confidence=3)
    with pytest.raises(InvalidTrade):
        p.short("X", 10, 100, reason="ok", confidence=9)


def test_short_rejects_negative_quantity():
    p = _p()
    with pytest.raises(InvalidTrade):
        p.short("X", -5, 100, reason="ok", confidence=3)


def test_repeated_short_averages_entry_price():
    """Same weighted-average formula as buy(), over the short's magnitude."""
    p = _p()
    p.short("X", 10, 100, reason="a", confidence=3)   # 10 @ 100
    p.short("X", 5, 130, reason="b", confidence=3)    # 5 @ 130
    h = p.holdings["X"]
    assert h.quantity == -15
    assert h.avg_price == 110.0                       # (1000 + 650) / 15


# --- unrealized P&L direction (the core inversion) --------------------------
def test_short_profits_when_price_falls():
    p = _p()
    p.short("X", 10, 100, reason="fade", confidence=3)
    assert p.unrealized_pnl({"X": 90}) == 100.0       # (90-100) * -10 = +100


def test_short_loses_when_price_rises():
    p = _p()
    p.short("X", 10, 100, reason="fade", confidence=3)
    assert p.unrealized_pnl({"X": 110}) == -100.0     # (110-100) * -10 = -100


def test_short_market_value_is_negative():
    """A short is a liability — it reduces total portfolio value."""
    p = _p(100_000)
    p.short("X", 10, 100, reason="fade", confidence=3)
    assert p.holdings_value({"X": 100}) == -1000.0
    assert p.total_value({"X": 100}) == 100_000.0     # 101,000 cash - 1,000 owed


def test_total_value_rises_as_short_wins():
    p = _p(100_000)
    p.short("X", 10, 100, reason="fade", confidence=3)
    assert p.total_value({"X": 80}) == 100_200.0      # price fell 20 -> +200


# --- covering ----------------------------------------------------------------
def test_cover_realizes_profit_when_bought_back_lower():
    p = _p(100_000)
    p.short("X", 10, 100, reason="fade", confidence=3)
    txn = p.cover("X", 10, 80, reason="target hit")
    assert txn.realized_pnl == 200.0                  # (100-80) * 10
    assert txn.type == "COVER"
    assert "X" not in p.holdings                      # fully closed


def test_cover_realizes_loss_when_bought_back_higher():
    p = _p(100_000)
    p.short("X", 10, 100, reason="fade", confidence=3)
    txn = p.cover("X", 10, 120, reason="stop loss")
    assert txn.realized_pnl == -200.0


def test_cover_cash_math_round_trip():
    """Cash must end exactly where the P&L says it should."""
    p = _p(100_000)
    p.short("X", 10, 100, reason="fade", confidence=3)   # +1000 -> 101,000
    p.cover("X", 10, 80, reason="target")                # -800  -> 100,200
    assert p.cash == 100_200.0
    assert p.realized_pnl() == 200.0


def test_partial_cover_leaves_rest_open():
    p = _p(100_000)
    p.short("X", 10, 100, reason="fade", confidence=3)
    p.cover("X", 4, 90, reason="partial")
    h = p.holdings["X"]
    assert h.quantity == -6
    assert h.avg_price == 100.0        # unchanged: still owe 6 shorted at 100


def test_cover_more_than_shorted_rejected():
    p = _p()
    p.short("X", 10, 100, reason="fade", confidence=3)
    with pytest.raises(InsufficientHoldings):
        p.cover("X", 15, 90, reason="too many")


def test_cover_with_no_position_rejected():
    p = _p()
    with pytest.raises(InsufficientHoldings):
        p.cover("X", 5, 90, reason="nothing to cover")


def test_cover_requires_reason():
    p = _p()
    p.short("X", 10, 100, reason="fade", confidence=3)
    with pytest.raises(InvalidTrade):
        p.cover("X", 5, 90, reason="")


# --- long/short direction guards --------------------------------------------
def test_cannot_buy_into_an_open_short():
    p = _p()
    p.short("X", 10, 100, reason="fade", confidence=3)
    with pytest.raises(InvalidTrade, match="cover"):
        p.buy("X", 5, 90, reason="oops", confidence=3)


def test_cannot_short_a_symbol_held_long():
    p = _p()
    p.buy("X", 10, 100, reason="long", confidence=3)
    with pytest.raises(InvalidTrade, match="long"):
        p.short("X", 5, 110, reason="oops", confidence=3)


def test_cannot_sell_a_short_position():
    p = _p()
    p.short("X", 10, 100, reason="fade", confidence=3)
    with pytest.raises(InvalidTrade, match="cover"):
        p.sell("X", 5, 90, reason="oops")


def test_cannot_cover_a_long_position():
    p = _p()
    p.buy("X", 10, 100, reason="long", confidence=3)
    with pytest.raises(InvalidTrade, match="sell"):
        p.cover("X", 5, 110, reason="oops")


def test_can_short_after_fully_closing_a_long():
    """Once the long is gone the symbol is free to short."""
    p = _p()
    p.buy("X", 10, 100, reason="long", confidence=3)
    p.sell("X", 10, 110, reason="done")
    p.short("X", 5, 110, reason="now fade it", confidence=4)
    assert p.holdings["X"].quantity == -5


# --- FIFO journal attribution for shorts ------------------------------------
def test_cover_fifo_matches_oldest_short_first():
    p = _p()
    p.short("X", 10, 100, reason="first", confidence=5, tags=["fade"])
    p.short("X", 10, 120, reason="second", confidence=2, tags=["fade"])
    txn = p.cover("X", 10, 90, reason="close oldest")
    assert len(txn.closed_lots) == 1
    lot = txn.closed_lots[0]
    assert lot.buy_price == 100.0      # the OLDEST short
    assert lot.confidence == 5
    assert lot.lot_pnl == 100.0        # (100-90) * 10 -> profit, correct direction


def test_cover_spanning_two_short_lots():
    p = _p()
    p.short("X", 10, 100, reason="a", confidence=5)
    p.short("X", 10, 120, reason="b", confidence=2)
    txn = p.cover("X", 15, 90, reason="close most")
    assert len(txn.closed_lots) == 2
    assert txn.closed_lots[0].lot_pnl == 100.0    # 10 @ (100-90)
    assert txn.closed_lots[1].lot_pnl == 150.0    # 5  @ (120-90)


def test_short_lot_pnl_negative_when_price_rose():
    p = _p()
    p.short("X", 10, 100, reason="a", confidence=3, tags=["fade"])
    txn = p.cover("X", 10, 130, reason="stopped out")
    assert txn.closed_lots[0].lot_pnl == -300.0


# --- journal analytics include shorts ---------------------------------------
def test_analytics_by_tag_includes_short_trades():
    p = _p()
    p.short("X", 10, 100, reason="fade", confidence=4, tags=["mean reversion"])
    p.cover("X", 10, 80, reason="target")
    rows = {r.label: r for r in performance_by_tag(p.transactions)}
    assert rows["mean reversion"].total_pnl == 200.0
    assert rows["mean reversion"].win_rate == 1.0


def test_winners_vs_losers_counts_shorts():
    p = _p()
    p.short("X", 10, 100, reason="win", confidence=4)
    p.cover("X", 10, 80, reason="target")       # +200
    p.short("Y", 10, 100, reason="lose", confidence=2)
    p.cover("Y", 10, 110, reason="stop")        # -100
    stats = winners_vs_losers(p.transactions)
    assert stats["closed_trades"] == 2
    assert stats["winners"]["count"] == 1
    assert stats["losers"]["count"] == 1
    assert stats["winners"]["total_pnl"] == 200.0
    assert stats["losers"]["total_pnl"] == -100.0


def test_performance_by_side_separates_long_and_short():
    """The 'is my shorting actually working?' view."""
    p = _p()
    p.buy("A", 10, 100, reason="long", confidence=3)
    p.sell("A", 10, 150, reason="target")        # long +500
    p.short("B", 10, 100, reason="short", confidence=3)
    p.cover("B", 10, 60, reason="target")        # short +400
    sides = performance_by_side(p.transactions)
    assert sides["long"]["total_pnl"] == 500.0
    assert sides["short"]["total_pnl"] == 400.0
    assert sides["long"]["closed_trades"] == 1
    assert sides["short"]["closed_trades"] == 1


def test_performance_by_side_empty_is_safe():
    assert performance_by_side([])["short"]["closed_trades"] == 0


# --- persistence round trip --------------------------------------------------
def test_short_survives_serialization():
    p = _p()
    p.short("X", 10, 100, reason="fade", confidence=4, tags=["t"])
    restored = Portfolio.from_dict(p.to_dict())
    h = restored.holdings["X"]
    assert h.quantity == -10 and h.avg_price == 100.0
    assert restored.transactions[0].type == "SHORT"


# --- API layer ---------------------------------------------------------------
@pytest.fixture
def client(tmp_path):
    app = create_app(data_root=str(tmp_path), start_worker=False, price_source_mode="manual")
    app.config.update(TESTING=True)
    c = app.test_client()
    r = c.post("/auth/register", json={"username": "rishi", "password": "supersecret1"})
    c.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {r.get_json()['token']}"
    c.post("/strategies", json={"name": "Intraday"})
    return c


def test_api_short_then_cover(client):
    r = client.post("/strategies/Intraday/short", json={
        "symbol": "RELIANCE", "quantity": 10, "price": 1300,
        "reason": "spiked 15% today, expecting fade", "confidence": 4,
        "tags": ["mean reversion"],
    })
    assert r.status_code == 201
    assert r.get_json()["transaction"]["type"] == "SHORT"

    r = client.post("/strategies/Intraday/cover", json={
        "symbol": "RELIANCE", "quantity": 10, "price": 1200, "reason": "reverted, target hit",
    })
    assert r.status_code == 201
    assert r.get_json()["realized_pnl"] == 1000.0     # (1300-1200) * 10


def test_api_short_shows_side_in_holdings(client):
    client.post("/strategies/Intraday/short", json={
        "symbol": "TCS", "quantity": 5, "price": 2000,
        "reason": "fade", "confidence": 3,
    })
    holdings = client.get("/strategies/Intraday").get_json()["holdings"]
    assert holdings[0]["side"] == "short"
    assert holdings[0]["quantity"] == -5


def test_api_short_persists_across_requests(client):
    """Proves SHORT/COVER round-trip through SQLite, not just memory."""
    client.post("/strategies/Intraday/short", json={
        "symbol": "INFY", "quantity": 10, "price": 1000,
        "reason": "fade", "confidence": 3,
    })
    detail = client.get("/strategies/Intraday").get_json()
    assert detail["holdings"][0]["quantity"] == -10
    txns = client.get("/strategies/Intraday/transactions").get_json()["transactions"]
    assert txns[0]["type"] == "SHORT"


def test_api_cover_more_than_shorted_returns_409(client):
    client.post("/strategies/Intraday/short", json={
        "symbol": "X", "quantity": 5, "price": 100, "reason": "fade", "confidence": 3,
    })
    r = client.post("/strategies/Intraday/cover", json={
        "symbol": "X", "quantity": 10, "price": 90, "reason": "too many",
    })
    assert r.status_code == 409
    assert r.get_json()["error"]["type"] == "InsufficientHoldings"


def test_api_buy_into_short_returns_400(client):
    client.post("/strategies/Intraday/short", json={
        "symbol": "X", "quantity": 5, "price": 100, "reason": "fade", "confidence": 3,
    })
    r = client.post("/strategies/Intraday/buy", json={
        "symbol": "X", "quantity": 5, "price": 90, "reason": "oops", "confidence": 3,
    })
    assert r.status_code == 400
    assert r.get_json()["error"]["type"] == "InvalidTrade"


def test_api_short_missing_confidence_returns_400(client):
    r = client.post("/strategies/Intraday/short", json={
        "symbol": "X", "quantity": 5, "price": 100, "reason": "fade",
    })
    assert r.status_code == 400


def test_api_analytics_includes_by_side(client):
    client.post("/strategies/Intraday/short", json={
        "symbol": "X", "quantity": 10, "price": 100,
        "reason": "fade", "confidence": 4, "tags": ["mean reversion"],
    })
    client.post("/strategies/Intraday/cover", json={
        "symbol": "X", "quantity": 10, "price": 80, "reason": "target",
    })
    data = client.get("/strategies/Intraday/analytics").get_json()
    assert data["by_side"]["short"]["total_pnl"] == 200.0
    assert data["by_side"]["long"]["closed_trades"] == 0


def test_api_short_pnl_reflected_in_leaderboard(client):
    client.post("/strategies/Intraday/short", json={
        "symbol": "X", "quantity": 10, "price": 100, "reason": "fade", "confidence": 3,
    })
    client.put("/prices/X", json={"price": 80})   # price fell -> short is winning
    board = client.get("/leaderboard").get_json()["leaderboard"]
    assert board[0]["unrealized_pnl"] == 200.0
