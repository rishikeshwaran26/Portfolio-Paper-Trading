# Paper Trading Simulator — NSE/BSE (learning project)

A virtual-money trading simulator for Indian stocks. Create multiple "strategy"
portfolios, buy/sell at live prices, and — the whole point — keep a **trade
journal** that records *why* each trade was made, so you can later check whether
your reasoning actually held up.

All phases built: core engine → Flask REST API → React frontend → live NSE
prices (with Yahoo fallback) + price charts → alerts, snapshots, comparison,
analytics, auth → SQLite storage → watchlist, symbol search, auto-updating
quotes (Groww-style) → **short selling**.

**Short selling:** four trade actions — BUY/SELL for long positions, and
SHORT/COVER for short ones. A short is stored as a negative holding quantity,
so one formula handles P&L for both sides (you profit when the price falls).
Journal analytics break out long vs short performance separately, since
betting on a rise and betting on a fall are different skills. Known
simplifications: no borrow fee or margin interest is modeled, and intraday
shorts are not force-squared-off at end of day.

**About "real-time":** there is no free official real-time API for NSE.
`nsepython` gives real-time quotes when NSE doesn't block your IP (home
connections in India usually work); Yahoo Finance is the always-working
fallback at ~15 min delay. The UI polls and re-renders on its own either way.
If you ever open a broker account with a free API (e.g. AngelOne SmartAPI),
implement its `get_prices()` in `engine/prices.py` and add it to the chain —
nothing else changes.

> A fuller architecture README is meant to be written by hand — see
> [README_OUTLINE.md](README_OUTLINE.md) for the scaffold and the raw design
> decisions to write it from.

## Run it

One-time setup:

```bash
pip install -r requirements.txt
cd frontend && npm install && cd ..
```

Every time — two terminals:

```bash
# terminal 1 — backend  (http://127.0.0.1:5000)
python run_api.py

# terminal 2 — frontend (http://localhost:5173)
cd frontend
npm run dev
```

Open http://localhost:5173 — first run offers "create your account".

```bash
python main.py                  # CLI — same database as the web app
python -m pytest -q             # 113 tests
python -m engine.pricecheck     # which live price sources work from YOUR machine
python -m engine.migrate        # one-shot: import old JSON data into SQLite
```

## Storage

Everything lives in one SQLite file: `data/papertrading.db` (created
automatically). The CLI and the web app read and write the **same** database —
one source of truth, two frontends. If you have data from the earlier JSON-file
era, `python -m engine.migrate` imports it (originals are left untouched).

## Layout

| File | What it holds |
|------|---------------|
| `engine/models.py` | Data shapes: `Holding`, `Transaction`, `ClosedLot` |
| `engine/portfolio.py` | The trading rules: `buy`, `sell`, P&L, `review` |
| `engine/manager.py` | Storage-agnostic strategy collection + leaderboard |
| `engine/journal.py` | Journal analytics (Python reference implementation) |
| `engine/db.py` | SQLite schema, connections, transactions |
| `engine/repository.py` | All SQLite persistence (portfolios, alerts, snapshots, prices, users) + SQL analytics |
| `engine/migrate.py` | JSON → SQLite one-shot migration |
| `engine/prices.py` | Live price sources: NSE → Yahoo fallback chain, caching, history |
| `engine/alerts.py` / `snapshots.py` | Alert + snapshot domain objects |
| `engine/cli.py` | The interactive terminal menu |
| `api/routes.py` | REST endpoints (HTTP ↔ engine translation) |
| `api/auth.py` | Accounts, password hashing, bearer tokens |
| `api/jobs.py` | Background worker: live prices, alert checks, daily snapshots |
| `frontend/src/` | React app: dashboard, detail + price charts, journal, analytics, compare, alerts |
| `tests/` | 113 tests documenting every rule |

## Key design ideas

- **Average-cost holdings, FIFO journal linking.** Your position uses a single
  average price. On top of that, each sell records *which buys it closed* (FIFO)
  so the journal can attribute realized profit back to the confidence and tags
  you set when buying.
- **The transaction record IS the journal entry.** Every buy/sell carries its
  own `reason` / `confidence` / `tags` / `review`.
- **Prices come from outside the engine** — it only ever receives a
  `{symbol: price}` dict. Live sources (NSE, then Yahoo) feed a persistent price
  table; a network failure degrades to last-known prices, never a crash.
- **Storage behind a seam.** Trading logic never touches persistence directly;
  swapping JSON files for SQLite touched the repository layer and almost
  nothing else. `closed_lots` is a real table, so "win rate by tag" is a SQL
  GROUP BY instead of a Python loop.
- **Every route is user-scoped** via the auth token — no hardcoded "the one
  user", so multi-user is a data change, not a rewrite.

## The journal questions this is built to answer

- Do my **high-confidence** trades actually make more money? → Analytics page,
  "avg P&L by confidence"
- Do my **'technical breakout'** trades beat my **'earnings play'** trades? →
  "win rate by tag"
- Do I hold **losers longer than winners** (disposition effect)? → the
  winners-vs-losers holding-duration comparison
