"""The daily movers screener — scan the whole NSE for big one-day moves.

The trading idea this serves
----------------------------
A stock that jumps or drops 5–20% in a single session is often stretched, and a
mean-reversion trader wants to see the whole list of them at once: fade the
over-extended gainers (short), watch the beaten-down losers for a bounce. This
module produces exactly that list, bucketed by how big the move was.

How it stays fast over ~1,900 stocks
------------------------------------
Naively fetching a full year of data for 1,900 tickers to answer "who moved
today?" would be enormous. So the scan is TWO PHASES, which is what real
screeners do:

  Phase 1 (broad, all ~1,900):  one month of daily bars, downloaded in chunks.
      Enough to compute today's % change AND today's volume vs its 30-day
      average. This alone narrows the field to a few dozen genuine movers.

  Phase 2 (deep, only the movers):  a full year of bars (for 52-week high/low
      context) plus news headlines — fetched ONLY for the handful that
      qualified. Cheap, because the set is now small.

Testability
-----------
All network access lives behind a `ScreenerData` provider. The real one uses
yfinance; tests inject a fake, so the bucketing / reason logic is verified with
zero network calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

# --- brackets ----------------------------------------------------------------
# (key, human label, low %, high %, direction). The top bucket is open-ended
# (high = infinity) on purpose: NSE circuit limits are often 20%, and a
# short-seller most wants to see the stocks that ran the hardest — clamping at
# 20% would hide exactly those. So "+15%+" means "15% or more".
BRACKETS: list[tuple[str, str, float, float, str]] = [
    ("up_5_10", "+5–10%", 5, 10, "up"),
    ("up_10_15", "+10–15%", 10, 15, "up"),
    ("up_15_plus", "+15%+", 15, float("inf"), "up"),
    ("down_5_10", "−5–10%", 5, 10, "down"),
    ("down_10_15", "−10–15%", 10, 15, "down"),
    ("down_15_plus", "−15%+", 15, float("inf"), "down"),
]

# A move on tiny volume is noise, not signal — a 15% pop on 500 shares means
# nothing. Below this many shares traded today, we drop the stock.
DEFAULT_MIN_VOLUME = 50_000

# "Near" its 52-week extreme: within this fraction of the high/low.
NEAR_EDGE = 0.03  # 3%

# How many recent closes the sparkline shows.
SPARK_POINTS = 30


def bracket_for(pct: float) -> Optional[str]:
    """Which bracket key a % change falls in, or None if |pct| < 5%."""
    a = abs(pct)
    direction = "up" if pct > 0 else "down"
    for key, _label, lo, hi, d in BRACKETS:
        if d == direction and lo <= a < hi:
            return key
    return None


# --- technical indicators (pure functions, unit-tested offline) --------------
def rsi(closes: list[float], period: int = 14) -> Optional[float]:
    """Wilder's Relative Strength Index over `closes` (oldest first).

    RSI measures momentum on a 0–100 scale: >70 is conventionally "overbought"
    (stretched after a run-up — a short-seller's cue), <30 "oversold" (beaten
    down — a bounce candidate). Returns None if there isn't enough history.
    """
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    # Wilder smoothing across the remaining deltas.
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)


def _ema(values: list[float], period: int) -> list[float]:
    k = 2 / (period + 1)
    e = values[0]
    out = [e]
    for v in values[1:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Optional[dict]:
    """MACD (12/26/9). Returns {macd, signal, hist, bullish} or None.

    `bullish` (MACD line above its signal line) is the simple read most screeners
    filter on: it flags trend turning up. `hist` is the gap between the two —
    positive and rising means momentum building. Needs ~slow+signal bars.
    """
    if len(closes) < slow + signal:
        return None
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = _ema(macd_line, signal)
    hist = macd_line[-1] - signal_line[-1]
    return {
        "macd": round(macd_line[-1], 3),
        "signal": round(signal_line[-1], 3),
        "hist": round(hist, 3),
        "bullish": macd_line[-1] > signal_line[-1],
    }


# --- data provider seam ------------------------------------------------------
class ScreenerData(Protocol):
    """Everything the scan needs from the outside world. Swapped for a fake in
    tests so the logic below is verified offline."""

    def recent_bars(self, tickers: list[str]) -> dict[str, list[dict]]:
        """~1 month of daily bars per symbol: [{close, volume}], oldest first."""
        ...

    def year_range(self, tickers: list[str]) -> dict[str, tuple[float, float]]:
        """52-week (high, low) per symbol."""
        ...

    def history_closes(self, tickers: list[str]) -> dict[str, list[float]]:
        """~3 months of daily closes per symbol (enough to compute RSI/MACD and
        draw a sparkline). Only fetched for the handful of movers, so the extra
        history is cheap."""
        ...

    def news(self, symbol: str) -> list[dict]:
        """Recent headlines: [{title, publisher, link, published}]."""
        ...

    def earnings_date(self, symbol: str) -> Optional[str]:
        """Most recent earnings/results date as YYYY-MM-DD, or None. Used for the
        'Results recently' tag — a fresh result often explains a big move."""
        ...


# --- results shapes ----------------------------------------------------------
@dataclass
class Mover:
    symbol: str
    name: str
    price: float
    prev_close: float
    pct_change: float
    volume: int
    avg_volume: int
    vol_ratio: float
    bracket: str
    direction: str
    vol_diff_1w_pct: Optional[float] = None  # today's volume vs 1-week avg, as %
    week52_high: Optional[float] = None
    week52_low: Optional[float] = None
    week52_pct: Optional[float] = None       # position in the 52w range, 0–100
    near_high: bool = False
    near_low: bool = False
    rsi: Optional[float] = None
    macd_bullish: Optional[bool] = None
    macd_hist: Optional[float] = None
    spark: list[float] = field(default_factory=list)  # recent closes for a sparkline
    results_recent: bool = False
    results_date: Optional[str] = None
    news: list[dict] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "price": self.price,
            "prev_close": self.prev_close,
            "pct_change": self.pct_change,
            "volume": self.volume,
            "avg_volume": self.avg_volume,
            "vol_ratio": self.vol_ratio,
            "vol_diff_1w_pct": self.vol_diff_1w_pct,
            "bracket": self.bracket,
            "direction": self.direction,
            "week52_high": self.week52_high,
            "week52_low": self.week52_low,
            "week52_pct": self.week52_pct,
            "near_high": self.near_high,
            "near_low": self.near_low,
            "rsi": self.rsi,
            "macd_bullish": self.macd_bullish,
            "macd_hist": self.macd_hist,
            "spark": self.spark,
            "results_recent": self.results_recent,
            "results_date": self.results_date,
            "news": self.news,
            "reasons": self.reasons,
        }


@dataclass
class ScanResult:
    movers: list[Mover]
    universe_count: int
    scanned_count: int
    source: str  # how the universe was obtained: download|cache|bundled

    def buckets(self) -> dict[str, list[dict]]:
        """Movers grouped by bracket key, each sorted by |% change| descending
        so the biggest move sits on top of every list."""
        out: dict[str, list[dict]] = {key: [] for key, *_ in BRACKETS}
        for m in self.movers:
            out[m.bracket].append(m.to_dict())
        for key in out:
            out[key].sort(key=lambda d: abs(d["pct_change"]), reverse=True)
        return out


# --- the scan ----------------------------------------------------------------
def _phase1_movers(
    rows: list[dict],
    data: ScreenerData,
    min_volume: int,
    chunk_size: int,
    progress: Optional[Callable[[int, int, str], None]],
) -> list[Mover]:
    """Broad pass: compute today's move + volume for every symbol, keep the ones
    that cleared a bracket and the volume floor."""
    name_of = {r["symbol"]: r.get("name", r["symbol"]) for r in rows}
    tickers = [r["symbol"] for r in rows]
    total = len(tickers)
    movers: list[Mover] = []

    for start in range(0, total, chunk_size):
        chunk = tickers[start : start + chunk_size]
        try:
            bars = data.recent_bars(chunk)
        except Exception:
            bars = {}
        for sym in chunk:
            series = bars.get(sym) or []
            if len(series) < 2:
                continue
            price = series[-1].get("close")
            prev = series[-2].get("close")
            volume = int(series[-1].get("volume") or 0)
            if not price or not prev or prev <= 0:
                continue
            pct = round((price - prev) / prev * 100, 2)
            bracket = bracket_for(pct)
            if bracket is None:
                continue
            if volume < min_volume:
                continue
            # 30-day average volume EXCLUDING today (today is the anomaly we're
            # measuring against the baseline).
            hist_vols = [int(b.get("volume") or 0) for b in series[:-1] if b.get("volume")]
            avg_vol = int(sum(hist_vols) / len(hist_vols)) if hist_vols else 0
            vol_ratio = round(volume / avg_vol, 2) if avg_vol > 0 else 0.0
            # 1-week average (last 5 sessions before today) expressed as a
            # percentage DIFFERENCE, matching the "1W avg vol diff" column:
            # +200% means today traded 3× the past week's average.
            week_vols = hist_vols[-5:]
            avg_vol_1w = sum(week_vols) / len(week_vols) if week_vols else 0
            vol_diff_1w = round((volume / avg_vol_1w - 1) * 100, 2) if avg_vol_1w > 0 else None
            movers.append(
                Mover(
                    symbol=sym,
                    name=name_of.get(sym, sym),
                    price=round(float(price), 2),
                    prev_close=round(float(prev), 2),
                    pct_change=pct,
                    volume=volume,
                    avg_volume=avg_vol,
                    vol_ratio=vol_ratio,
                    vol_diff_1w_pct=vol_diff_1w,
                    bracket=bracket,
                    direction="up" if pct > 0 else "down",
                )
            )
        if progress:
            progress(min(start + chunk_size, total), total, f"Scanned {min(start + chunk_size, total)}/{total} stocks")

    return movers


def _enrich(
    movers: list[Mover],
    data: ScreenerData,
    progress: Optional[Callable[[int, int, str], None]],
) -> None:
    """Deep pass over the (small) mover set: 52-week context, RSI/MACD, a
    sparkline, news, earnings recency, and the human 'why' reasons. Mutates each
    Mover in place."""
    if not movers:
        return
    tickers = [m.symbol for m in movers]
    try:
        ranges = data.year_range(tickers)
    except Exception:
        ranges = {}
    try:
        closes_by_sym = data.history_closes(tickers)
    except Exception:
        closes_by_sym = {}

    total = len(movers)
    for i, m in enumerate(movers, 1):
        hi, lo = ranges.get(m.symbol, (None, None))
        if hi:
            m.week52_high = round(float(hi), 2)
            m.near_high = m.price >= hi * (1 - NEAR_EDGE)
        if lo:
            m.week52_low = round(float(lo), 2)
            m.near_low = m.price <= lo * (1 + NEAR_EDGE)
        if hi and lo and hi > lo:
            m.week52_pct = round((m.price - lo) / (hi - lo) * 100, 1)

        closes = closes_by_sym.get(m.symbol) or []
        if closes:
            m.spark = [round(float(c), 2) for c in closes[-SPARK_POINTS:]]
            m.rsi = rsi(closes)
            mac = macd(closes)
            if mac:
                m.macd_bullish = mac["bullish"]
                m.macd_hist = mac["hist"]

        try:
            m.news = data.news(m.symbol)[:3]
        except Exception:
            m.news = []

        try:
            ed = data.earnings_date(m.symbol)
        except Exception:
            ed = None
        if ed:
            m.results_date = ed
            m.results_recent = _is_recent(ed)

        m.reasons = _reasons_for(m)
        if progress:
            progress(i, total, f"Analysing movers {i}/{total}")


def _is_recent(date_str: str, days: int = 4) -> bool:
    """True if an ISO date is within the last `days` days — for the 'Results
    recently' tag. A result out in the last few sessions is a plausible cause of
    a big move.

    Compared as plain calendar dates, not timestamps: an earnings date is a
    day, not an instant, so there is no "timezone" for it to be in. Mixing it
    with a UTC-aware `now` would make the comparison flip depending on the time
    of day and the server's local offset — e.g. IST is UTC+5:30, so for the
    ~5.5 hours after UTC midnight, `date.today()` in India is already
    "tomorrow" relative to UTC, which would make a same-day result look 1 day
    in the future and fail the `>= 0` check below.
    """
    from datetime import date

    try:
        d = date.fromisoformat(date_str[:10])
    except (ValueError, TypeError):
        return False
    return 0 <= (date.today() - d).days <= days


def _reasons_for(m: Mover) -> list[str]:
    """Turn the computed signals into plain-English reasons. These are
    *context*, not claims of causation — volume and range are facts; the news
    headlines (attached separately) are where an actual cause usually shows up."""
    reasons: list[str] = []
    if m.vol_ratio >= 3:
        reasons.append(f"Heavy volume — {m.vol_ratio}× the 30-day average")
    elif m.vol_ratio >= 1.5:
        reasons.append(f"Above-average volume — {m.vol_ratio}× normal")
    elif m.avg_volume and m.vol_ratio and m.vol_ratio < 0.8:
        reasons.append(f"On light volume — only {m.vol_ratio}× normal (move may not stick)")

    if m.near_high:
        reasons.append("Near its 52-week high")
    elif m.near_low:
        reasons.append("Near its 52-week low")

    if m.rsi is not None and m.rsi >= 70:
        reasons.append(f"Overbought — RSI {m.rsi} (stretched, mean-reversion fade setup)")
    elif m.rsi is not None and m.rsi <= 30:
        reasons.append(f"Oversold — RSI {m.rsi} (bounce candidate)")

    if m.macd_bullish is True:
        reasons.append("MACD bullish (momentum turning up)")
    elif m.macd_bullish is False:
        reasons.append("MACD bearish (momentum turning down)")

    if m.results_recent:
        reasons.append(f"Results out recently ({m.results_date}) — likely the catalyst")

    if not m.results_recent:
        if m.direction == "up" and abs(m.pct_change) >= 15:
            reasons.append("Possible upper-circuit / sharp spike — stretched for a mean-reversion fade")
        elif m.direction == "down" and abs(m.pct_change) >= 15:
            reasons.append("Sharp drop — watch for an oversold bounce")
    return reasons


def scan(
    rows: list[dict],
    data: ScreenerData,
    source: str = "unknown",
    min_volume: int = DEFAULT_MIN_VOLUME,
    chunk_size: int = 100,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> ScanResult:
    """Run the full two-phase scan over `rows` ([{symbol, name}]).

    `progress(done, total, message)` is called throughout so a caller (the
    background thread) can surface a live progress bar — the scan takes ~a minute
    over the full exchange and we never want the UI to look frozen.
    """
    movers = _phase1_movers(rows, data, min_volume, chunk_size, progress)
    if progress:
        progress(len(rows), len(rows), f"Found {len(movers)} movers — analysing")
    _enrich(movers, data, progress)
    return ScanResult(
        movers=movers,
        universe_count=len(rows),
        scanned_count=len(rows),
        source=source,
    )


# --- the real (yfinance) data provider --------------------------------------
class YFinanceScreenerData:
    """ScreenerData backed by yfinance. Batches downloads to stay under Yahoo's
    rate limits (see engine/prices.py for the same discipline)."""

    def __init__(self, exchange: str = "NS"):
        self.suffix = f".{exchange}"

    def _tick(self, symbol: str) -> str:
        return symbol.strip().upper() + self.suffix

    def recent_bars(self, tickers: list[str]) -> dict[str, list[dict]]:
        if not tickers:
            return {}
        import yfinance as yf

        yts = [self._tick(t) for t in tickers]
        out: dict[str, list[dict]] = {}
        try:
            data = yf.download(
                yts, period="1mo", progress=False, auto_adjust=True, threads=False, group_by="ticker"
            )
        except Exception:
            return {}
        if data is None or data.empty:
            return {}
        for sym, yt in zip(tickers, yts):
            try:
                # With group_by="ticker" and multiple tickers, columns are a
                # MultiIndex keyed by ticker; a single ticker is a flat frame.
                sub = data[yt] if yt in getattr(data, "columns", []) else data
                closes = sub["Close"].dropna()
                vols = sub["Volume"]
                bars = []
                for idx in closes.index:
                    c = closes.get(idx)
                    v = vols.get(idx)
                    if c is None or c != c:  # NaN check
                        continue
                    bars.append({"close": float(c), "volume": int(v) if v == v else 0})
                if bars:
                    out[sym] = bars
            except (KeyError, TypeError, IndexError):
                continue
        return out

    def year_range(self, tickers: list[str]) -> dict[str, tuple[float, float]]:
        if not tickers:
            return {}
        import yfinance as yf

        yts = [self._tick(t) for t in tickers]
        out: dict[str, tuple[float, float]] = {}
        try:
            data = yf.download(
                yts, period="1y", progress=False, auto_adjust=True, threads=False, group_by="ticker"
            )
        except Exception:
            return {}
        if data is None or data.empty:
            return {}
        for sym, yt in zip(tickers, yts):
            try:
                sub = data[yt] if yt in getattr(data, "columns", []) else data
                highs = sub["High"].dropna()
                lows = sub["Low"].dropna()
                if len(highs) and len(lows):
                    out[sym] = (float(highs.max()), float(lows.min()))
            except (KeyError, TypeError, IndexError):
                continue
        return out

    def history_closes(self, tickers: list[str]) -> dict[str, list[float]]:
        if not tickers:
            return {}
        import yfinance as yf

        yts = [self._tick(t) for t in tickers]
        out: dict[str, list[float]] = {}
        try:
            data = yf.download(
                yts, period="3mo", progress=False, auto_adjust=True, threads=False, group_by="ticker"
            )
        except Exception:
            return {}
        if data is None or data.empty:
            return {}
        for sym, yt in zip(tickers, yts):
            try:
                sub = data[yt] if yt in getattr(data, "columns", []) else data
                closes = sub["Close"].dropna()
                if len(closes):
                    out[sym] = [float(c) for c in closes]
            except (KeyError, TypeError, IndexError):
                continue
        return out

    def earnings_date(self, symbol: str) -> Optional[str]:
        """Best-effort most-recent past earnings date. yfinance's earnings data
        is flaky and version-dependent, so every failure mode degrades to None
        (no 'Results recently' tag) rather than breaking the scan."""
        import yfinance as yf
        from datetime import datetime, timezone

        try:
            df = yf.Ticker(self._tick(symbol)).get_earnings_dates(limit=8)
        except Exception:
            return None
        if df is None or getattr(df, "empty", True):
            return None
        now = datetime.now(timezone.utc)
        past = []
        for idx in df.index:
            try:
                dt = idx.to_pydatetime()
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt <= now:
                    past.append(dt)
            except (AttributeError, ValueError):
                continue
        if not past:
            return None
        return max(past).strftime("%Y-%m-%d")

    def news(self, symbol: str) -> list[dict]:
        import yfinance as yf

        try:
            raw = yf.Ticker(self._tick(symbol)).news or []
        except Exception:
            return []
        items = []
        for n in raw:
            # yfinance news shape has shifted over versions; support both the
            # flat old shape and the newer {"content": {...}} nesting.
            content = n.get("content", n)
            title = content.get("title") or n.get("title")
            if not title:
                continue
            provider = content.get("provider") or {}
            publisher = (
                provider.get("displayName")
                if isinstance(provider, dict)
                else None
            ) or n.get("publisher") or ""
            url = ""
            cu = content.get("canonicalUrl") or content.get("clickThroughUrl")
            if isinstance(cu, dict):
                url = cu.get("url", "")
            url = url or n.get("link", "")
            items.append(
                {
                    "title": title,
                    "publisher": publisher,
                    "link": url,
                    "published": content.get("pubDate") or n.get("providerPublishTime", ""),
                }
            )
        return items
