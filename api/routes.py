"""The REST endpoints.

Three design ideas run through this file:

REST resource conventions
-------------------------
URLs name *resources* (nouns), HTTP methods are the *verbs*:
  - a collection:  /strategies         (GET = list, POST = create one)
  - an item:       /strategies/<name>  (GET = read that one)
  - a sub-action:  /strategies/<name>/buy   (POST = append a transaction)
We don't put verbs in paths like /createStrategy — the method already says what
we're doing, so GET (safe, cacheable) stays distinct from POST (creates data).

Two layers of validation
-------------------------
  1. SYNTACTIC (api/validation.py): is the body JSON? right types? -> 400 before
     the engine is ever touched. Never trust a client.
  2. SEMANTIC (the engine): enough cash? enough shares? -> typed engine errors
     that the handlers map to 409/400.
The engine stays the single source of truth for trading rules.

Every route is user-scoped
--------------------------
@require_auth resolves the bearer token to a user and puts g.data on the
request. No route ever opens a hardcoded file path, which is what makes
multi-user a data change rather than a rewrite.
"""

from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request

from engine import symbols
from engine.alerts import ABOVE, BELOW
from engine.prices import NsePythonPriceSource, market_is_open
from engine.journal import (
    performance_by_confidence,
    performance_by_side,
    performance_by_tag,
    winners_vs_losers,
)
from engine.manager import DEFAULT_STARTING_CASH
from engine.portfolio import Portfolio

from .auth import require_auth
from .errors import ApiError
from .jobs import capture_snapshot_for_user, refresh_live_prices
from .validation import json_body, opt_str, opt_tags, req_int, req_num, req_str

bp = Blueprint("api", __name__)


# --- per-request wiring (all derived from g.data, never hardcoded) ----------
# g.data is the authenticated user's UserData, built by @require_auth. Routes
# never construct a repository from a raw path or open a connection themselves.
def _manager():
    return g.data.portfolios()


def _price_store():
    return g.data.prices()


def _alert_store():
    return g.data.alerts()


def _snapshot_store():
    return g.data.snapshots()


def _prices_for(manager, store) -> dict[str, float]:
    """Current price for every symbol held anywhere. Missing prices are simply
    absent — the engine values those holdings at cost, so nothing crashes."""
    symbols = set()
    for p in manager.portfolios.values():
        symbols.update(p.holdings.keys())
    return store.get_prices(list(symbols))


def _get_portfolio(manager, name: str) -> Portfolio:
    p = manager.portfolios.get(name)
    if p is None:
        raise ApiError(404, "NotFound", f"no strategy named '{name}'")
    return p


# --- response shaping --------------------------------------------------------
def _summary(p: Portfolio, prices: dict[str, float]) -> dict:
    return {
        "name": p.name,
        "cash": p.cash,
        "starting_cash": p.starting_cash,
        "holdings_value": p.holdings_value(prices),
        "total_value": p.total_value(prices),
        "return_pct": p.total_return_pct(prices),
        "realized_pnl": p.realized_pnl(),
        "unrealized_pnl": p.unrealized_pnl(prices),
        "num_holdings": len(p.holdings),
    }


def _detail(p: Portfolio, prices: dict[str, float]) -> dict:
    holdings = []
    for symbol, h in p.holdings.items():
        ltp = prices.get(symbol, h.avg_price)
        holdings.append(
            {
                "symbol": symbol,
                "side": "short" if h.is_short else "long",
                # quantity/avg_price stay signed/positive as the engine stores
                # them; the frontend shows abs(quantity) with a side badge.
                "quantity": h.quantity,
                "avg_price": h.avg_price,
                "last_price": ltp,
                "priced": symbol in prices,
                "market_value": h.market_value(ltp),
                "unrealized_pnl": h.unrealized_pnl(ltp),
            }
        )
    d = _summary(p, prices)
    d["holdings"] = holdings
    d["transactions"] = [t.to_dict() for t in p.transactions]
    return d


# --- strategy collection -----------------------------------------------------
@bp.post("/strategies")
@require_auth
def create_strategy():
    body = json_body()
    name = req_str(body, "name")
    starting_cash = float(body.get("starting_cash", DEFAULT_STARTING_CASH))

    manager = _manager()
    if name in manager.portfolios:
        raise ApiError(409, "StrategyExists", f"strategy '{name}' already exists")

    p = manager.create_strategy(name, starting_cash)
    manager.save()
    prices = _prices_for(manager, _price_store())
    resp = jsonify(_summary(p, prices))
    resp.status_code = 201
    resp.headers["Location"] = f"/strategies/{name}"
    return resp


@bp.get("/strategies")
@require_auth
def list_strategies():
    manager = _manager()
    prices = _prices_for(manager, _price_store())
    return jsonify({"strategies": [_summary(p, prices) for p in manager.portfolios.values()]})


@bp.get("/strategies/<name>")
@require_auth
def get_strategy(name: str):
    manager = _manager()
    p = _get_portfolio(manager, name)
    prices = _prices_for(manager, _price_store())
    return jsonify(_detail(p, prices))


# --- trading -----------------------------------------------------------------
@bp.post("/strategies/<name>/buy")
@require_auth
def buy(name: str):
    # reason + confidence are required because the trade journal is the core
    # feature of this project — a buy without a thesis defeats the point.
    body = json_body()
    symbol = req_str(body, "symbol")
    quantity = req_int(body, "quantity")
    price = req_num(body, "price")
    reason = req_str(body, "reason")
    confidence = req_int(body, "confidence")
    tags = opt_tags(body)

    manager = _manager()
    p = _get_portfolio(manager, name)
    txn = p.buy(symbol, quantity, price, reason, confidence, tags)
    manager.save()
    _price_store().set_price(symbol, price)

    resp = jsonify({"transaction": txn.to_dict(), "cash": p.cash})
    resp.status_code = 201
    return resp


@bp.post("/strategies/<name>/sell")
@require_auth
def sell(name: str):
    body = json_body()
    symbol = req_str(body, "symbol")
    quantity = req_int(body, "quantity")
    price = req_num(body, "price")
    reason = req_str(body, "reason")

    manager = _manager()
    p = _get_portfolio(manager, name)
    txn = p.sell(symbol, quantity, price, reason)
    manager.save()
    _price_store().set_price(symbol, price)

    resp = jsonify({"transaction": txn.to_dict(), "cash": p.cash, "realized_pnl": txn.realized_pnl})
    resp.status_code = 201
    return resp


@bp.post("/strategies/<name>/short")
@require_auth
def short(name: str):
    # Same required fields as buy() — a short is still an opening trade with a
    # thesis, just betting on a fall instead of a rise.
    body = json_body()
    symbol = req_str(body, "symbol")
    quantity = req_int(body, "quantity")
    price = req_num(body, "price")
    reason = req_str(body, "reason")
    confidence = req_int(body, "confidence")
    tags = opt_tags(body)

    manager = _manager()
    p = _get_portfolio(manager, name)
    txn = p.short(symbol, quantity, price, reason, confidence, tags)
    manager.save()
    _price_store().set_price(symbol, price)

    resp = jsonify({"transaction": txn.to_dict(), "cash": p.cash})
    resp.status_code = 201
    return resp


@bp.post("/strategies/<name>/cover")
@require_auth
def cover(name: str):
    body = json_body()
    symbol = req_str(body, "symbol")
    quantity = req_int(body, "quantity")
    price = req_num(body, "price")
    reason = req_str(body, "reason")

    manager = _manager()
    p = _get_portfolio(manager, name)
    txn = p.cover(symbol, quantity, price, reason)
    manager.save()
    _price_store().set_price(symbol, price)

    resp = jsonify({"transaction": txn.to_dict(), "cash": p.cash, "realized_pnl": txn.realized_pnl})
    resp.status_code = 201
    return resp


@bp.get("/strategies/<name>/transactions")
@require_auth
def transactions(name: str):
    manager = _manager()
    p = _get_portfolio(manager, name)
    txns = p.transactions
    t_type = request.args.get("type")
    symbol = request.args.get("symbol")
    if t_type:
        txns = [t for t in txns if t.type == t_type.upper()]
    if symbol:
        txns = [t for t in txns if t.symbol == symbol.strip().upper()]
    return jsonify({"transactions": [t.to_dict() for t in txns]})


@bp.post("/strategies/<name>/transactions/<txn_id>/review")
@require_auth
def review(name: str, txn_id: str):
    body = json_body()
    notes = req_str(body, "notes")
    manager = _manager()
    p = _get_portfolio(manager, name)
    if not any(t.id == txn_id for t in p.transactions):
        raise ApiError(404, "NotFound", f"no transaction '{txn_id}' in '{name}'")
    txn = p.review(txn_id, notes)
    manager.save()
    return jsonify({"transaction": txn.to_dict()})


# --- journal analytics (the insight layer) ----------------------------------
@bp.get("/strategies/<name>/analytics")
@require_auth
def analytics(name: str):
    """Everything needed to answer 'what kind of trader am I?':
    win rate + avg P&L by tag, by confidence, winners vs losers, and long vs
    short performance side-by-side (a short strategy can be judged on its own
    terms rather than blended into your long-side numbers)."""
    manager = _manager()
    p = _get_portfolio(manager, name)
    return jsonify(
        {
            "by_confidence": [s.to_dict() for s in performance_by_confidence(p.transactions)],
            "by_tag": [s.to_dict() for s in performance_by_tag(p.transactions)],
            "winners_vs_losers": winners_vs_losers(p.transactions),
            "by_side": performance_by_side(p.transactions),
        }
    )


# --- leaderboard -------------------------------------------------------------
@bp.get("/leaderboard")
@require_auth
def leaderboard():
    manager = _manager()
    prices = _prices_for(manager, _price_store())
    return jsonify({"leaderboard": manager.leaderboard(prices)})


# --- snapshots + comparison --------------------------------------------------
@bp.get("/snapshots")
@require_auth
def snapshots():
    """Chart-ready history. ?strategies=A,B narrows the overlay.

    Returns `series` already reshaped into one row per date with one key per
    strategy — exactly what recharts wants, so the frontend does no reshaping.
    """
    wanted = request.args.get("strategies")
    names = [s.strip() for s in wanted.split(",") if s.strip()] if wanted else None
    store = _snapshot_store()
    return jsonify(
        {
            "series": store.series(names),
            "strategies": store.strategy_names(),
            "count": len(store.snapshots),
        }
    )


@bp.post("/snapshots/capture")
@require_auth
def capture_snapshot():
    """Force a snapshot now instead of waiting for the daily job — useful for
    testing the comparison chart without waiting a day."""
    taken = capture_snapshot_for_user(g.data.root, g.user_id)
    return jsonify({"captured": [s.to_dict() for s in taken]}), 201


# --- price alerts ------------------------------------------------------------
@bp.get("/alerts")
@require_auth
def list_alerts():
    store = _alert_store()
    return jsonify(
        {
            "alerts": [a.to_dict() for a in store.alerts],
            # what the in-app banner shows: fired but not yet acknowledged
            "triggered": [a.to_dict() for a in store.triggered()],
        }
    )


@bp.post("/alerts")
@require_auth
def create_alert():
    body = json_body()
    symbol = req_str(body, "symbol")
    target_price = req_num(body, "target_price")
    direction = opt_str(body, "direction", ABOVE).lower()
    note = opt_str(body, "note")
    if direction not in (ABOVE, BELOW):
        raise ApiError(400, "BadRequest", f"direction must be '{ABOVE}' or '{BELOW}'")
    if target_price <= 0:
        raise ApiError(400, "BadRequest", "target_price must be positive")
    alert = _alert_store().add(symbol, target_price, direction, note)
    return jsonify({"alert": alert.to_dict()}), 201


@bp.post("/alerts/<alert_id>/dismiss")
@require_auth
def dismiss_alert(alert_id: str):
    alert = _alert_store().dismiss(alert_id)
    if not alert:
        raise ApiError(404, "NotFound", f"no alert '{alert_id}'")
    return jsonify({"alert": alert.to_dict()})


@bp.delete("/alerts/<alert_id>")
@require_auth
def delete_alert(alert_id: str):
    if not _alert_store().remove(alert_id):
        raise ApiError(404, "NotFound", f"no alert '{alert_id}'")
    return jsonify({"deleted": alert_id})


# --- symbol search -----------------------------------------------------------
@bp.get("/symbols/search")
@require_auth
def search_symbols():
    """Autocomplete: ?q=rel -> RELIANCE first. Backed by a bundled list of the
    ~150 most-traded NSE names (engine/symbols.py) — instant and offline, but
    not the whole exchange; unknown symbols can still be typed manually."""
    q = request.args.get("q", "")
    return jsonify({"results": symbols.search(q)})


# --- watchlist ---------------------------------------------------------------
def _quotes_for(syms: list[str]) -> list[dict]:
    """Groww-style quote rows: last price + change vs previous close.

    Current prices come from the shared price table (the background worker keeps
    it fresh); previous closes come from the live source in ONE batched call,
    cached 10 minutes. The route itself never fans out per-symbol.
    """
    if not syms:
        return []
    stored = _price_store().get_prices(syms)
    source = current_app.config.get("PRICE_SOURCE")
    prev = {}
    if source and hasattr(source, "get_prev_closes"):
        try:
            prev = source.get_prev_closes(syms)
        except Exception:
            prev = {}
    rows = []
    for s in syms:
        price = stored.get(s)
        pc = prev.get(s)
        change = round(price - pc, 2) if price is not None and pc else None
        rows.append(
            {
                "symbol": s,
                "name": symbols.name_of(s),
                "price": price,
                "prev_close": pc,
                "change": change,
                "change_pct": round(change / pc * 100, 2) if change is not None and pc else None,
            }
        )
    return rows


@bp.get("/watchlists")
@require_auth
def list_watchlists():
    """Every one of the user's named watchlists, each with live quotes for its
    own symbols. No auto-created default — a brand-new user just sees an empty
    list and the UI prompts them to create the first one."""
    lists = g.data.watchlist().list_all()
    for wl in lists:
        wl["stocks"] = _quotes_for(wl.pop("symbols"))
    return jsonify({"watchlists": lists, "market_open": market_is_open()})


@bp.post("/watchlists")
@require_auth
def create_watchlist():
    body = json_body()
    wl = g.data.watchlist().create(req_str(body, "name"))
    wl["stocks"] = wl.pop("symbols")
    return jsonify({"watchlist": wl}), 201


@bp.delete("/watchlists/<int:watchlist_id>")
@require_auth
def delete_watchlist(watchlist_id: int):
    if not g.data.watchlist().delete(watchlist_id):
        raise ApiError(404, "NotFound", f"no watchlist with id {watchlist_id}")
    return jsonify({"deleted": watchlist_id})


@bp.post("/watchlists/<int:watchlist_id>/symbols")
@require_auth
def add_watchlist_symbol(watchlist_id: int):
    body = json_body()
    sym = g.data.watchlist().add_symbol(watchlist_id, req_str(body, "symbol"))
    if sym is None:
        raise ApiError(404, "NotFound", f"no watchlist with id {watchlist_id}")
    # Fetch a price immediately so the new row isn't blank until the next
    # worker tick.
    source = current_app.config.get("PRICE_SOURCE")
    if source:
        try:
            got = source.get_prices([sym])
            if got:
                _price_store().set_many(got)
        except Exception:
            pass
    return jsonify({"symbol": sym}), 201


@bp.delete("/watchlists/<int:watchlist_id>/symbols/<symbol>")
@require_auth
def remove_watchlist_symbol(watchlist_id: int, symbol: str):
    if not g.data.watchlist().remove_symbol(watchlist_id, symbol):
        raise ApiError(404, "NotFound", f"'{symbol.upper()}' is not in watchlist {watchlist_id}")
    return jsonify({"removed": symbol.strip().upper()})


# --- single-symbol quote (used by the trade form's market-price prefill) ----
@bp.get("/prices/quote/<symbol>")
@require_auth
def quote(symbol: str):
    sym = symbol.strip().upper()
    source = current_app.config.get("PRICE_SOURCE")
    price = None
    if source:
        try:
            price = source.get_prices([sym]).get(sym)
        except Exception:
            price = None
    live = price is not None
    if price is not None:
        _price_store().set_price(sym, price)  # keep the shared table fresh
    else:
        price = _price_store().get_prices([sym]).get(sym)  # last known
    if price is None:
        raise ApiError(
            404, "NoQuote",
            f"no price available for '{sym}' — check the symbol, or set one manually",
        )
    return jsonify(
        {
            "symbol": sym,
            "name": symbols.name_of(sym),
            "price": price,
            "live": live,  # False -> last-known from the table, not a fresh fetch
            "market_open": market_is_open(),
        }
    )


# --- prices (manual stub until Phase 4 wires up live NSE data) --------------
@bp.get("/prices")
@require_auth
def get_prices():
    return jsonify({"prices": _price_store().get_all()})


@bp.post("/prices/refresh")
@require_auth
def refresh_prices():
    """Pull live prices right now instead of waiting for the background job.

    After refreshing we immediately re-check alerts, so a price that crossed a
    target fires without waiting for the next poll.
    """
    source = current_app.config.get("PRICE_SOURCE")
    fresh = refresh_live_prices(g.data.root, source)
    fired = _alert_store().check(_price_store().get_all())
    return jsonify(
        {
            "refreshed": fresh,
            "count": len(fresh),
            "market_open": market_is_open(),
            "triggered": [a.to_dict() for a in fired],
        }
    )


@bp.get("/prices/sources")
@require_auth
def price_sources():
    """Diagnostics: which live source is configured, and can this machine
    actually reach NSE? NSE blocks many IPs, so surfacing the real answer beats
    silently falling back and leaving you wondering why prices look delayed."""
    ok, msg = NsePythonPriceSource().healthcheck()
    return jsonify(
        {
            "mode": current_app.config.get("PRICE_SOURCE_MODE", "auto"),
            "market_open": market_is_open(),
            "nse": {"reachable": ok, "detail": msg},
        }
    )


@bp.get("/prices/<symbol>/history")
@require_auth
def price_history(symbol: str):
    """OHLC history for the price chart. ?period=1mo&interval=1d"""
    period = request.args.get("period", "1mo")
    interval = request.args.get("interval", "1d")
    # Whitelist: these strings go to an upstream API, so don't pass through
    # arbitrary user input.
    if period not in {"5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "ytd", "max"}:
        raise ApiError(400, "BadRequest", "unsupported period")
    if interval not in {"5m", "15m", "30m", "1h", "1d", "1wk", "1mo"}:
        raise ApiError(400, "BadRequest", "unsupported interval")

    source = current_app.config.get("PRICE_SOURCE")
    get_history = getattr(source, "get_history", None)
    if not get_history:
        raise ApiError(503, "NoHistorySource", "the configured price source cannot serve history")
    rows = get_history(symbol, period, interval)
    if not rows:
        raise ApiError(
            502,
            "HistoryUnavailable",
            f"could not fetch history for '{symbol.upper()}' — check the symbol, or the data provider may be rate-limiting",
        )
    return jsonify({"symbol": symbol.strip().upper(), "period": period, "interval": interval, "candles": rows})


@bp.put("/prices/<symbol>")
@require_auth
def set_price(symbol: str):
    body = json_body()
    price = req_num(body, "price")
    if price <= 0:
        raise ApiError(400, "BadRequest", "price must be positive")
    _price_store().set_price(symbol, price)
    # Setting a price is exactly when an alert might fire, so check immediately
    # rather than making the user wait for the next poll.
    fired = _alert_store().check(_price_store().get_all())
    return jsonify(
        {
            "symbol": symbol.strip().upper(),
            "price": round(price, 2),
            "triggered": [a.to_dict() for a in fired],
        }
    )
