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


# --- named watchlists ---------------------------------------------------------
def _create_list(client, name="Swing"):
    r = client.post("/watchlists", json={"name": name})
    assert r.status_code == 201
    return r.get_json()["watchlist"]["id"]


def test_create_watchlist_starts_empty(client):
    wl = client.post("/watchlists", json={"name": "Swing"}).get_json()["watchlist"]
    assert wl["name"] == "Swing"
    assert wl["stocks"] == []


def test_no_watchlists_by_default(client):
    assert client.get("/watchlists").get_json()["watchlists"] == []


def test_duplicate_watchlist_names_allowed(client):
    _create_list(client, "Swing")
    _create_list(client, "Swing")
    names = [w["name"] for w in client.get("/watchlists").get_json()["watchlists"]]
    assert names == ["Swing", "Swing"]


def test_add_symbol_lists_quotes_and_change(client):
    wl_id = _create_list(client, "Swing")
    assert client.post(f"/watchlists/{wl_id}/symbols", json={"symbol": "reliance"}).status_code == 201
    watchlists = client.get("/watchlists").get_json()["watchlists"]
    stocks = watchlists[0]["stocks"]
    assert len(stocks) == 1
    row = stocks[0]
    assert row["symbol"] == "RELIANCE"
    assert row["name"] == "Reliance Industries"
    assert row["price"] == 1323.1           # fetched immediately on add
    assert row["prev_close"] == 1300.0
    assert row["change"] == 23.1
    assert row["change_pct"] == 1.78


def test_same_symbol_in_two_lists_independently(client):
    """The core feature: RELIANCE can sit in both Swing and Intraday at once."""
    swing = _create_list(client, "Swing")
    intraday = _create_list(client, "Intraday")
    client.post(f"/watchlists/{swing}/symbols", json={"symbol": "RELIANCE"})
    client.post(f"/watchlists/{intraday}/symbols", json={"symbol": "RELIANCE"})
    watchlists = client.get("/watchlists").get_json()["watchlists"]
    assert watchlists[0]["stocks"][0]["symbol"] == "RELIANCE"
    assert watchlists[1]["stocks"][0]["symbol"] == "RELIANCE"


def test_add_symbol_twice_to_same_list_is_noop(client):
    wl_id = _create_list(client)
    client.post(f"/watchlists/{wl_id}/symbols", json={"symbol": "TCS"})
    client.post(f"/watchlists/{wl_id}/symbols", json={"symbol": "TCS"})
    watchlists = client.get("/watchlists").get_json()["watchlists"]
    assert len(watchlists[0]["stocks"]) == 1


def test_remove_symbol(client):
    wl_id = _create_list(client)
    client.post(f"/watchlists/{wl_id}/symbols", json={"symbol": "TCS"})
    assert client.delete(f"/watchlists/{wl_id}/symbols/TCS").status_code == 200
    watchlists = client.get("/watchlists").get_json()["watchlists"]
    assert watchlists[0]["stocks"] == []


def test_remove_symbol_missing_404(client):
    wl_id = _create_list(client)
    assert client.delete(f"/watchlists/{wl_id}/symbols/GHOST").status_code == 404


def test_add_symbol_to_unknown_watchlist_404(client):
    assert client.post("/watchlists/999/symbols", json={"symbol": "TCS"}).status_code == 404


def test_delete_watchlist(client):
    wl_id = _create_list(client)
    assert client.delete(f"/watchlists/{wl_id}").status_code == 200
    assert client.get("/watchlists").get_json()["watchlists"] == []


def test_delete_watchlist_missing_404(client):
    assert client.delete("/watchlists/999").status_code == 404


def test_deleting_one_watchlist_leaves_others(client):
    a = _create_list(client, "Swing")
    _create_list(client, "Intraday")
    client.delete(f"/watchlists/{a}")
    names = [w["name"] for w in client.get("/watchlists").get_json()["watchlists"]]
    assert names == ["Intraday"]


def test_watchlist_isolated_per_user(client, tmp_path):
    """A second user must not see or modify the first user's watchlists."""
    from api import create_app as _create_app

    app2 = _create_app(data_root=str(tmp_path), start_worker=False, price_source_mode="manual")
    c2 = app2.test_client()
    r2 = c2.post("/auth/register", json={"username": "bob", "password": "supersecret1"})
    c2.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {r2.get_json()['token']}"

    wl_id = _create_list(client, "Swing")  # belongs to the first user
    assert c2.get("/watchlists").get_json()["watchlists"] == []
    assert c2.post(f"/watchlists/{wl_id}/symbols", json={"symbol": "TCS"}).status_code == 404
    assert c2.delete(f"/watchlists/{wl_id}").status_code == 404


def test_watchlist_symbols_reach_background_price_job(client, tmp_path):
    from api.jobs import symbols_of_interest

    wl_id = _create_list(client)
    client.post(f"/watchlists/{wl_id}/symbols", json={"symbol": "WIPRO"})
    assert "WIPRO" in symbols_of_interest(str(tmp_path))


# --- legacy flat-watchlist migration ------------------------------------------
def test_legacy_watchlist_migrates_into_named_list(tmp_path):
    """Simulate an old-schema database (before named watchlists existed) and
    confirm init_db() moves its entries into a "Watchlist" list per user
    instead of silently losing them."""
    import sqlite3

    from engine.db import init_db
    from engine.repository import WatchlistRepository

    db_path = str(tmp_path / "legacy.db")
    init_db(db_path)  # creates the current schema, including watchlists tables

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO users (id, username, password_hash, created_at) VALUES ('u1','bob','x','now')"
    )
    # Recreate the OLD flat table shape and seed it, as if this were a
    # pre-migration database.
    conn.execute(
        "CREATE TABLE watchlist (user_id TEXT, symbol TEXT, added_at TEXT, "
        "PRIMARY KEY (user_id, symbol))"
    )
    conn.execute("INSERT INTO watchlist VALUES ('u1', 'RELIANCE', 'then')")
    conn.execute("INSERT INTO watchlist VALUES ('u1', 'INFY', 'then')")
    conn.commit()
    conn.close()

    init_db(db_path)  # run migration

    repo = WatchlistRepository(db_path, "u1")
    lists = repo.list_all()
    assert len(lists) == 1
    assert lists[0]["name"] == "Watchlist"
    assert sorted(lists[0]["symbols"]) == ["INFY", "RELIANCE"]

    # old table is gone; re-running init_db again must not error or duplicate
    init_db(db_path)
    assert len(WatchlistRepository(db_path, "u1").list_all()) == 1


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
