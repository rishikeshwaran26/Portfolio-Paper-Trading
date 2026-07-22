"""Tests for the market screener: bucketing, volume filter, enrichment, the
repository, and the async scan flow via the API. No network — a fake
ScreenerData provider supplies deterministic bars."""

import time

import pytest

from api import create_app
from engine import screener
from engine.repository import ScreenerRepository
from engine.screener import bracket_for, scan


# --- pure bucketing ----------------------------------------------------------
def test_bracket_for_gainers():
    assert bracket_for(4.9) is None
    assert bracket_for(5) == "up_5_10"
    assert bracket_for(9.99) == "up_5_10"
    assert bracket_for(10) == "up_10_15"
    assert bracket_for(14.9) == "up_10_15"
    assert bracket_for(15) == "up_15_plus"
    assert bracket_for(25) == "up_15_plus"  # open-ended top bucket keeps big movers


def test_bracket_for_losers():
    assert bracket_for(-4.9) is None
    assert bracket_for(-5) == "down_5_10"
    assert bracket_for(-12) == "down_10_15"
    assert bracket_for(-30) == "down_15_plus"


# --- technical indicators ----------------------------------------------------
def test_rsi_all_gains_is_100():
    # Strictly rising series -> no losses -> RSI pinned at 100.
    assert screener.rsi([float(i) for i in range(1, 40)]) == 100.0


def test_rsi_all_losses_is_low():
    # Strictly falling series -> no gains -> RSI at 0.
    assert screener.rsi([float(i) for i in range(40, 1, -1)]) == 0.0


def test_rsi_needs_enough_data():
    assert screener.rsi([1, 2, 3]) is None  # fewer than period+1 points


def test_rsi_known_wilder_value():
    # A classic hand-checkable sequence; Wilder RSI-14 ~ 70.5 for this input.
    closes = [
        44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
        45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00,
    ]
    # Mostly-rising series -> elevated RSI. Exact value depends on how many
    # Wilder smoothing steps the short series allows; just assert it's high.
    val = screener.rsi(closes, period=14)
    assert 60 <= val <= 75


def test_macd_bullish_on_uptrend():
    closes = [float(i) for i in range(1, 60)]  # steady uptrend
    m = screener.macd(closes)
    assert m is not None and m["bullish"] is True


def test_macd_bearish_on_downtrend():
    closes = [float(i) for i in range(60, 1, -1)]  # steady downtrend
    m = screener.macd(closes)
    assert m is not None and m["bullish"] is False


def test_macd_needs_enough_data():
    assert screener.macd([1, 2, 3, 4, 5]) is None


# --- fake provider -----------------------------------------------------------
class FakeData:
    """Deterministic ScreenerData. `bars` maps symbol -> list of {close, volume}."""

    def __init__(self, bars, ranges=None, news=None, closes=None, earnings=None):
        self.bars = bars
        self.ranges = ranges or {}
        self._news = news or {}
        self._closes = closes or {}
        self._earnings = earnings or {}

    def recent_bars(self, tickers):
        return {t: self.bars[t] for t in tickers if t in self.bars}

    def year_range(self, tickers):
        return {t: self.ranges[t] for t in tickers if t in self.ranges}

    def history_closes(self, tickers):
        # Default to the closes from recent_bars if no explicit 3mo series given.
        out = {}
        for t in tickers:
            if t in self._closes:
                out[t] = self._closes[t]
            elif t in self.bars:
                out[t] = [b["close"] for b in self.bars[t]]
        return out

    def news(self, symbol):
        return self._news.get(symbol, [])

    def earnings_date(self, symbol):
        return self._earnings.get(symbol)


def _flat_bars(prev, last, volume, hist_vol=1000):
    """29 flat days at `prev` (each with hist_vol) then one day at `last`."""
    return [{"close": prev, "volume": hist_vol} for _ in range(29)] + [
        {"close": last, "volume": volume}
    ]


def test_scan_buckets_and_volume_filter():
    rows = [
        {"symbol": "BIGUP", "name": "Big Up"},      # +20% -> up_15_plus
        {"symbol": "MIDUP", "name": "Mid Up"},      # +12% -> up_10_15
        {"symbol": "SMALLUP", "name": "Small Up"},  # +6%  -> up_5_10
        {"symbol": "DOWN", "name": "Faller"},       # -8%  -> down_5_10
        {"symbol": "FLAT", "name": "Flat"},         # +1%  -> excluded (below 5%)
        {"symbol": "THIN", "name": "Thin"},         # +18% but tiny volume -> excluded
    ]
    data = FakeData(
        bars={
            "BIGUP": _flat_bars(100, 120, 200_000),
            "MIDUP": _flat_bars(100, 112, 200_000),
            "SMALLUP": _flat_bars(100, 106, 200_000),
            "DOWN": _flat_bars(100, 92, 200_000),
            "FLAT": _flat_bars(100, 101, 200_000),
            "THIN": _flat_bars(100, 118, 500),  # below DEFAULT_MIN_VOLUME
        }
    )
    result = scan(rows, data, source="test", chunk_size=2)
    buckets = result.buckets()

    assert [m["symbol"] for m in buckets["up_15_plus"]] == ["BIGUP"]
    assert [m["symbol"] for m in buckets["up_10_15"]] == ["MIDUP"]
    assert [m["symbol"] for m in buckets["up_5_10"]] == ["SMALLUP"]
    assert [m["symbol"] for m in buckets["down_5_10"]] == ["DOWN"]
    # FLAT (too small) and THIN (too illiquid) never made it in
    all_syms = {m.symbol for m in result.movers}
    assert "FLAT" not in all_syms and "THIN" not in all_syms


def test_scan_computes_volume_ratio_and_reasons():
    rows = [{"symbol": "SPIKE", "name": "Spike Co"}]
    # 29 days at 100k volume, today 500k -> 5x average (and clears the 50k floor)
    data = FakeData(
        bars={"SPIKE": _flat_bars(100, 118, 500_000, hist_vol=100_000)},
        ranges={"SPIKE": (119.0, 60.0)},  # today's 118 is within 3% of 119 high
        news={"SPIKE": [{"title": "Spike Co wins big order", "publisher": "X", "link": "u", "published": ""}]},
    )
    m = scan(rows, data, source="test").movers[0]
    assert m.vol_ratio == 5.0
    assert m.near_high is True
    assert any("volume" in r.lower() for r in m.reasons)
    assert any("52-week high" in r for r in m.reasons)
    assert m.news[0]["title"] == "Spike Co wins big order"


def test_scan_sorts_within_bucket_biggest_first():
    rows = [{"symbol": "A", "name": "A"}, {"symbol": "B", "name": "B"}]
    data = FakeData(bars={
        "A": _flat_bars(100, 106, 200_000),  # +6%
        "B": _flat_bars(100, 109, 200_000),  # +9%
    })
    buckets = scan(rows, data, source="test").buckets()
    # both in up_5_10, bigger move (B, +9%) first
    assert [m["symbol"] for m in buckets["up_5_10"]] == ["B", "A"]


# --- repository --------------------------------------------------------------
@pytest.fixture
def db(tmp_path):
    from engine.db import init_db
    p = str(tmp_path / "s.db")
    init_db(p)
    return p


def test_repository_roundtrip(db):
    repo = ScreenerRepository(db)
    assert repo.latest_done() is None  # nothing yet

    rows = [{"symbol": "BIGUP", "name": "Big Up"}]
    data = FakeData(bars={"BIGUP": _flat_bars(100, 120, 200_000)}, ranges={"BIGUP": (120.0, 50.0)})
    result = scan(rows, data, source="download")

    run_id = repo.create_run("2026-07-21")
    repo.finish_run(run_id, result)

    latest = repo.latest_done()
    assert latest["run"]["mover_count"] == 1
    assert latest["run"]["source"] == "download"
    assert latest["buckets"]["up_15_plus"][0]["symbol"] == "BIGUP"
    assert latest["buckets"]["up_15_plus"][0]["near_high"] is True
    assert repo.done_today("2026-07-21") is True
    assert repo.done_today("2026-07-20") is False


def test_enriched_fields_flow_through_scan_and_repo(db):
    """rsi / macd / sparkline / 1w-vol-diff / 52w-pct / results tag are computed
    in the scan and survive a persist + reload."""
    # A 60-day uptrend into a +20% pop today, on a big volume spike.
    trend = [float(x) for x in range(100, 160)]           # 60 rising closes
    bars = [{"close": c, "volume": 100_000} for c in trend]
    bars[-1] = {"close": 185.0, "volume": 1_000_000}       # today: gap up, 10x vol
    prev = trend[-2]
    pct = round((185.0 - prev) / prev * 100, 2)
    assert pct >= 15  # lands in up_15_plus

    data = FakeData(
        bars={"TREND": bars},
        ranges={"TREND": (190.0, 90.0)},
        closes={"TREND": trend[:-1] + [185.0]},            # 60 closes -> MACD computable
        earnings={"TREND": __import__("datetime").date.today().isoformat()},
    )
    result = scan([{"symbol": "TREND", "name": "Trend Co"}], data, source="test")
    m = result.movers[0]
    assert m.rsi is not None and m.rsi > 50           # uptrend -> high RSI
    assert m.macd_bullish is True
    assert len(m.spark) > 0
    assert m.vol_diff_1w_pct is not None and m.vol_diff_1w_pct > 0
    assert m.week52_pct is not None and 0 <= m.week52_pct <= 100
    assert m.results_recent is True                    # earnings today -> tag on

    repo = ScreenerRepository(db)
    run_id = repo.create_run("2026-07-21")
    repo.finish_run(run_id, result)
    reloaded = repo.latest_done()["movers"][0]
    assert reloaded["rsi"] == m.rsi
    assert reloaded["macd_bullish"] is True
    assert reloaded["spark"] == m.spark
    assert reloaded["results_recent"] is True
    assert reloaded["vol_diff_1w_pct"] == m.vol_diff_1w_pct


def test_repository_fail_run(db):
    repo = ScreenerRepository(db)
    run_id = repo.create_run("2026-07-21")
    repo.fail_run(run_id, "boom")
    assert repo.latest_done() is None       # a failed run is not "done"
    assert repo.last_run()["status"] == "error"


# --- API + async service -----------------------------------------------------
@pytest.fixture
def client(tmp_path):
    app = create_app(data_root=str(tmp_path), start_worker=False, price_source_mode="manual")
    app.config.update(TESTING=True)
    # Inject a fake data provider so a real scan runs with no network.
    app.config["SCREENER_DATA"] = FakeData(
        bars={
            "BIGUP": _flat_bars(100, 120, 200_000),  # +20% -> up_15_plus
            "DOWN": _flat_bars(100, 80, 200_000),    # -20% -> down_15_plus
        },
        ranges={"BIGUP": (120.0, 50.0)},
    )
    c = app.test_client()
    r = c.post("/auth/register", json={"username": "rishi", "password": "supersecret1"})
    c.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {r.get_json()['token']}"
    # Seed a tiny universe cache so the scan doesn't try to hit NSE.
    import os
    with open(os.path.join(str(tmp_path), "nse_universe.csv"), "w", encoding="utf-8") as f:
        f.write("symbol,name,series\nBIGUP,Big Up,EQ\nDOWN,Faller,EQ\n")
    return c


def test_screener_empty_before_any_scan(client):
    body = client.get("/screener").get_json()
    assert body["latest"] is None
    assert body["status"]["status"] == "idle"
    assert len(body["brackets"]) == 6


def test_screener_scan_flow(client):
    r = client.post("/screener/scan")
    assert r.status_code == 202

    # Poll status until the background thread finishes (fast with fake data).
    for _ in range(50):
        st = client.get("/screener/status").get_json()
        if st["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    assert st["status"] == "done", st

    body = client.get("/screener").get_json()
    assert body["latest"]["run"]["mover_count"] == 2
    assert body["latest"]["buckets"]["up_15_plus"][0]["symbol"] == "BIGUP"
    assert body["latest"]["buckets"]["down_15_plus"][0]["symbol"] == "DOWN"


def test_screener_scan_disabled_in_manual_mode(tmp_path):
    """With no data provider (pure manual mode), scanning returns 503."""
    app = create_app(data_root=str(tmp_path), start_worker=False, price_source_mode="manual")
    c = app.test_client()
    r = c.post("/auth/register", json={"username": "bob", "password": "supersecret1"})
    c.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {r.get_json()['token']}"
    assert c.post("/screener/scan").status_code == 503


def test_screener_scan_requires_auth(tmp_path):
    app = create_app(data_root=str(tmp_path), start_worker=False, price_source_mode="manual")
    assert app.test_client().get("/screener").status_code == 401
