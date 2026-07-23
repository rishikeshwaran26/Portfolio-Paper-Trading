"""Tests for the backtest engine: spike detection, walk-forward measurement
(peak / first red day / round trip), and aggregate stats. A fake data
provider supplies deterministic price series, so this is zero-network."""

import time
from datetime import date, timedelta

import pytest

from api import create_app
from engine.backtest import BacktestSummary, run_backtest
from engine.db import init_db
from engine.repository import BacktestRepository


class FakeData:
    """bars: {symbol: [{date, close, volume}, ...]} already shaped exactly
    like YFinanceBacktestData.history() would return."""

    def __init__(self, bars):
        self.bars = bars

    def history(self, tickers, start, end):
        out = {}
        for t in tickers:
            if t not in self.bars:
                continue
            out[t] = [b for b in self.bars[t] if start.isoformat() <= b["date"] <= end.isoformat()]
        return out


def _series(start_date: date, closes: list[float], volumes: list[int] | None = None) -> list[dict]:
    """Build a daily bar series (one bar per calendar day, weekends included
    for simplicity — the engine doesn't care, it just walks the list)."""
    volumes = volumes or [200_000] * len(closes)
    return [
        {"date": (start_date + timedelta(days=i)).isoformat(), "close": c, "volume": v}
        for i, (c, v) in enumerate(zip(closes, volumes))
    ]


SPIKE_DAY = date(2026, 3, 1)


def test_spike_detected_and_qualifies():
    """A stock that jumps 22% on the target date, then keeps going flat,
    never reverts within the window."""
    before = [100.0] * 20          # 20 flat days before the spike
    spike = [122.0]                 # +22% on the target day
    after = [122.0] * 30            # stays flat forever after — never reverts
    closes = before + spike + after
    start = SPIKE_DAY - timedelta(days=20)
    bars = _series(start, closes)

    rows = [{"symbol": "X", "name": "X Ltd"}]
    result = run_backtest(rows, FakeData({"X": bars}), SPIKE_DAY, window_days=30)

    assert len(result.movers) == 1
    m = result.movers[0]
    assert m.spike_pct == 22.0
    assert m.direction == "up"
    assert m.reverted is False
    assert m.round_trip_offset_days is None
    assert m.first_red_offset_days is None  # perfectly flat afterward, no red day


def test_below_threshold_is_excluded():
    before = [100.0] * 20
    closes = before + [110.0] + [110.0] * 10  # only +10%, below the 20% threshold
    bars = _series(SPIKE_DAY - timedelta(days=20), closes)
    rows = [{"symbol": "Y", "name": "Y Ltd"}]
    result = run_backtest(rows, FakeData({"Y": bars}), SPIKE_DAY)
    assert result.movers == []


def test_full_round_trip_measured():
    """Spikes to 120 from 100, then falls back to 100 or below exactly 5 days later."""
    before = [100.0] * 20
    spike = [120.0]
    decline = [118.0, 114.0, 108.0, 103.0, 99.0]  # day 5 closes at/under prev_close (100)
    after_flat = [95.0] * 10
    closes = before + spike + decline + after_flat
    bars = _series(SPIKE_DAY - timedelta(days=20), closes)

    rows = [{"symbol": "Z", "name": "Z Ltd"}]
    result = run_backtest(rows, FakeData({"Z": bars}), SPIKE_DAY, window_days=30)
    m = result.movers[0]
    assert m.reverted is True
    assert m.round_trip_offset_days == 5
    assert m.first_red_offset_days == 1  # 118 < 120, the very next day


def test_peak_reached_after_spike_day():
    """The stock keeps climbing for 2 more days before turning — the peak is
    NOT the spike day itself."""
    before = [100.0] * 20
    spike = [120.0]
    still_climbing = [125.0, 130.0]  # peak is here, day offset 2
    turns_down = [110.0] * 10
    closes = before + spike + still_climbing + turns_down
    bars = _series(SPIKE_DAY - timedelta(days=20), closes)

    rows = [{"symbol": "W", "name": "W Ltd"}]
    result = run_backtest(rows, FakeData({"W": bars}), SPIKE_DAY, window_days=30)
    m = result.movers[0]
    assert m.peak_price == 130.0
    assert m.peak_offset_days == 2
    assert m.first_red_offset_days == 3  # first day price drops vs the day before


def test_down_direction_for_bounce_thesis():
    """direction='down' flags drops and measures a bounce back UP as reverted."""
    before = [100.0] * 20
    drop = [78.0]  # -22%
    bounce = [82.0, 90.0, 101.0]  # day 3 back at/above prev_close (100)
    closes = before + drop + bounce + [101.0] * 10
    bars = _series(SPIKE_DAY - timedelta(days=20), closes)

    rows = [{"symbol": "V", "name": "V Ltd"}]
    result = run_backtest(rows, FakeData({"V": bars}), SPIKE_DAY, direction="down", window_days=30)
    m = result.movers[0]
    assert m.direction == "down"
    assert m.spike_pct == -22.0
    assert m.reverted is True
    assert m.round_trip_offset_days == 3


def test_low_volume_excluded():
    before = [100.0] * 20
    closes = before + [125.0] + [125.0] * 10
    volumes = [200_000] * 20 + [1_000] + [200_000] * 10  # today's volume is tiny
    bars = _series(SPIKE_DAY - timedelta(days=20), closes, volumes)
    rows = [{"symbol": "T", "name": "T Ltd"}]
    result = run_backtest(rows, FakeData({"T": bars}), SPIKE_DAY, min_volume=50_000)
    assert result.movers == []


def test_no_bar_on_target_date_is_skipped_not_crashed():
    bars = _series(SPIKE_DAY - timedelta(days=20), [100.0] * 15)  # doesn't reach target date
    rows = [{"symbol": "NODATA", "name": "No Data Ltd"}]
    result = run_backtest(rows, FakeData({"NODATA": bars}), SPIKE_DAY)
    assert result.movers == []


def test_rsi_computed_when_enough_history():
    before = [100.0 + i * 0.5 for i in range(40)]  # steady uptrend -> high RSI
    spike = [before[-1] * 1.25]
    closes = before + spike + [spike[0]] * 10
    bars = _series(SPIKE_DAY - timedelta(days=40), closes)
    rows = [{"symbol": "R", "name": "R Ltd"}]
    result = run_backtest(rows, FakeData({"R": bars}), SPIKE_DAY)
    m = result.movers[0]
    assert m.rsi is not None and m.rsi > 50


# --- summary / aggregate stats ------------------------------------------------
def test_summary_empty():
    s = BacktestSummary(0, 0, 0.0, None, None, None, None)
    assert s.reverted_pct == 0.0
    assert s.avg_days_to_revert is None


def test_summary_aggregates_across_multiple_movers():
    """3 movers: 2 revert (in 4 and 6 days), 1 never does."""
    before = [100.0] * 20

    def make(spike_pct, decline_days_to_revert):
        spike = 100.0 * (1 + spike_pct / 100)
        series = [spike]
        if decline_days_to_revert:
            step = (spike - 100.0) / decline_days_to_revert
            for i in range(1, decline_days_to_revert + 1):
                series.append(spike - step * i)
            series += [series[-1]] * 10
        else:
            series += [spike] * 15
        return before + series

    bars = {
        "A": _series(SPIKE_DAY - timedelta(days=20), make(20, 4)),
        "B": _series(SPIKE_DAY - timedelta(days=20), make(25, 6)),
        "C": _series(SPIKE_DAY - timedelta(days=20), make(30, None)),
    }
    rows = [{"symbol": s, "name": s} for s in bars]
    result = run_backtest(rows, FakeData(bars), SPIKE_DAY, window_days=30)
    assert len(result.movers) == 3

    summary = result.summary()
    assert summary.mover_count == 3
    assert summary.reverted_count == 2
    assert summary.reverted_pct == round(2 / 3 * 100, 1)
    assert summary.avg_days_to_revert == 5.0  # (4 + 6) / 2


# --- repository ----------------------------------------------------------------
@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "backtest.db")
    init_db(p)
    return p


def test_repository_roundtrip(db):
    repo = BacktestRepository(db)
    assert repo.list_runs() == []

    before = [100.0] * 20
    closes = before + [122.0] + [122.0] * 30  # never reverts
    bars = _series(SPIKE_DAY - timedelta(days=20), closes)
    rows = [{"symbol": "X", "name": "X Ltd"}]
    result = run_backtest(rows, FakeData({"X": bars}), SPIKE_DAY, window_days=30)

    run_id = repo.create_run("2026-03-01", "up", 20.0, 30)
    repo.finish_run(run_id, result)

    detail = repo.get_run(run_id)
    assert detail["run"]["status"] == "done"
    assert detail["run"]["mover_count"] == 1
    assert detail["run"]["reverted_count"] == 0
    assert detail["movers"][0]["symbol"] == "X"
    assert detail["movers"][0]["reverted"] is False

    runs = repo.list_runs()
    assert len(runs) == 1
    assert runs[0]["target_date"] == "2026-03-01"


def test_spark_column_migrates_onto_a_preexisting_table(tmp_path):
    """Regression test: a database created before the `spark` column existed
    must gain it on the next init_db(), not silently keep working with a
    schema that's missing a column finish_run() writes to. Simulates that by
    building backtest_movers WITHOUT spark, then re-running init_db()."""
    import sqlite3

    db_path = str(tmp_path / "legacy.db")
    init_db(db_path)  # creates the current (correct) schema

    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE backtest_movers")
    conn.execute(
        """CREATE TABLE backtest_movers (
            run_id INTEGER, symbol TEXT, name TEXT, direction TEXT, spike_pct REAL,
            price_at_spike REAL, prev_close REAL, volume INTEGER, avg_volume INTEGER,
            vol_ratio REAL, rsi REAL, peak_price REAL, peak_offset_days INTEGER,
            first_red_offset_days INTEGER, round_trip_offset_days INTEGER,
            reverted INTEGER, PRIMARY KEY (run_id, symbol)
        )"""
    )  # the "old" shape, missing `spark`
    conn.commit()
    conn.close()

    init_db(db_path)  # must add the missing column, not error

    repo = BacktestRepository(db_path)
    before = [100.0] * 20
    bars = _series(SPIKE_DAY - timedelta(days=20), before + [122.0] + [122.0] * 10)
    rows = [{"symbol": "X", "name": "X Ltd"}]
    result = run_backtest(rows, FakeData({"X": bars}), SPIKE_DAY, window_days=10)

    run_id = repo.create_run("2026-03-01", "up", 20.0, 10)
    repo.finish_run(run_id, result)  # would raise OperationalError pre-migration

    detail = repo.get_run(run_id)
    assert detail["movers"][0]["spark"] == result.movers[0].spark


def test_repository_fail_run(db):
    repo = BacktestRepository(db)
    run_id = repo.create_run("2026-03-01", "up", 20.0, 30)
    repo.fail_run(run_id, "network error")
    detail = repo.get_run(run_id)
    assert detail["run"]["status"] == "error"
    assert detail["run"]["error"] == "network error"


# --- API + async service ------------------------------------------------------
class FakeBacktestData:
    def __init__(self, bars):
        self.bars = bars

    def history(self, tickers, start, end):
        out = {}
        for t in tickers:
            if t not in self.bars:
                continue
            out[t] = [b for b in self.bars[t] if start.isoformat() <= b["date"] <= end.isoformat()]
        return out


@pytest.fixture
def client(tmp_path):
    app = create_app(data_root=str(tmp_path), start_worker=False, price_source_mode="manual")
    app.config.update(TESTING=True)
    before = [100.0] * 20
    never_reverts = before + [122.0] + [122.0] * 30
    reverts_fast = before + [125.0] + [110.0, 99.0] + [99.0] * 20
    app.config["BACKTEST_DATA"] = FakeBacktestData(
        bars={
            "HOLDS": _series(SPIKE_DAY - timedelta(days=20), never_reverts),
            "FALLS": _series(SPIKE_DAY - timedelta(days=20), reverts_fast),
        }
    )
    c = app.test_client()
    r = c.post("/auth/register", json={"username": "rishi", "password": "supersecret1"})
    c.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {r.get_json()['token']}"
    import os
    with open(os.path.join(str(tmp_path), "nse_universe.csv"), "w", encoding="utf-8") as f:
        f.write("symbol,name,series\nHOLDS,Holds Ltd,EQ\nFALLS,Falls Ltd,EQ\n")
    return c


def test_backtest_empty_before_any_run(client):
    body = client.get("/backtest/runs").get_json()
    assert body["runs"] == []


def test_backtest_run_flow(client):
    r = client.post("/backtest/run", json={"target_date": SPIKE_DAY.isoformat(), "window_days": 30})
    assert r.status_code == 202

    for _ in range(50):
        st = client.get("/backtest/status").get_json()
        if st["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    assert st["status"] == "done", st
    run_id = st["run_id"]

    detail = client.get(f"/backtest/runs/{run_id}").get_json()
    assert detail["run"]["mover_count"] == 2
    assert detail["run"]["reverted_count"] == 1
    symbols = {m["symbol"]: m for m in detail["movers"]}
    assert symbols["HOLDS"]["reverted"] is False
    assert symbols["FALLS"]["reverted"] is True

    runs = client.get("/backtest/runs").get_json()["runs"]
    assert len(runs) == 1
    assert runs[0]["target_date"] == SPIKE_DAY.isoformat()


def test_backtest_rejects_future_date(client):
    r = client.post("/backtest/run", json={"target_date": "2099-01-01"})
    assert r.status_code == 400


def test_backtest_rejects_bad_direction(client):
    r = client.post("/backtest/run", json={"target_date": SPIKE_DAY.isoformat(), "direction": "sideways"})
    assert r.status_code == 400


def test_backtest_unknown_run_404(client):
    assert client.get("/backtest/runs/999").status_code == 404


def test_backtest_disabled_in_manual_mode(tmp_path):
    app = create_app(data_root=str(tmp_path), start_worker=False, price_source_mode="manual")
    c = app.test_client()
    r = c.post("/auth/register", json={"username": "bob", "password": "supersecret1"})
    c.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {r.get_json()['token']}"
    resp = c.post("/backtest/run", json={"target_date": SPIKE_DAY.isoformat()})
    assert resp.status_code == 503


def test_backtest_requires_auth(tmp_path):
    app = create_app(data_root=str(tmp_path), start_worker=False, price_source_mode="manual")
    assert app.test_client().get("/backtest/runs").status_code == 401
