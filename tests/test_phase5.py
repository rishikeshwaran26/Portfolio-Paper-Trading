"""Phase 5 tests: auth boundary, alerts, snapshots, journal insight layer."""

import pytest

from api import create_app
from api.jobs import capture_snapshot_for_user, check_all_alerts, check_alerts_for_user
from api.paths import all_user_ids, db_file
from engine.alerts import ABOVE, BELOW
from engine.db import init_db
from engine.journal import winners_vs_losers
from engine.portfolio import Portfolio
from engine.repository import (
    AlertRepository,
    PriceRepository,
    SnapshotRepository,
    SqlitePortfolioManager,
)


# --- fixtures ----------------------------------------------------------------
@pytest.fixture
def app(tmp_path):
    a = create_app(data_root=str(tmp_path), start_worker=False, price_source_mode="manual")
    a.config.update(TESTING=True)
    return a


@pytest.fixture
def anon(app):
    return app.test_client()


@pytest.fixture
def client(anon):
    r = anon.post("/auth/register", json={"username": "rishi", "password": "supersecret1"})
    anon.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {r.get_json()['token']}"
    return anon


# --- auth --------------------------------------------------------------------
def test_status_reports_no_users_initially(anon):
    assert anon.get("/auth/status").get_json()["has_users"] is False


def test_register_then_login(anon):
    anon.post("/auth/register", json={"username": "rishi", "password": "supersecret1"})
    assert anon.get("/auth/status").get_json()["has_users"] is True
    r = anon.post("/auth/login", json={"username": "rishi", "password": "supersecret1"})
    assert r.status_code == 200 and r.get_json()["token"]


def test_login_wrong_password_401(anon):
    anon.post("/auth/register", json={"username": "rishi", "password": "supersecret1"})
    r = anon.post("/auth/login", json={"username": "rishi", "password": "wrongwrong"})
    assert r.status_code == 401
    assert r.get_json()["error"]["type"] == "InvalidCredentials"


def test_duplicate_username_409(anon):
    anon.post("/auth/register", json={"username": "rishi", "password": "supersecret1"})
    r = anon.post("/auth/register", json={"username": "RISHI", "password": "supersecret1"})
    assert r.status_code == 409


def test_short_password_rejected(anon):
    r = anon.post("/auth/register", json={"username": "rishi", "password": "short"})
    assert r.status_code == 400


def test_password_hash_never_returned(anon):
    r = anon.post("/auth/register", json={"username": "rishi", "password": "supersecret1"})
    assert "password_hash" not in r.get_json()["user"]


def test_protected_route_without_token_401(anon):
    assert anon.get("/strategies").status_code == 401


def test_protected_route_with_bad_token_401(anon):
    anon.environ_base["HTTP_AUTHORIZATION"] = "Bearer not-a-real-token"
    r = anon.get("/strategies")
    assert r.status_code == 401
    assert r.get_json()["error"]["type"] == "InvalidToken"


def test_me_returns_current_user(client):
    assert client.get("/auth/me").get_json()["user"]["username"] == "rishi"


def test_two_users_have_isolated_data(app):
    """The core multi-user-readiness check: user B must not see user A's data."""
    a, b = app.test_client(), app.test_client()
    ta = a.post("/auth/register", json={"username": "alice", "password": "supersecret1"}).get_json()["token"]
    tb = b.post("/auth/register", json={"username": "bob", "password": "supersecret1"}).get_json()["token"]
    a.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {ta}"
    b.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {tb}"

    a.post("/strategies", json={"name": "Alice Only"})
    assert [s["name"] for s in a.get("/strategies").get_json()["strategies"]] == ["Alice Only"]
    assert b.get("/strategies").get_json()["strategies"] == []
    assert b.get("/strategies/Alice Only").status_code == 404
    assert len(all_user_ids(app.config["DATA_ROOT"])) == 2


# --- alerts: engine rule -----------------------------------------------------
@pytest.fixture
def alert_repo(tmp_path):
    """An AlertRepository on a throwaway db with one user row."""
    db = str(tmp_path / "t.db")
    init_db(db)
    from engine.repository import UserRepository
    UserRepository(db).insert({"id": "u1", "username": "t", "password_hash": "x", "created_at": "now"})
    return AlertRepository(db, "u1")


def test_alert_above_triggers_at_or_over_target(alert_repo):
    store = alert_repo
    a = store.add("RELIANCE", 2900, ABOVE)
    assert a.should_trigger(2899) is False
    assert a.should_trigger(2900) is True
    assert a.should_trigger(2950) is True


def test_alert_below_triggers_at_or_under_target(alert_repo):
    store = alert_repo
    a = store.add("TCS", 3000, BELOW)
    assert a.should_trigger(3001) is False
    assert a.should_trigger(3000) is True
    assert a.should_trigger(2900) is True


def test_triggered_alert_does_not_refire(alert_repo):
    store = alert_repo
    store.add("X", 100, ABOVE)
    assert len(store.check({"X": 150})) == 1
    assert len(store.check({"X": 160})) == 0  # already triggered
    assert len(store.triggered()) == 1


def test_alert_ignores_symbols_without_price(alert_repo):
    store = alert_repo
    store.add("NOPRICE", 100, ABOVE)
    assert store.check({"OTHER": 500}) == []


def test_alert_persists_across_reload(alert_repo):
    alert_repo.add("X", 100, ABOVE, note="watch this")
    reloaded = AlertRepository(alert_repo.db_path, alert_repo.user_id)
    assert len(reloaded.alerts) == 1 and reloaded.alerts[0].note == "watch this"


def test_invalid_direction_rejected(alert_repo):
    with pytest.raises(ValueError):
        alert_repo.add("X", 100, "sideways")


# --- alerts: API + background job -------------------------------------------
def test_alert_crud_via_api(client):
    r = client.post("/alerts", json={"symbol": "RELIANCE", "target_price": 2900, "direction": "above"})
    assert r.status_code == 201
    alert_id = r.get_json()["alert"]["id"]
    assert len(client.get("/alerts").get_json()["alerts"]) == 1
    assert client.delete(f"/alerts/{alert_id}").status_code == 200
    assert client.get("/alerts").get_json()["alerts"] == []


def test_alert_bad_direction_400(client):
    r = client.post("/alerts", json={"symbol": "X", "target_price": 10, "direction": "up"})
    assert r.status_code == 400


def test_setting_price_triggers_alert_immediately(client):
    client.post("/alerts", json={"symbol": "RELIANCE", "target_price": 2900, "direction": "above"})
    r = client.put("/prices/RELIANCE", json={"price": 2950})
    assert len(r.get_json()["triggered"]) == 1
    assert len(client.get("/alerts").get_json()["triggered"]) == 1


def test_dismiss_removes_from_banner(client):
    client.post("/alerts", json={"symbol": "X", "target_price": 100, "direction": "above"})
    client.put("/prices/X", json={"price": 120})
    aid = client.get("/alerts").get_json()["triggered"][0]["id"]
    client.post(f"/alerts/{aid}/dismiss")
    assert client.get("/alerts").get_json()["triggered"] == []


def test_background_checker_fires_alerts(app, client):
    """The job the worker thread runs, invoked directly (no thread needed)."""
    client.post("/alerts", json={"symbol": "INFY", "target_price": 1500, "direction": "below"})
    root = app.config["DATA_ROOT"]
    uid = all_user_ids(root)[0]
    # price is above target -> nothing fires
    DataPathsPrices(root, 1600)
    assert check_alerts_for_user(root, uid) == []
    # price drops below target -> fires
    DataPathsPrices(root, 1400)
    assert len(check_alerts_for_user(root, uid)) == 1


def DataPathsPrices(root, price):
    """Helper: set INFY's shared price directly in the db."""
    PriceRepository(db_file(root)).set_price("INFY", price)


def test_check_all_alerts_sweeps_every_user(app):
    a, b = app.test_client(), app.test_client()
    for c, u in ((a, "alice"), (b, "bob")):
        t = c.post("/auth/register", json={"username": u, "password": "supersecret1"}).get_json()["token"]
        c.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {t}"
        c.post("/alerts", json={"symbol": "Z", "target_price": 50, "direction": "above"})
    PriceRepository(db_file(app.config["DATA_ROOT"])).set_price("Z", 99)
    assert check_all_alerts(app.config["DATA_ROOT"]) == 2  # one per user


# --- snapshots ---------------------------------------------------------------
@pytest.fixture
def snap(tmp_path):
    """A manager + snapshot repository sharing one throwaway db."""
    db = str(tmp_path / "t.db")
    init_db(db)
    from engine.repository import UserRepository
    UserRepository(db).insert({"id": "u1", "username": "t", "password_hash": "x", "created_at": "now"})
    return SqlitePortfolioManager(db, "u1"), SnapshotRepository(db, "u1")


def test_snapshot_capture_records_every_strategy(snap):
    m, store = snap
    m.create_strategy("A", 100_000)
    m.create_strategy("B", 100_000)
    m.save()
    taken = store.capture(m, {})
    assert len(taken) == 2
    assert {s.strategy for s in taken} == {"A", "B"}


def test_snapshot_same_day_upserts_not_duplicates(snap):
    m, store = snap
    m.create_strategy("A", 100_000)
    m.save()
    store.capture(m, {})
    store.capture(m, {})  # same day again
    assert len(store.snapshots) == 1  # replaced, not appended


def test_series_is_chart_shaped(snap):
    m, store = snap
    a = m.create_strategy("A", 100_000)
    m.create_strategy("B", 100_000)
    a.buy("X", 10, 1000, reason="x", confidence=3)
    m.save()
    store.capture(m, {"X": 2000})  # A gains
    series = store.series()
    assert len(series) == 1
    row = series[0]
    assert "date" in row and "A" in row and "B" in row
    assert row["A"] > row["B"]


def test_snapshot_endpoint_and_manual_capture(client):
    client.post("/strategies", json={"name": "Momentum"})
    assert client.get("/snapshots").get_json()["series"] == []
    r = client.post("/snapshots/capture")
    assert r.status_code == 201
    data = client.get("/snapshots").get_json()
    assert data["strategies"] == ["Momentum"]
    assert len(data["series"]) == 1


def test_snapshot_job_for_user(app, client):
    client.post("/strategies", json={"name": "S"})
    root = app.config["DATA_ROOT"]
    uid = all_user_ids(root)[0]
    assert len(capture_snapshot_for_user(root, uid)) == 1


def test_snapshot_sweep_picks_up_users_registered_later(app):
    """Regression: the first version only snapshotted once at boot, so a user
    who registered afterwards had an empty chart until the next daily firing.
    The sweep must find users that did not exist on the previous pass."""
    from api.jobs import capture_all_snapshots

    root = app.config["DATA_ROOT"]
    assert capture_all_snapshots(root) == 0  # no users yet

    c = app.test_client()
    t = c.post("/auth/register", json={"username": "late", "password": "supersecret1"}).get_json()["token"]
    c.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {t}"
    c.post("/strategies", json={"name": "Late Strategy"})

    # A later sweep must now capture the newly-registered user's strategy.
    assert capture_all_snapshots(root) == 1
    assert c.get("/snapshots").get_json()["strategies"] == ["Late Strategy"]


def test_repeated_sweeps_keep_one_row_per_day(app, client):
    """The sweep runs every few minutes; the data must stay daily."""
    from api.jobs import capture_all_snapshots

    client.post("/strategies", json={"name": "S"})
    root = app.config["DATA_ROOT"]
    capture_all_snapshots(root)
    capture_all_snapshots(root)
    capture_all_snapshots(root)
    assert len(client.get("/snapshots").get_json()["series"]) == 1


def test_snapshots_filtered_by_strategy(client):
    client.post("/strategies", json={"name": "A"})
    client.post("/strategies", json={"name": "B"})
    client.post("/snapshots/capture")
    row = client.get("/snapshots?strategies=A").get_json()["series"][0]
    assert "A" in row and "B" not in row


# --- journal insight layer ---------------------------------------------------
def _mixed_portfolio() -> Portfolio:
    """Two quick winners and one long-held loser — the classic pattern the
    winners-vs-losers view is meant to expose."""
    p = Portfolio(name="J", cash=1_000_000)
    p.buy("A", 10, 100, reason="win", confidence=5, tags=["breakout"])
    p.sell("A", 10, 150, reason="target")          # +500
    p.buy("B", 10, 100, reason="win", confidence=4, tags=["breakout"])
    p.sell("B", 10, 130, reason="target")          # +300
    p.buy("C", 10, 100, reason="loss", confidence=2, tags=["earnings play"])
    p.sell("C", 10, 60, reason="stop")             # -400
    return p


def test_winners_vs_losers_splits_correctly():
    stats = winners_vs_losers(_mixed_portfolio().transactions)
    assert stats["winners"]["count"] == 2
    assert stats["losers"]["count"] == 1
    assert stats["winners"]["total_pnl"] == 800.0
    assert stats["losers"]["total_pnl"] == -400.0
    assert stats["closed_trades"] == 3
    assert round(stats["win_rate"], 2) == 0.67


def test_winners_vs_losers_reports_avg_confidence():
    stats = winners_vs_losers(_mixed_portfolio().transactions)
    assert stats["winners"]["avg_confidence"] == 4.5  # (5+4)/2
    assert stats["losers"]["avg_confidence"] == 2.0


def test_payoff_ratio_computed():
    stats = winners_vs_losers(_mixed_portfolio().transactions)
    # avg win 400, avg loss -400 -> ratio 1.0
    assert stats["payoff_ratio"] == 1.0


def test_winners_vs_losers_empty_is_safe():
    stats = winners_vs_losers([])
    assert stats["closed_trades"] == 0
    assert stats["win_rate"] == 0.0
    assert stats["payoff_ratio"] is None


def test_analytics_endpoint_includes_all_three_views(client):
    client.post("/strategies", json={"name": "M"})
    client.post("/strategies/M/buy", json={
        "symbol": "A", "quantity": 10, "price": 100,
        "reason": "x", "confidence": 5, "tags": ["breakout"],
    })
    client.post("/strategies/M/sell", json={
        "symbol": "A", "quantity": 10, "price": 150, "reason": "target",
    })
    data = client.get("/strategies/M/analytics").get_json()
    assert "by_confidence" in data and "by_tag" in data and "winners_vs_losers" in data
    assert data["winners_vs_losers"]["winners"]["count"] == 1
