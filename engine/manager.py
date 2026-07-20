"""PortfolioManager — owns the set of named strategies, independent of storage.

The Portfolio class is pure trading logic. This class owns the COLLECTION of
strategies and the operations over it (create, look up, rank), but deliberately
knows nothing about where they're stored.

load() and save() are left abstract: engine.repository.SqlitePortfolioManager
implements them against SQLite. That split is why migrating from JSON files to
SQLite didn't touch create_strategy, get, delete_strategy or leaderboard — the
logic that matters lives here, once, and only persistence was swapped.

Portfolios are keyed by strategy name, which is unique per user.
"""

from __future__ import annotations

from typing import Optional

from .errors import InvalidTrade
from .portfolio import Portfolio

DEFAULT_STARTING_CASH = 1_000_000.0  # ₹10,00,000, configurable per strategy


class PortfolioManager:
    """Storage-agnostic base. Subclasses supply load() and save()."""

    def __init__(self):
        self.portfolios: dict[str, Portfolio] = {}

    # -- persistence (implemented by subclasses) ------------------------------
    def load(self) -> "PortfolioManager":
        raise NotImplementedError("use engine.repository.SqlitePortfolioManager")

    def save(self) -> None:
        raise NotImplementedError("use engine.repository.SqlitePortfolioManager")

    # -- strategy management --------------------------------------------------
    def create_strategy(self, name: str, starting_cash: float = DEFAULT_STARTING_CASH) -> Portfolio:
        name = (name or "").strip()
        if not name:
            raise InvalidTrade("strategy name is required")
        if name in self.portfolios:
            raise InvalidTrade(f"strategy '{name}' already exists")
        if starting_cash <= 0:
            raise InvalidTrade("starting cash must be positive")
        p = Portfolio(name=name, cash=starting_cash, starting_cash=starting_cash)
        self.portfolios[name] = p
        return p

    def get(self, name: str) -> Portfolio:
        p = self.portfolios.get(name)
        if p is None:
            raise InvalidTrade(f"no strategy named '{name}'")
        return p

    def delete_strategy(self, name: str) -> None:
        if name not in self.portfolios:
            raise InvalidTrade(f"no strategy named '{name}'")
        del self.portfolios[name]

    def names(self) -> list[str]:
        return list(self.portfolios.keys())

    # -- leaderboard ----------------------------------------------------------
    def leaderboard(self, prices: dict[str, float]) -> list[dict]:
        """Rank YOUR OWN strategies against each other by total value.

        Returns rows sorted best-first, each with the numbers you'd compare:
        total value, total return %, realized and unrealized P&L. This is the
        personal leaderboard — it only ever compares your strategies to your
        other strategies, never to anyone else.
        """
        rows = []
        for name, p in self.portfolios.items():
            rows.append(
                {
                    "strategy": name,
                    "total_value": p.total_value(prices),
                    "return_pct": p.total_return_pct(prices),
                    "cash": p.cash,
                    "holdings_value": p.holdings_value(prices),
                    "realized_pnl": p.realized_pnl(),
                    "unrealized_pnl": p.unrealized_pnl(prices),
                }
            )
        rows.sort(key=lambda r: r["total_value"], reverse=True)
        for i, row in enumerate(rows, start=1):
            row["rank"] = i
        return rows
