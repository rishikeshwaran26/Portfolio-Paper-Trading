"""Backtest: did today's screener idea actually work in the past?

The question this answers
--------------------------
The screener finds stocks that moved 20%+ in a day, on the theory that such an
extreme move tends to partially reverse (short-term reversal) — the basis for
a mean-reversion short. That's a belief until you check it. This module checks
it, using real historical prices instead of a fresh live scan:

  1. Pick a past calendar date.
  2. Find every stock that spiked (or dropped) by the threshold that day —
     using yesterday's close vs that day's close, exactly like the screener.
  3. For each one, walk FORWARD day by day for a fixed window and record three
     things: how much further it ran before turning (the peak), how many days
     until the first red (down) day, and how many days until it fully round-
     tripped back to its pre-spike price (or never, within the window).
  4. Aggregate across every mover to get real numbers: reversion rate, average
     days to reverse, and whether the spike-day volume/RSI predicted it.

Why this can be done ENTIRELY with data we already have access to: unlike a
live scan (which needs today's price, unknowable in advance), a past date's
full price history — before AND after it — already exists on Yahoo Finance.
No waiting required; we can test any date in the past right now.

The "why" signal is intentionally narrower than the live screener's: news
headlines are not available for arbitrary past dates (Yahoo's news endpoint
only returns *current* headlines), so this module only uses volume and RSI at
the spike — both computable from historical prices for any date.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Optional, Protocol

from .screener import rsi as _rsi

DEFAULT_THRESHOLD_PCT = 20.0
DEFAULT_WINDOW_DAYS = 30  # trading days to watch after the spike
DEFAULT_MIN_VOLUME = 50_000
VOLUME_BASELINE_DAYS = 30  # trading days used to compute "average volume"
RSI_LOOKBACK_DAYS = 14


# --- data provider seam ------------------------------------------------------
class BacktestData(Protocol):
    """Everything the backtest needs from the outside world. Swapped for a
    fake in tests so the walk-forward logic is verified with zero network
    calls."""

    def history(self, tickers: list[str], start: date, end: date) -> dict[str, list[dict]]:
        """Daily bars per symbol between start and end (inclusive), oldest
        first: [{date: "YYYY-MM-DD", close, volume}]."""
        ...


# --- result shapes -------------------------------------------------------------
@dataclass
class BacktestMover:
    symbol: str
    name: str
    direction: str  # "up" or "down"
    spike_pct: float
    price_at_spike: float
    prev_close: float
    volume: int
    avg_volume: int
    vol_ratio: float
    rsi: Optional[float]

    # what happened AFTER the spike, within the tracking window
    peak_price: float
    peak_offset_days: int          # 0 = the spike day itself was the peak
    first_red_offset_days: Optional[int] = None   # None = never within window
    round_trip_offset_days: Optional[int] = None  # None = never fully reverted
    reverted: bool = False         # convenience: round_trip_offset_days is not None
    spark: list[float] = field(default_factory=list)  # prev_close + spike day + forward closes

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "direction": self.direction,
            "spike_pct": self.spike_pct,
            "price_at_spike": self.price_at_spike,
            "prev_close": self.prev_close,
            "volume": self.volume,
            "avg_volume": self.avg_volume,
            "vol_ratio": self.vol_ratio,
            "rsi": self.rsi,
            "peak_price": self.peak_price,
            "peak_offset_days": self.peak_offset_days,
            "first_red_offset_days": self.first_red_offset_days,
            "round_trip_offset_days": self.round_trip_offset_days,
            "reverted": self.reverted,
            "spark": self.spark,
        }


@dataclass
class BacktestSummary:
    """Aggregate stats across every mover found on the target date — the
    actual answer to 'does this idea work'."""

    mover_count: int
    reverted_count: int
    reverted_pct: float
    avg_days_to_revert: Optional[float]     # among those that DID revert
    avg_days_to_first_red: Optional[float]  # among those that had one
    high_rsi_reverted_pct: Optional[float]  # movers with RSI >= 70
    low_rsi_reverted_pct: Optional[float]   # movers with RSI < 70 (or unknown)

    def to_dict(self) -> dict:
        return {
            "mover_count": self.mover_count,
            "reverted_count": self.reverted_count,
            "reverted_pct": self.reverted_pct,
            "avg_days_to_revert": self.avg_days_to_revert,
            "avg_days_to_first_red": self.avg_days_to_first_red,
            "high_rsi_reverted_pct": self.high_rsi_reverted_pct,
            "low_rsi_reverted_pct": self.low_rsi_reverted_pct,
        }


@dataclass
class BacktestResult:
    target_date: str
    direction: str
    threshold_pct: float
    window_days: int
    universe_count: int
    movers: list[BacktestMover] = field(default_factory=list)

    def summary(self) -> BacktestSummary:
        return _summarize(self.movers)


# --- the core simulation -----------------------------------------------------
def _summarize(movers: list[BacktestMover]) -> BacktestSummary:
    n = len(movers)
    if n == 0:
        return BacktestSummary(0, 0, 0.0, None, None, None, None)

    reverted = [m for m in movers if m.reverted]
    had_red = [m for m in movers if m.first_red_offset_days is not None]
    high_rsi = [m for m in movers if m.rsi is not None and m.rsi >= 70]
    low_rsi = [m for m in movers if m.rsi is not None and m.rsi < 70]

    def pct_reverted(group: list[BacktestMover]) -> Optional[float]:
        return round(sum(1 for m in group if m.reverted) / len(group) * 100, 1) if group else None

    return BacktestSummary(
        mover_count=n,
        reverted_count=len(reverted),
        reverted_pct=round(len(reverted) / n * 100, 1),
        avg_days_to_revert=(
            round(sum(m.round_trip_offset_days for m in reverted) / len(reverted), 1)
            if reverted else None
        ),
        avg_days_to_first_red=(
            round(sum(m.first_red_offset_days for m in had_red) / len(had_red), 1)
            if had_red else None
        ),
        high_rsi_reverted_pct=pct_reverted(high_rsi),
        low_rsi_reverted_pct=pct_reverted(low_rsi),
    )


def _trading_days_needed(window_days: int) -> timedelta:
    """Calendar-day span that comfortably covers `window_days` TRADING days,
    padding for weekends/holidays (roughly 7/5 calendar days per trading day,
    plus a safety margin)."""
    return timedelta(days=int(window_days * 1.6) + 10)


def run_backtest(
    rows: list[dict],
    data: BacktestData,
    target_date: date,
    direction: str = "up",
    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
    window_days: int = DEFAULT_WINDOW_DAYS,
    min_volume: int = DEFAULT_MIN_VOLUME,
    chunk_size: int = 100,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> BacktestResult:
    """Replay `target_date` across `rows` ([{symbol, name}]) and measure what
    happened next. `direction` is "up" (spikes, for the short thesis) or
    "down" (drops, for a bounce thesis) — matches the screener's convention.
    """
    lookback_start = target_date - timedelta(days=max(VOLUME_BASELINE_DAYS, RSI_LOOKBACK_DAYS) * 2 + 20)
    lookahead_end = target_date + _trading_days_needed(window_days)

    tickers = [r["symbol"] for r in rows]
    name_of = {r["symbol"]: r.get("name", r["symbol"]) for r in rows}
    movers: list[BacktestMover] = []
    total = len(tickers)

    for start in range(0, total, chunk_size):
        chunk = tickers[start : start + chunk_size]
        try:
            history = data.history(chunk, lookback_start, lookahead_end)
        except Exception:
            history = {}
        for sym in chunk:
            bars = history.get(sym) or []
            mover = _evaluate_symbol(
                sym, name_of.get(sym, sym), bars, target_date, direction,
                threshold_pct, window_days, min_volume,
            )
            if mover:
                movers.append(mover)
        if progress:
            done = min(start + chunk_size, total)
            progress(done, total, f"Replayed {done}/{total} stocks for {target_date.isoformat()}")

    return BacktestResult(
        target_date=target_date.isoformat(),
        direction=direction,
        threshold_pct=threshold_pct,
        window_days=window_days,
        universe_count=total,
        movers=movers,
    )


def _evaluate_symbol(
    symbol: str,
    name: str,
    bars: list[dict],
    target_date: date,
    direction: str,
    threshold_pct: float,
    window_days: int,
    min_volume: int,
) -> Optional[BacktestMover]:
    """Find `target_date` in this symbol's bar series and, if it qualifies as
    a spike, walk forward to measure what happened. Returns None if the symbol
    has no bar on that date or doesn't qualify."""
    idx = next((i for i, b in enumerate(bars) if b["date"] == target_date.isoformat()), None)
    if idx is None or idx == 0:
        return None  # no data for that day, or no prior day to compare against

    today = bars[idx]
    prev = bars[idx - 1]
    prev_close = prev["close"]
    price_at_spike = today["close"]
    if not prev_close or prev_close <= 0:
        return None

    pct = round((price_at_spike - prev_close) / prev_close * 100, 2)
    if direction == "up" and pct < threshold_pct:
        return None
    if direction == "down" and pct > -threshold_pct:
        return None
    volume = int(today.get("volume") or 0)
    if volume < min_volume:
        return None

    # volume baseline: the trading days strictly before the spike
    baseline_start = max(0, idx - VOLUME_BASELINE_DAYS)
    hist_vols = [int(b.get("volume") or 0) for b in bars[baseline_start:idx] if b.get("volume")]
    avg_volume = int(sum(hist_vols) / len(hist_vols)) if hist_vols else 0
    vol_ratio = round(volume / avg_volume, 2) if avg_volume > 0 else 0.0

    rsi_start = max(0, idx - RSI_LOOKBACK_DAYS * 3)
    closes_for_rsi = [b["close"] for b in bars[rsi_start : idx + 1] if b.get("close") is not None]
    spike_rsi = _rsi(closes_for_rsi)

    # --- walk forward -------------------------------------------------------
    forward = bars[idx + 1 : idx + 1 + window_days]
    peak_price = price_at_spike
    peak_offset = 0
    first_red_offset: Optional[int] = None
    round_trip_offset: Optional[int] = None
    prev_bar_close = price_at_spike
    spark = [prev_close, price_at_spike]  # the path a sparkline draws: before -> spike -> forward

    for offset, bar in enumerate(forward, start=1):
        close = bar.get("close")
        if close is None:
            continue
        spark.append(close)
        if close > peak_price:
            peak_price = close
            peak_offset = offset
        if first_red_offset is None and close < prev_bar_close:
            first_red_offset = offset
        if round_trip_offset is None:
            reverted_now = (
                close <= prev_close if direction == "up" else close >= prev_close
            )
            if reverted_now:
                round_trip_offset = offset
        prev_bar_close = close

    return BacktestMover(
        symbol=symbol,
        name=name,
        direction="up" if pct > 0 else "down",
        spike_pct=pct,
        price_at_spike=round(price_at_spike, 2),
        prev_close=round(prev_close, 2),
        volume=volume,
        avg_volume=avg_volume,
        vol_ratio=vol_ratio,
        rsi=spike_rsi,
        peak_price=round(peak_price, 2),
        peak_offset_days=peak_offset,
        first_red_offset_days=first_red_offset,
        round_trip_offset_days=round_trip_offset,
        reverted=round_trip_offset is not None,
        spark=[round(v, 2) for v in spark],
    )


# --- the real (yfinance) data provider --------------------------------------
class YFinanceBacktestData:
    """BacktestData backed by yfinance's historical daily bars — the same
    library the live screener and price charts use, just queried over an
    arbitrary past date range instead of "recent"."""

    def __init__(self, exchange: str = "NS"):
        self.suffix = f".{exchange}"

    def _tick(self, symbol: str) -> str:
        return symbol.strip().upper() + self.suffix

    def history(self, tickers: list[str], start: date, end: date) -> dict[str, list[dict]]:
        if not tickers:
            return {}
        import yfinance as yf

        yts = [self._tick(t) for t in tickers]
        out: dict[str, list[dict]] = {}
        try:
            data = yf.download(
                yts, start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(),
                progress=False, auto_adjust=True, threads=False, group_by="ticker",
            )
        except Exception:
            return {}
        if data is None or data.empty:
            return {}
        for sym, yt in zip(tickers, yts):
            try:
                sub = data[yt] if yt in getattr(data, "columns", []) else data
                closes = sub["Close"]
                vols = sub["Volume"]
                bars = []
                for idx in closes.index:
                    c = closes.get(idx)
                    if c is None or c != c:  # NaN
                        continue
                    v = vols.get(idx)
                    bars.append(
                        {
                            "date": idx.strftime("%Y-%m-%d"),
                            "close": float(c),
                            "volume": int(v) if v == v else 0,
                        }
                    )
                if bars:
                    out[sym] = bars
            except (KeyError, TypeError, IndexError):
                continue
        return out
