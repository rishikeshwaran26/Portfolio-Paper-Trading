"""SQLite schema and connection handling.

Why migrate off JSON
--------------------
JSON was right for Phase 1: readable, zero setup, easy to eyeball while the data
model was still moving. It stops being right once you want to *ask questions*.
Every analytics call currently loads every transaction of every strategy into
Python and filters in a loop. With SQL, "win rate by tag" is a GROUP BY that the
database does for us, and it stays fast as the journal grows.

The other thing JSON couldn't give us: safe concurrent writes. The background
worker and a web request could previously both read-modify-write the same file
and silently clobber each other (last writer wins). SQLite gives us real
transactions and row-level correctness instead.

Schema notes
------------
- `closed_lots` is its own TABLE, not a JSON blob on the sell. This is the
  single most important modelling decision here: closed lots are what journal
  analytics aggregates over ("avg holding days for winners", "P&L by tag"), and
  putting them in a real table is what makes those queries SQL instead of Python
  loops.

- `tags` IS stored as a JSON array in a TEXT column. A fully normalised
  tag/tag_link pair of tables would be more "correct", but tags here are a short
  list of free-text labels attached to one transaction, always read together
  with it, and never updated independently. The join cost isn't worth it. Where
  we DO need to query by tag we use json_each(), which SQLite provides.

- Money is REAL (float rupees), matching the engine. For a real money system
  you'd store integer paise to avoid float dust — noted as a known simplification.

- Foreign keys use ON DELETE CASCADE and we enable `PRAGMA foreign_keys=ON` per
  connection (SQLite defaults it OFF, which surprises people).

- WAL mode lets the background worker read while a request writes, instead of
  the two blocking each other.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolios (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    cash          REAL NOT NULL,
    starting_cash REAL NOT NULL,
    created_at    TEXT NOT NULL,
    UNIQUE (user_id, name)
);

CREATE TABLE IF NOT EXISTS holdings (
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    symbol       TEXT    NOT NULL,
    quantity     INTEGER NOT NULL,
    avg_price    REAL    NOT NULL,
    PRIMARY KEY (portfolio_id, symbol)
);

CREATE TABLE IF NOT EXISTS transactions (
    id            TEXT PRIMARY KEY,
    portfolio_id  INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    seq           INTEGER NOT NULL,          -- preserves insertion order
    type          TEXT    NOT NULL,          -- BUY | SELL
    symbol        TEXT    NOT NULL,
    quantity      INTEGER NOT NULL,
    price         REAL    NOT NULL,
    timestamp     TEXT    NOT NULL,
    reason        TEXT    NOT NULL DEFAULT '',
    confidence    INTEGER,                   -- buys only
    tags          TEXT    NOT NULL DEFAULT '[]',
    open_quantity INTEGER NOT NULL DEFAULT 0,
    realized_pnl  REAL,                      -- sells only
    review        TEXT
);
CREATE INDEX IF NOT EXISTS idx_txn_portfolio ON transactions(portfolio_id, seq);

CREATE TABLE IF NOT EXISTS closed_lots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sell_id      TEXT    NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    position     INTEGER NOT NULL,           -- order within the sell
    buy_id       TEXT    NOT NULL,
    quantity     INTEGER NOT NULL,
    buy_price    REAL    NOT NULL,
    sell_price   REAL    NOT NULL,
    confidence   INTEGER,
    tags         TEXT    NOT NULL DEFAULT '[]',
    holding_days REAL    NOT NULL,
    lot_pnl      REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lot_sell ON closed_lots(sell_id);

CREATE TABLE IF NOT EXISTS alerts (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol          TEXT NOT NULL,
    target_price    REAL NOT NULL,
    direction       TEXT NOT NULL,           -- above | below
    note            TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL,           -- active | triggered | dismissed
    created_at      TEXT NOT NULL,
    triggered_at    TEXT,
    triggered_price REAL
);
CREATE INDEX IF NOT EXISTS idx_alert_user ON alerts(user_id, status);

CREATE TABLE IF NOT EXISTS snapshots (
    user_id        TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date           TEXT NOT NULL,            -- YYYY-MM-DD, the upsert key
    timestamp      TEXT NOT NULL,
    strategy       TEXT NOT NULL,
    total_value    REAL NOT NULL,
    return_pct     REAL NOT NULL,
    cash           REAL NOT NULL,
    realized_pnl   REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    PRIMARY KEY (user_id, date, strategy)
);

-- Symbols a user is watching (no position needed). The composite key makes
-- adding the same symbol twice a natural no-op via INSERT OR IGNORE.
CREATE TABLE IF NOT EXISTS watchlist (
    user_id  TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol   TEXT NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (user_id, symbol)
);

-- Prices are MARKET data: shared by every user, not scoped to one.
CREATE TABLE IF NOT EXISTS prices (
    symbol     TEXT PRIMARY KEY,
    price      REAL NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    """Open a connection with the pragmas we depend on.

    We open a fresh connection per unit of work rather than sharing one. SQLite
    connections are not safe to share across threads, and the background worker
    runs in its own thread — a new connection is cheap (microseconds) and removes
    that whole class of bug.
    """
    directory = os.path.dirname(os.path.abspath(db_path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row  # rows behave like dicts: row["cash"]
    conn.execute("PRAGMA foreign_keys = ON")   # OFF by default in SQLite!
    conn.execute("PRAGMA journal_mode = WAL")  # readers don't block the writer
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def transaction(db_path: str):
    """Run a unit of work in a single transaction.

    Commits on success, rolls back on any exception. This is the guarantee JSON
    could never give us: a buy that updates cash, holdings AND appends a
    transaction row either happens completely or not at all.
    """
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    """Create the schema if it doesn't exist. Safe to call on every startup."""
    with transaction(db_path) as conn:
        conn.executescript(SCHEMA)
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )


def schema_version(db_path: str) -> int:
    with transaction(db_path) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        return int(row["value"]) if row else 0
