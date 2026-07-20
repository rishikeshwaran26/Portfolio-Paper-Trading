"""One-shot migration: JSON files -> SQLite.

    python -m engine.migrate           # migrate data/ into data/papertrading.db
    python -m engine.migrate --dry-run # show what WOULD be migrated
    python -m engine.migrate --force   # allow importing into a non-empty db

What it moves:
    data/users.json                        -> users
    data/prices.json                       -> prices
    data/users/<uid>/portfolios.json       -> portfolios, holdings, transactions, closed_lots
    data/users/<uid>/alerts.json           -> alerts
    data/users/<uid>/snapshots.json        -> snapshots
    data/portfolios.json (legacy CLI file) -> assigned to a user you choose

Nothing is deleted. The JSON files stay exactly where they are, so if anything
looks wrong you still have the originals — verify the app first, then archive
them yourself.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from .db import init_db, transaction
from .portfolio import Portfolio
from .repository import (
    AlertRepository,
    PriceRepository,
    SnapshotRepository,
    SqlitePortfolioManager,
    UserRepository,
)

DEFAULT_ROOT = "data"
DB_NAME = "papertrading.db"


def db_path_for(root: str) -> str:
    return os.path.join(root, DB_NAME)


def _read_json(path: str):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  ! could not read {path}: {e}")
        return None


def migrate(root: str = DEFAULT_ROOT, dry_run: bool = False, force: bool = False) -> dict:
    db = db_path_for(root)
    init_db(db)

    users_repo = UserRepository(db)
    if users_repo.count() and not force and not dry_run:
        raise SystemExit(
            f"{db} already contains {users_repo.count()} user(s). "
            "Re-running would duplicate data. Use --force if you really mean it."
        )

    stats = {"users": 0, "portfolios": 0, "transactions": 0, "alerts": 0, "snapshots": 0, "prices": 0}
    verb = "would migrate" if dry_run else "migrated"

    # --- users ---------------------------------------------------------------
    users_doc = _read_json(os.path.join(root, "users.json")) or {}
    users = users_doc.get("users", {})
    for uid, u in users.items():
        print(f"  user: {u['username']} ({uid})")
        if not dry_run:
            if not users_repo.by_id(uid):
                users_repo.insert(u)
        stats["users"] += 1

    # --- shared prices -------------------------------------------------------
    prices = _read_json(os.path.join(root, "prices.json")) or {}
    if isinstance(prices, dict) and prices:
        print(f"  prices: {len(prices)} symbols")
        if not dry_run:
            PriceRepository(db).set_many({k: float(v) for k, v in prices.items()})
        stats["prices"] = len(prices)

    # --- per-user data -------------------------------------------------------
    for uid in users:
        user_dir = os.path.join(root, "users", uid)
        if not os.path.isdir(user_dir):
            continue

        pdoc = _read_json(os.path.join(user_dir, "portfolios.json")) or {}
        pdata = pdoc.get("portfolios", {})
        if pdata:
            mgr = SqlitePortfolioManager(db, uid)
            for name, raw in pdata.items():
                p = Portfolio.from_dict(raw)
                mgr.portfolios[name] = p
                stats["portfolios"] += 1
                stats["transactions"] += len(p.transactions)
                print(f"    strategy '{name}': {len(p.transactions)} transactions, "
                      f"{len(p.holdings)} holdings")
            if not dry_run:
                mgr.save()

        adoc = _read_json(os.path.join(user_dir, "alerts.json")) or {}
        for a in adoc.get("alerts", []):
            stats["alerts"] += 1
            if not dry_run:
                with transaction(db) as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO alerts "
                        "(id, user_id, symbol, target_price, direction, note, status, "
                        " created_at, triggered_at, triggered_price) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (a["id"], uid, a["symbol"], float(a["target_price"]), a["direction"],
                         a.get("note", ""), a.get("status", "active"),
                         a.get("created_at", datetime.now(timezone.utc).isoformat()),
                         a.get("triggered_at"), a.get("triggered_price")),
                    )

        sdoc = _read_json(os.path.join(user_dir, "snapshots.json")) or {}
        for s in sdoc.get("snapshots", []):
            stats["snapshots"] += 1
            if not dry_run:
                with transaction(db) as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO snapshots "
                        "(user_id, date, timestamp, strategy, total_value, return_pct, cash, "
                        " realized_pnl, unrealized_pnl) VALUES (?,?,?,?,?,?,?,?,?)",
                        (uid, s["date"], s["timestamp"], s["strategy"], float(s["total_value"]),
                         float(s["return_pct"]), float(s.get("cash", 0)),
                         float(s.get("realized_pnl", 0)), float(s.get("unrealized_pnl", 0))),
                    )

    # --- legacy pre-auth CLI file -------------------------------------------
    legacy = os.path.join(root, "portfolios.json")
    legacy_doc = _read_json(legacy)
    if legacy_doc and legacy_doc.get("portfolios"):
        owner = users_repo.all_ids()[0] if users_repo.all_ids() else None
        n = len(legacy_doc["portfolios"])
        if owner:
            print(f"  legacy {legacy}: {n} strategies -> assigning to first user ({owner})")
            if not dry_run:
                mgr = SqlitePortfolioManager(db, owner).load()
                for name, raw in legacy_doc["portfolios"].items():
                    key = name if name not in mgr.portfolios else f"{name} (from CLI)"
                    mgr.portfolios[key] = Portfolio.from_dict(raw)
                    stats["portfolios"] += 1
                mgr.save()
        else:
            print(f"  legacy {legacy}: {n} strategies found but NO user exists yet.")
            print("    Register an account in the web app first, then re-run with --force.")

    print(f"\n{verb}: " + ", ".join(f"{v} {k}" for k, v in stats.items() if v))
    if dry_run:
        print("\n(dry run — nothing was written)")
    else:
        print(f"\nDatabase: {db}")
        print("Your JSON files were NOT deleted. Verify the app works, then archive them.")
    return stats


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        rc = getattr(stream, "reconfigure", None)
        if rc:
            try:
                rc(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass

    ap = argparse.ArgumentParser(description="Migrate JSON data into SQLite")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="data directory (default: data)")
    ap.add_argument("--dry-run", action="store_true", help="show what would happen")
    ap.add_argument("--force", action="store_true", help="allow import into a non-empty db")
    args = ap.parse_args()

    print(f"Migrating JSON in '{args.root}' -> SQLite\n")
    if not os.path.isdir(args.root):
        print(f"No '{args.root}' directory — nothing to migrate. A fresh DB will be created on first run.")
        return
    migrate(args.root, args.dry_run, args.force)


if __name__ == "__main__":
    main()
