"""Phase 4 tests: live price sources, chaining, caching, history.

These use a FAKE source rather than hitting the network, so the suite stays
fast, deterministic, and runnable offline. The real sources are exercised by
`python -m engine.pricecheck` (see that module) — a diagnostic you run by hand,
because a unit test that depends on NSE being reachable is a flaky test.
"""

import pytest

from api import create_app
from engine.prices import (
    CachedPriceSource,
    ChainedPriceSource,
    ManualPriceSource,
    build_source,
    market_is_open,
    normalize,
)


# --- fakes -------------------------------------------------------------------
class FakeSource:
    """Records how many times it was asked, so we can prove caching works."""

    def __init__(self, prices, name="fake"):
        self.prices = prices
        self.name = name
        self.calls = 0

    def get_prices(self, symbols):
        self.calls += 1
        return {s: self.prices[s] for s in symbols if s in self.prices}

    def get_history(self, symbol, period="1mo", interval="1d"):
        return [{"date": "2026-07-20", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10}]


class BrokenSource:
    """Simulates NSE being blocked — raises on every call."""

    name = "broken"

    def get_prices(self, symbols):
        raise ConnectionError("HTTP 403 blocked")


# --- symbol normalization ----------------------------------------------------
def test_normalize_strips_exchange_suffixes():
    assert normalize("reliance") == "RELIANCE"
    assert normalize("RELIANCE.NS") == "RELIANCE"
    assert normalize("ITC.BO") == "ITC"
    assert normalize("  tcs  ") == "TCS"


# --- chaining ----------------------------------------------------------------
def test_chain_falls_through_to_second_source():
    """The whole point of the chain: NSE blocked -> Yahoo answers."""
    chain = ChainedPriceSource([BrokenSource(), FakeSource({"RELIANCE": 1323.1})])
    assert chain.get_prices(["RELIANCE"]) == {"RELIANCE": 1323.1}


def test_chain_prefers_the_first_source_that_has_the_symbol():
    primary = FakeSource({"A": 100.0})
    secondary = FakeSource({"A": 999.0, "B": 50.0})
    chain = ChainedPriceSource([primary, secondary])
    got = chain.get_prices(["A", "B"])
    assert got["A"] == 100.0  # primary wins
    assert got["B"] == 50.0   # only secondary had it


def test_chain_only_asks_later_sources_for_missing_symbols():
    primary = FakeSource({"A": 1.0})
    secondary = FakeSource({"B": 2.0})
    ChainedPriceSource([primary, secondary]).get_prices(["A", "B"])
    assert secondary.calls == 1


def test_chain_returns_empty_when_everything_fails():
    assert ChainedPriceSource([BrokenSource(), BrokenSource()]).get_prices(["X"]) == {}


def test_chain_history_uses_first_source_that_has_it():
    chain = ChainedPriceSource([BrokenSource(), FakeSource({"A": 1})])
    assert len(chain.get_history("A")) == 1


# --- caching -----------------------------------------------------------------
def test_cache_prevents_repeated_upstream_calls():
    fake = FakeSource({"A": 10.0})
    cached = CachedPriceSource(fake, ttl_seconds=60)
    cached.get_prices(["A"])
    cached.get_prices(["A"])
    cached.get_prices(["A"])
    assert fake.calls == 1  # upstream hit once despite three reads


def test_cache_expires():
    fake = FakeSource({"A": 10.0})
    cached = CachedPriceSource(fake, ttl_seconds=0)  # immediately stale
    cached.get_prices(["A"])
    cached.get_prices(["A"])
    assert fake.calls == 2


def test_cache_only_fetches_the_uncached_symbols():
    fake = FakeSource({"A": 1.0, "B": 2.0})
    cached = CachedPriceSource(fake, ttl_seconds=60)
    cached.get_prices(["A"])
    cached.get_prices(["A", "B"])
    assert fake.calls == 2
    assert cached.get_prices(["A", "B"]) == {"A": 1.0, "B": 2.0}


def test_cache_invalidate():
    fake = FakeSource({"A": 1.0})
    cached = CachedPriceSource(fake, ttl_seconds=600)
    cached.get_prices(["A"])
    cached.invalidate()
    cached.get_prices(["A"])
    assert fake.calls == 2


# --- manual source -----------------------------------------------------------
def test_manual_source_roundtrip():
    m = ManualPriceSource({"RELIANCE": 100})
    m.set_price("tcs", 200)
    assert m.get_prices(["RELIANCE", "TCS", "MISSING"]) == {"RELIANCE": 100.0, "TCS": 200.0}


# --- factory -----------------------------------------------------------------
def test_build_source_manual_mode_has_no_network():
    assert isinstance(build_source("manual"), ManualPriceSource)


def test_build_source_auto_is_cached_chain():
    src = build_source("auto")
    assert isinstance(src, CachedPriceSource)
    assert isinstance(src.source, ChainedPriceSource)


# --- market hours ------------------------------------------------------------
def test_market_closed_on_weekend():
    from datetime import datetime, timezone

    saturday = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)  # Sat, ~11:30 IST
    assert market_is_open(saturday) is False


def test_market_open_during_weekday_session():
    from datetime import datetime, timezone

    # Monday 2026-07-20, 06:00 UTC == 11:30 IST -> inside 09:15–15:30
    assert market_is_open(datetime(2026, 7, 20, 6, 0, tzinfo=timezone.utc)) is True
    # 04:00 UTC == 09:30 IST -> open
    assert market_is_open(datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc)) is True
    # 12:00 UTC == 17:30 IST -> closed
    assert market_is_open(datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)) is False


# --- API integration (with a fake source injected) ---------------------------
@pytest.fixture
def client(tmp_path):
    app = create_app(data_root=str(tmp_path), start_worker=False, price_source_mode="manual")
    app.config.update(TESTING=True)
    # Inject a fake live source so the endpoints are exercised without network.
    app.config["PRICE_SOURCE"] = FakeSource({"RELIANCE": 1323.1, "TCS": 2251.1})
    c = app.test_client()
    r = c.post("/auth/register", json={"username": "rishi", "password": "supersecret1"})
    c.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {r.get_json()['token']}"
    return c


def _buy(client, symbol="RELIANCE", price=1200):
    client.post("/strategies/M/buy", json={
        "symbol": symbol, "quantity": 10, "price": price,
        "reason": "x", "confidence": 3,
    })


def test_refresh_pulls_live_prices_into_the_store(client):
    client.post("/strategies", json={"name": "M"})
    _buy(client, "RELIANCE", 1200)
    r = client.post("/prices/refresh")
    assert r.status_code == 200
    assert r.get_json()["refreshed"]["RELIANCE"] == 1323.1
    # the persisted store now holds the live value
    assert client.get("/prices").get_json()["prices"]["RELIANCE"] == 1323.1


def test_refresh_updates_unrealized_pnl(client):
    client.post("/strategies", json={"name": "M"})
    _buy(client, "RELIANCE", 1200)  # bought at 1200
    assert client.get("/strategies/M").get_json()["unrealized_pnl"] == 0.0
    client.post("/prices/refresh")
    # live price 1323.1 -> (1323.1-1200)*10 = 1231.0
    assert client.get("/strategies/M").get_json()["unrealized_pnl"] == 1231.0


def test_refresh_fires_alerts(client):
    client.post("/strategies", json={"name": "M"})
    _buy(client, "RELIANCE", 1200)
    client.post("/alerts", json={"symbol": "RELIANCE", "target_price": 1300, "direction": "above"})
    r = client.post("/prices/refresh")
    assert len(r.get_json()["triggered"]) == 1


def test_refresh_with_no_holdings_is_a_noop(client):
    assert client.post("/prices/refresh").get_json()["count"] == 0


def test_history_endpoint(client):
    r = client.get("/prices/RELIANCE/history?period=1mo&interval=1d")
    assert r.status_code == 200
    body = r.get_json()
    assert body["symbol"] == "RELIANCE"
    assert body["candles"][0]["close"] == 1.5


def test_history_rejects_bad_period(client):
    assert client.get("/prices/X/history?period=evil").status_code == 400


def test_history_rejects_bad_interval(client):
    assert client.get("/prices/X/history?interval=99y").status_code == 400


def test_history_unavailable_returns_502(client, tmp_path):
    class NoData(FakeSource):
        def get_history(self, symbol, period="1mo", interval="1d"):
            return []

    client.application.config["PRICE_SOURCE"] = NoData({})
    assert client.get("/prices/X/history").status_code == 502


def test_sources_endpoint_reports_diagnostics(client):
    body = client.get("/prices/sources").get_json()
    assert "mode" in body and "market_open" in body
    assert "reachable" in body["nse"]  # honest about whether NSE works here
