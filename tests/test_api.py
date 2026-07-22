"""API tests using Flask's test client — exercises real routes, no live server.

Each test gets its own app pointed at a temp data + prices file (via tmp_path),
so tests never touch your real data/ and never interfere with each other.
"""

import pytest

from api import create_app


@pytest.fixture
def anon(tmp_path):
    """An UNauthenticated client, for testing the auth boundary itself."""
    app = create_app(data_root=str(tmp_path), start_worker=False, price_source_mode="manual")
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def client(anon):
    """A logged-in client. Registers a user and attaches the bearer token to
    every subsequent request via environ_base, so individual tests don't have to
    thread headers through by hand."""
    r = anon.post("/auth/register", json={"username": "rishi", "password": "supersecret1"})
    assert r.status_code == 201
    token = r.get_json()["token"]
    anon.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return anon


def _create(client, name="Momentum", cash=1_000_000):
    return client.post("/strategies", json={"name": name, "starting_cash": cash})


def _buy(client, name="Momentum", **over):
    body = {
        "symbol": "RELIANCE",
        "quantity": 10,
        "price": 2500,
        "reason": "breakout",
        "confidence": 4,
        "tags": ["technical breakout"],
    }
    body.update(over)
    return client.post(f"/strategies/{name}/buy", json=body)


# --- health ------------------------------------------------------------------
def test_index_ok(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


# --- create / list / get -----------------------------------------------------
def test_create_strategy_returns_201_and_location(client):
    r = _create(client)
    assert r.status_code == 201
    assert r.headers["Location"] == "/strategies/Momentum"
    body = r.get_json()
    assert body["name"] == "Momentum"
    assert body["cash"] == 1_000_000
    assert body["total_value"] == 1_000_000


def test_create_duplicate_returns_409(client):
    _create(client)
    r = _create(client)
    assert r.status_code == 409
    assert r.get_json()["error"]["type"] == "StrategyExists"


def test_create_missing_name_returns_400(client):
    r = client.post("/strategies", json={"starting_cash": 500})
    assert r.status_code == 400
    assert r.get_json()["error"]["type"] == "BadRequest"


def test_create_non_json_returns_400(client):
    r = client.post("/strategies", data="not json", content_type="text/plain")
    assert r.status_code == 400


def test_list_strategies(client):
    _create(client, "A")
    _create(client, "B")
    r = client.get("/strategies")
    names = {s["name"] for s in r.get_json()["strategies"]}
    assert names == {"A", "B"}


def test_get_unknown_strategy_returns_404(client):
    r = client.get("/strategies/Ghost")
    assert r.status_code == 404
    assert r.get_json()["error"]["type"] == "NotFound"


def test_delete_strategy_removes_it(client):
    _create(client, "Doomed")
    _buy(client, "Doomed")  # give it a holding + transaction to cascade-delete
    r = client.delete("/strategies/Doomed")
    assert r.status_code == 200
    assert r.get_json()["deleted"] == "Doomed"
    # gone from the list and individually 404s now
    assert client.get("/strategies").get_json()["strategies"] == []
    assert client.get("/strategies/Doomed").status_code == 404


def test_delete_unknown_strategy_returns_404(client):
    r = client.delete("/strategies/Ghost")
    assert r.status_code == 404
    assert r.get_json()["error"]["type"] == "NotFound"


def test_delete_strategy_leaves_others(client):
    _create(client, "Keep")
    _create(client, "Drop")
    client.delete("/strategies/Drop")
    names = {s["name"] for s in client.get("/strategies").get_json()["strategies"]}
    assert names == {"Keep"}


# --- buy ---------------------------------------------------------------------
def test_buy_succeeds_and_reduces_cash(client):
    _create(client)
    r = _buy(client)
    assert r.status_code == 201
    body = r.get_json()
    assert body["cash"] == 1_000_000 - 25_000
    assert body["transaction"]["confidence"] == 4
    assert body["transaction"]["tags"] == ["technical breakout"]


def test_buy_insufficient_funds_returns_409(client):
    _create(client, cash=1000)
    r = _buy(client, quantity=10, price=2500)  # needs 25000
    assert r.status_code == 409
    assert r.get_json()["error"]["type"] == "InsufficientFunds"


def test_buy_missing_reason_returns_400(client):
    _create(client)
    r = client.post(
        "/strategies/Momentum/buy",
        json={"symbol": "X", "quantity": 1, "price": 10, "confidence": 3},
    )
    assert r.status_code == 400


def test_buy_bad_confidence_type_returns_400(client):
    _create(client)
    r = _buy(client, confidence="high")
    assert r.status_code == 400


def test_buy_confidence_out_of_range_returns_400(client):
    # confidence is an int (passes syntactic check) but 9 is rejected by the
    # engine's semantic rule -> InvalidTrade -> 400.
    _create(client)
    r = _buy(client, confidence=9)
    assert r.status_code == 400
    assert r.get_json()["error"]["type"] == "InvalidTrade"


def test_buy_float_quantity_returns_400(client):
    _create(client)
    r = _buy(client, quantity=10.5)
    assert r.status_code == 400


def test_buy_on_unknown_strategy_returns_404(client):
    r = _buy(client, name="Ghost")
    assert r.status_code == 404


# --- sell --------------------------------------------------------------------
def test_sell_realizes_pnl(client):
    _create(client)
    _buy(client, quantity=10, price=2500)
    r = client.post(
        "/strategies/Momentum/sell",
        json={"symbol": "RELIANCE", "quantity": 10, "price": 2700, "reason": "target"},
    )
    assert r.status_code == 201
    assert r.get_json()["realized_pnl"] == 2000.0


def test_sell_too_many_returns_409(client):
    _create(client)
    _buy(client, quantity=5, price=2500)
    r = client.post(
        "/strategies/Momentum/sell",
        json={"symbol": "RELIANCE", "quantity": 10, "price": 2700, "reason": "x"},
    )
    assert r.status_code == 409
    assert r.get_json()["error"]["type"] == "InsufficientHoldings"


# --- transactions + filters --------------------------------------------------
def test_transactions_and_filter(client):
    _create(client)
    _buy(client)
    client.post(
        "/strategies/Momentum/sell",
        json={"symbol": "RELIANCE", "quantity": 5, "price": 2600, "reason": "trim"},
    )
    all_txns = client.get("/strategies/Momentum/transactions").get_json()["transactions"]
    assert len(all_txns) == 2
    sells = client.get("/strategies/Momentum/transactions?type=SELL").get_json()["transactions"]
    assert len(sells) == 1 and sells[0]["type"] == "SELL"


# --- prices + P&L movement ---------------------------------------------------
def test_price_update_moves_unrealized_pnl(client):
    _create(client)
    _buy(client, quantity=10, price=2500)
    # Before moving price, latest price == buy price -> zero unrealized.
    detail = client.get("/strategies/Momentum").get_json()
    assert detail["unrealized_pnl"] == 0.0
    # Move the price up ₹200 -> +₹2000 unrealized on 10 shares.
    client.put("/prices/RELIANCE", json={"price": 2700})
    detail = client.get("/strategies/Momentum").get_json()
    assert detail["unrealized_pnl"] == 2000.0


# --- leaderboard -------------------------------------------------------------
def test_leaderboard_ranks_strategies(client):
    _create(client, "A")
    _create(client, "B")
    _buy(client, name="A", symbol="X", quantity=10, price=1000)
    _buy(client, name="B", symbol="Y", quantity=10, price=1000)
    client.put("/prices/X", json={"price": 2000})  # A gains more
    client.put("/prices/Y", json={"price": 1100})
    board = client.get("/leaderboard").get_json()["leaderboard"]
    assert board[0]["strategy"] == "A"
    assert board[0]["rank"] == 1


# --- review ------------------------------------------------------------------
def test_review_closed_trade(client):
    _create(client)
    _buy(client, symbol="A", quantity=10, price=100, confidence=5)
    sell = client.post(
        "/strategies/Momentum/sell",
        json={"symbol": "A", "quantity": 10, "price": 150, "reason": "target"},
    ).get_json()
    txn_id = sell["transaction"]["id"]
    r = client.post(
        f"/strategies/Momentum/transactions/{txn_id}/review",
        json={"notes": "sold too early, ran further"},
    )
    assert r.status_code == 200
    assert r.get_json()["transaction"]["review"] == "sold too early, ran further"


def test_review_unknown_txn_returns_404(client):
    _create(client)
    r = client.post(
        "/strategies/Momentum/transactions/nope/review", json={"notes": "x"}
    )
    assert r.status_code == 404


# --- analytics ---------------------------------------------------------------
def test_analytics_buckets_by_confidence(client):
    _create(client)
    _buy(client, symbol="A", quantity=10, price=100, confidence=5)
    client.post(
        "/strategies/Momentum/sell",
        json={"symbol": "A", "quantity": 10, "price": 150, "reason": "target"},
    )
    data = client.get("/strategies/Momentum/analytics").get_json()
    conf5 = [row for row in data["by_confidence"] if row["label"] == "confidence 5"]
    assert conf5 and conf5[0]["total_pnl"] == 500.0
