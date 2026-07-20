"""Price sources — the seam between the trading engine and the outside world.

The engine NEVER fetches prices itself; it only ever receives a
{symbol: price} dict. That's why adding live data here changes no trading logic.

How the pieces fit
------------------
    live source (NSE / yfinance)  ->  PriceStore (data/prices.json)  ->  engine
         fetched by a job              persistent last-known cache      valuation

Live sources *feed* the persistent store; everything downstream (P&L, alerts,
leaderboard, snapshots) keeps reading the store exactly as it did before. So a
network hiccup degrades to "last known price" instead of breaking the app, and
a manually-set price still works as an override.

Sources implement PriceSource.get_prices(symbols) -> {symbol: price}. Sources
that can also serve history implement get_history(symbol, period).

A note on NSE
-------------
`nsepython` scrapes NSE's public site. There is no official free API, and NSE
actively blocks traffic that doesn't look like a browser — datacenter/cloud IPs
commonly get HTTP 403 regardless of headers. It tends to work from an ordinary
Indian residential connection and fail from a server. That's exactly why
ChainedPriceSource exists: try NSE, fall back to Yahoo, fall back to last-known.
"""

from __future__ import annotations

import time
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Protocol

# NSE trades 09:15–15:30 IST, Monday to Friday.
IST = timezone(timedelta(hours=5, minutes=30))
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)


def market_is_open(now: datetime | None = None) -> bool:
    """True during NSE trading hours. Used to tell the UI whether a price is
    live or a stale last-close, and to avoid pointless polling overnight.
    (Does not know about trading holidays — it'll say 'open' on Diwali.)"""
    now = (now or datetime.now(timezone.utc)).astimezone(IST)
    if now.weekday() >= 5:  # Saturday/Sunday
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


class PriceSource(Protocol):
    """Any object with this method can feed prices to the engine."""

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        ...


def normalize(symbol: str) -> str:
    """Our canonical form is the bare NSE symbol, e.g. 'RELIANCE'."""
    s = symbol.strip().upper()
    for suffix in (".NS", ".BO"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s


# --- manual (Phase 1 stub, still useful as an override) ---------------------
class ManualPriceSource:
    """Prices supplied by hand. Keeps the whole app runnable with no network."""

    def __init__(self, prices: dict[str, float] | None = None):
        self._prices: dict[str, float] = {normalize(k): float(v) for k, v in (prices or {}).items()}

    def set_price(self, symbol: str, price: float) -> None:
        self._prices[normalize(symbol)] = float(price)

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        return {s: self._prices[normalize(s)] for s in symbols if normalize(s) in self._prices}


# --- Yahoo Finance (works from anywhere; delayed but reliable) --------------
class YFinancePriceSource:
    """Yahoo Finance via the `yfinance` package.

    Reliable from a server, and the only one of our sources that gives usable
    HISTORY for charts. Data is typically delayed ~15 minutes for NSE — fine for
    a paper-trading learning tool, and stated plainly in the UI.

    Batches every symbol into ONE download call. That matters: Yahoo rate-limits
    aggressively (HTTP 429), and one request for twenty symbols is far safer
    than twenty requests.
    """

    name = "yfinance"

    def __init__(self, exchange: str = "NS"):
        self.suffix = f".{exchange}"  # .NS = NSE, .BO = BSE

    def _ticker(self, symbol: str) -> str:
        return normalize(symbol) + self.suffix

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        symbols = [normalize(s) for s in symbols if s and s.strip()]
        if not symbols:
            return {}
        import yfinance as yf  # imported lazily: it's slow and optional

        tickers = [self._ticker(s) for s in symbols]
        out: dict[str, float] = {}
        try:
            data = yf.download(
                tickers, period="1d", progress=False, auto_adjust=True, threads=False
            )
            if data is None or data.empty:
                return {}
            closes = data["Close"]
            for sym, tick in zip(symbols, tickers):
                try:
                    # A single ticker yields a Series; multiple yield a DataFrame.
                    series = closes[tick] if hasattr(closes, "columns") else closes
                    val = series.dropna()
                    if len(val):
                        out[sym] = round(float(val.iloc[-1]), 2)
                except (KeyError, IndexError, TypeError):
                    continue
        except Exception:
            # Network/rate-limit failure must never propagate: callers fall back
            # to the last-known price instead.
            return out
        return out

    def get_prev_closes(self, symbols: list[str]) -> dict[str, float]:
        """Previous session's close for each symbol, in ONE batched request.

        This is what day-change % ("+1.2% today") is computed against. Batched
        for the same reason get_prices is: a watchlist of 15 symbols polled
        every 15s would otherwise be 60 requests/minute — a fast route to a
        rate-limit ban.
        """
        symbols = [normalize(s) for s in symbols if s and s.strip()]
        if not symbols:
            return {}
        import yfinance as yf

        tickers = [self._ticker(s) for s in symbols]
        out: dict[str, float] = {}
        try:
            data = yf.download(tickers, period="5d", progress=False, auto_adjust=True, threads=False)
            if data is None or data.empty:
                return {}
            closes = data["Close"]
            for sym, tick in zip(symbols, tickers):
                try:
                    series = (closes[tick] if hasattr(closes, "columns") else closes).dropna()
                    if len(series) >= 2:
                        out[sym] = round(float(series.iloc[-2]), 2)  # second-to-last = prev close
                except (KeyError, IndexError, TypeError):
                    continue
        except Exception:
            return out
        return out

    def get_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> list[dict]:
        """OHLC history for charts: [{date, open, high, low, close, volume}]."""
        import yfinance as yf

        try:
            hist = yf.Ticker(self._ticker(symbol)).history(period=period, interval=interval)
        except Exception:
            return []
        if hist is None or hist.empty:
            return []
        rows = []
        for idx, row in hist.iterrows():
            try:
                rows.append(
                    {
                        "date": idx.strftime("%Y-%m-%d %H:%M" if interval.endswith(("m", "h")) else "%Y-%m-%d"),
                        "open": round(float(row["Open"]), 2),
                        "high": round(float(row["High"]), 2),
                        "low": round(float(row["Low"]), 2),
                        "close": round(float(row["Close"]), 2),
                        "volume": int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
                    }
                )
            except (KeyError, ValueError, TypeError):
                continue
        return rows


# --- NSE via nsepython (real-time, but often blocked from servers) ----------
class NsePythonPriceSource:
    """Live NSE prices by scraping NSE's public quote endpoint.

    Real-time when it works. Fetches one symbol per request (there's no batch
    endpoint), so we deliberately sleep briefly between calls — hammering NSE is
    the fastest way to get your IP blocked.
    """

    name = "nsepython"

    def __init__(self, delay: float = 0.4):
        self.delay = delay

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        try:
            from nsepython import nse_eq
        except ImportError:
            return {}

        out: dict[str, float] = {}
        for i, raw in enumerate(symbols):
            sym = normalize(raw)
            try:
                data = nse_eq(sym)
                # A blocked/failed scrape returns {} rather than raising.
                price = (data or {}).get("priceInfo", {}).get("lastPrice")
                if price:
                    out[sym] = round(float(price), 2)
            except Exception:
                continue
            if i < len(symbols) - 1:
                time.sleep(self.delay)  # be polite; avoid a rate-limit ban
        return out

    def healthcheck(self) -> tuple[bool, str]:
        """Is NSE reachable from THIS machine? Surfaced via /prices/sources so
        you can see at a glance whether live NSE works where you're running."""
        try:
            from nsepython import nse_eq
        except ImportError:
            return False, "nsepython is not installed"
        try:
            data = nse_eq("RELIANCE")
        except Exception as e:
            return False, f"{type(e).__name__}: {str(e)[:120]}"
        if not data:
            return False, "NSE returned an empty response (usually HTTP 403 — the IP is blocked)"
        if "priceInfo" not in data:
            return False, "unexpected response shape from NSE"
        return True, "ok"


# --- chaining + caching ------------------------------------------------------
class ChainedPriceSource:
    """Try each source in order; the first to return a symbol wins.

    This is what makes live pricing robust: if NSE blocks us we silently fall
    through to Yahoo, and anything still missing keeps its last-known price from
    the persistent store. The app never breaks because a scraper broke.
    """

    name = "chain"

    def __init__(self, sources: list):
        self.sources = sources

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        remaining = [normalize(s) for s in symbols]
        out: dict[str, float] = {}
        for src in self.sources:
            if not remaining:
                break
            try:
                got = src.get_prices(remaining)
            except Exception:
                continue
            out.update(got)
            remaining = [s for s in remaining if s not in out]
        return out

    def get_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> list[dict]:
        for src in self.sources:
            fn = getattr(src, "get_history", None)
            if not fn:
                continue
            rows = fn(symbol, period, interval)
            if rows:
                return rows
        return []

    def get_prev_closes(self, symbols: list[str]) -> dict[str, float]:
        for src in self.sources:
            fn = getattr(src, "get_prev_closes", None)
            if fn:
                try:
                    got = fn(symbols)
                except Exception:
                    continue
                if got:
                    return got
        return {}


class CachedPriceSource:
    """TTL cache in front of any source.

    Two reasons this matters: the alert job polls every 15s and would otherwise
    hammer the upstream API into a rate-limit ban, and repeated page loads
    shouldn't each trigger a network round trip.
    """

    def __init__(self, source, ttl_seconds: int = 60):
        self.source = source
        self.ttl = ttl_seconds
        self._cache: dict[str, tuple[float, float]] = {}  # symbol -> (price, fetched_at)
        self._prev_cache: dict[str, tuple[float, float]] = {}  # symbol -> (prev_close, fetched_at)

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        now = time.monotonic()
        out: dict[str, float] = {}
        stale: list[str] = []
        for raw in symbols:
            s = normalize(raw)
            hit = self._cache.get(s)
            if hit and now - hit[1] < self.ttl:
                out[s] = hit[0]
            else:
                stale.append(s)
        if stale:
            fresh = self.source.get_prices(stale)
            for s, p in fresh.items():
                self._cache[s] = (p, now)
                out[s] = p
        return out

    def get_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> list[dict]:
        fn = getattr(self.source, "get_history", None)
        return fn(symbol, period, interval) if fn else []

    def get_prev_closes(self, symbols: list[str]) -> dict[str, float]:
        """Cached much longer than live prices (10 min) — a previous close only
        changes once per trading day."""
        fn = getattr(self.source, "get_prev_closes", None)
        if not fn:
            return {}
        now = time.monotonic()
        out: dict[str, float] = {}
        stale: list[str] = []
        for raw in symbols:
            s = normalize(raw)
            hit = self._prev_cache.get(s)
            if hit and now - hit[1] < 600:
                out[s] = hit[0]
            else:
                stale.append(s)
        if stale:
            for s, p in fn(stale).items():
                self._prev_cache[s] = (p, now)
                out[s] = p
        return out

    def invalidate(self) -> None:
        self._cache.clear()
        self._prev_cache.clear()


# --- factory -----------------------------------------------------------------
def build_source(mode: str = "auto", cache_ttl: int = 60):
    """Construct the configured price source.

    mode:
      "auto"      NSE first (real-time), Yahoo as fallback  <- default
      "nse"       NSE only
      "yfinance"  Yahoo only (works from servers; ~15min delayed)
      "manual"    no network at all
    """
    mode = (mode or "auto").lower()
    if mode == "manual":
        return ManualPriceSource()
    if mode == "nse":
        base = NsePythonPriceSource()
    elif mode == "yfinance":
        base = YFinancePriceSource()
    else:
        base = ChainedPriceSource([NsePythonPriceSource(), YFinancePriceSource()])
    return CachedPriceSource(base, ttl_seconds=cache_ttl)
