"""Tests for symbol search, watchlist, and the quote endpoint."""

import pytest

from api import create_app
from engine import symbols


# --- symbol search (pure) ----------------------------------------------------
def test_search_prefers_symbol_prefix():
    results = symbols.search("REL")
    assert results[0]["symbol"] == "RELIANCE"


def test_search_matches_company_name():
    results = symbols.search("tata consultancy")
    assert results[0]["symbol"] == "TCS"


def test_search_substring_and_limit():
    assert len(symbols.search("BANK", limit=5)) == 5


def test_search_empty_query_returns_nothing():
    assert symbols.search("") == []
    assert symbols.search("   ") == []


def test_name_of():
    assert symbols.name_of("itc") == "ITC"
    assert symbols.name_of("NOSUCH") is None


# --- API fixtures ------------------------------------------------------------
class FakeSource:
    """Live source with current prices and previous closes."""

    def __init__(self, prices, prev):
        self.prices = prices
        self.prev = prev

    def get_prices(self, syms):
        return {s: self.prices[s] for s in syms if s in self.prices}

    def get_prev_closes(self, syms):
        return {s: self.prev[s] for s in syms if s in self.prev}


@pytest.fixture
def client(tmp_path):
    app = create_app(data_root=str(tmp_path), start_worker=False, price_source_mode="manual")
    app.config.update(TESTING=True)
    app.config["PRICE_SOURCE"] = FakeSource(
        prices={"RELIANCE": 1323.1, "TCS": 2251.1},
        prev={"RELIANCE": 1300.0, "TCS": 2300.0},
    )
    c = app.test_client()
    r = c.post("/auth/register", json={"username": "rishi", "password": "supersecret1"})
    c.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {r.get_json()['token']}"
    return c


# --- search endpoint ---------------------------------------------------------
def test_search_endpoint(client):
    r = client.get("/symbols/search?q=infy")
    assert r.status_code == 200
    assert r.get_json()["results"][0]["symbol"] == "INFY"


def test_search_requires_auth(tmp_path):
    app = create_app(data_root=str(tmp_path), start_worker=False, price_source_mode="manual")
    assert app.test_client().get("/symbols/search?q=x").status_code == 401


# --- watchlist ---------------------------------------------------------------
def test_watchlist_add_lists_quotes_and_change(client):
    assert client.post("/watchlist", json={"symbol": "reliance"}).status_code == 201
    rows = client.get("/watchlist").get_json()["watchlist"]
    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "RELIANCE"
    assert row["name"] == "Reliance Industries"
    assert row["price"] == 1323.1           # fetched immediately on add
    assert row["prev_close"] == 1300.0
    assert row["change"] == 23.1
    assert row["change_pct"] == 1.78


def test_watchlist_add_twice_is_noop(client):
    client.post("/watchlist", json={"symbol": "TCS"})
    client.post("/watchlist", json={"symbol": "TCS"})
    assert len(client.get("/watchlist").get_json()["watchlist"]) == 1


def test_watchlist_remove(client):
    client.post("/watchlist", json={"symbol": "TCS"})
    assert client.delete("/watchlist/TCS").status_code == 200
    assert client.get("/watchlist").get_json()["watchlist"] == []


def test_watchlist_remove_missing_404(client):
    assert client.delete("/watchlist/GHOST").status_code == 404


def test_watchlist_symbols_reach_background_price_job(client, tmp_path):
    from api.jobs import symbols_of_interest

    client.post("/watchlist", json={"symbol": "WIPRO"})
    assert "WIPRO" in symbols_of_interest(str(tmp_path))


# --- quote endpoint ----------------------------------------------------------
def test_quote_live(client):
    body = client.get("/prices/quote/RELIANCE").get_json()
    assert body["price"] == 1323.1
    assert body["live"] is True
    assert body["name"] == "Reliance Industries"


def test_quote_falls_back_to_last_known(client):
    client.put("/prices/OBSCURE", json={"price": 55.5})  # only in the table
    body = client.get("/prices/quote/OBSCURE").get_json()
    assert body["price"] == 55.5
    assert body["live"] is False


def test_quote_unknown_symbol_404(client):
    assert client.get("/prices/quote/NOSUCHSTOCK").status_code == 404
