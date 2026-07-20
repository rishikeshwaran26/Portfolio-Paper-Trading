"""Interactive CLI to exercise the whole engine by hand — no web layer.

This is a thin shell: every menu action calls the same Portfolio /
PortfolioManager / journal methods that Flask calls. It reads prices from a
ManualPriceSource, so you can drive realistic scenarios (buy, watch unrealized
P&L move as you enter new prices, sell, review) entirely offline.

The CLI now reads and writes THE SAME SQLite database as the web app
(data/papertrading.db), scoped to a user you pick at startup. Trades you make
here show up in the browser and vice versa — one source of truth, two frontends.

Run it with:  python main.py
"""

from __future__ import annotations

import os

from . import journal
from .db import init_db
from .errors import StorageError, TradingError
from .manager import DEFAULT_STARTING_CASH
from .models import BUY, SELL
from .prices import ManualPriceSource
from .repository import SqlitePortfolioManager, UserRepository

DB_PATH = os.path.join("data", "papertrading.db")


def _pick_user(db_path: str) -> str | None:
    """Choose which account's portfolios the CLI operates on.

    The web app scopes everything by the logged-in user; the CLI has no login,
    so it asks. One account -> auto-selected; none -> offer to create one
    (password must then be set via the web app's register flow — the CLI does
    not handle passwords)."""
    repo = UserRepository(db_path)
    ids = repo.all_ids()
    if not ids:
        print("\nNo accounts exist yet. Create one in the web app first")
        print("(python run_api.py + npm run dev), or continue with a local")
        name = _ask("CLI-only account name (blank to abort): ")
        if not name:
            return None
        import uuid
        from datetime import datetime, timezone

        user = {
            "id": uuid.uuid4().hex[:12],
            "username": name,
            # No password: this account can't log into the web UI until one is
            # set. Marked clearly so it can't be mistaken for a real hash.
            "password_hash": "!cli-only-no-password",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        repo.insert(user)
        return user["id"]
    if len(ids) == 1:
        return ids[0]
    print("\nAccounts:")
    users = [repo.by_id(uid) for uid in ids]
    for i, u in enumerate(users, 1):
        print(f"  {i}) {u['username']}")
    while True:
        n = _ask_int("Which account? ")
        if 1 <= n <= len(users):
            return users[n - 1]["id"]


# --- tiny input helpers ------------------------------------------------------
def _ask(prompt: str) -> str:
    return input(prompt).strip()


def _ask_int(prompt: str) -> int:
    while True:
        try:
            return int(_ask(prompt))
        except ValueError:
            print("  please enter a whole number.")


def _ask_float(prompt: str) -> float:
    while True:
        try:
            return float(_ask(prompt))
        except ValueError:
            print("  please enter a number.")


def _rupees(x: float) -> str:
    return f"₹{x:,.2f}"


def _pnl(x: float) -> str:
    sign = "+" if x >= 0 else ""
    return f"{sign}{_rupees(x)}"


class TradingCLI:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.manager: SqlitePortfolioManager | None = None
        # One shared manual price source for the session — handy for what-if
        # scenarios even now that the web app pulls live prices.
        self.prices = ManualPriceSource()
        self.current: str | None = None

    # -- lifecycle ------------------------------------------------------------
    def run(self) -> None:
        init_db(self.db_path)  # idempotent; a fresh install just works
        user_id = _pick_user(self.db_path)
        if user_id is None:
            print("Bye.")
            return
        self.manager = SqlitePortfolioManager(self.db_path, user_id)
        try:
            self.manager.load()
        except StorageError as e:
            print(f"\n!! Could not load data: {e}\n")
            if _ask("Start with an empty set of strategies? [y/N] ").lower() != "y":
                print("Aborting so you can investigate the database.")
                return
        print("\n=== Paper Trading Simulator (NSE/BSE) ===")
        while True:
            self._print_menu()
            choice = _ask("> ")
            if choice == "0":
                self._save()
                print("Saved. Bye.")
                return
            self._dispatch(choice)

    def _dispatch(self, choice: str) -> None:
        actions = {
            "1": self.create_strategy,
            "2": self.select_strategy,
            "3": self.buy,
            "4": self.sell,
            "5": self.view_portfolio,
            "6": self.view_transactions,
            "7": self.view_pnl,
            "8": self.view_journal,
            "9": self.journal_analytics,
            "10": self.review_trade,
            "11": self.leaderboard,
            "12": self.set_price,
        }
        action = actions.get(choice)
        if not action:
            print("  unknown option.")
            return
        try:
            action()
        except TradingError as e:
            print(f"  ✗ {e}")
        except StorageError as e:
            print(f"  ✗ storage: {e}")

    def _print_menu(self) -> None:
        cur = f"  [current: {self.current}]" if self.current else "  [no strategy selected]"
        print(f"\n--- menu ---{cur}")
        print(" 1) create strategy      2) select strategy     3) buy")
        print(" 4) sell                 5) view portfolio      6) transaction history")
        print(" 7) view P&L             8) trade journal       9) journal analytics")
        print("10) review a trade      11) leaderboard        12) set a price")
        print(" 0) save & quit")

    # -- helpers --------------------------------------------------------------
    def _save(self) -> None:
        self.manager.save()

    def _require_current(self):
        if not self.current:
            raise TradingError("select or create a strategy first (option 1 or 2)")
        return self.manager.get(self.current)

    def _price_map(self) -> dict[str, float]:
        symbols = set()
        for p in self.manager.portfolios.values():
            symbols.update(p.holdings.keys())
        return self.prices.get_prices(list(symbols))

    # -- actions --------------------------------------------------------------
    def create_strategy(self) -> None:
        name = _ask("strategy name: ")
        raw = _ask(f"starting cash [{_rupees(DEFAULT_STARTING_CASH)}]: ")
        cash = float(raw) if raw else DEFAULT_STARTING_CASH
        self.manager.create_strategy(name, cash)
        self.current = name
        self._save()
        print(f"  ✓ created '{name}' with {_rupees(cash)}")

    def select_strategy(self) -> None:
        names = self.manager.names()
        if not names:
            print("  no strategies yet — create one first.")
            return
        for i, n in enumerate(names, 1):
            print(f"  {i}) {n}")
        idx = _ask_int("pick #: ")
        if 1 <= idx <= len(names):
            self.current = names[idx - 1]
            print(f"  ✓ selected '{self.current}'")
        else:
            print("  out of range.")

    def buy(self) -> None:
        p = self._require_current()
        symbol = _ask("symbol (e.g. RELIANCE): ")
        qty = _ask_int("quantity: ")
        price = _ask_float("price per share: ")
        reason = _ask("reason / thesis (required): ")
        confidence = _ask_int("confidence 1-5: ")
        tags_raw = _ask("tags (comma-separated, optional): ")
        tags = [t for t in (s.strip() for s in tags_raw.split(",")) if t]
        txn = p.buy(symbol, qty, price, reason, confidence, tags)
        # Seed the manual price so unrealized P&L works immediately.
        self.prices.set_price(symbol, price)
        self._save()
        print(f"  ✓ bought {qty} {txn.symbol} @ {_rupees(price)} | cash left {_rupees(p.cash)} | id {txn.id}")

    def sell(self) -> None:
        p = self._require_current()
        symbol = _ask("symbol: ")
        qty = _ask_int("quantity: ")
        price = _ask_float("price per share: ")
        reason = _ask("reason for selling (required): ")
        txn = p.sell(symbol, qty, price, reason)
        self.prices.set_price(symbol, price)
        self._save()
        print(f"  ✓ sold {qty} {txn.symbol} @ {_rupees(price)} | realized {_pnl(txn.realized_pnl or 0)} | id {txn.id}")

    def view_portfolio(self) -> None:
        p = self._require_current()
        prices = self._price_map()
        print(f"\n  Strategy: {p.name}")
        print(f"  Cash:            {_rupees(p.cash)}")
        print(f"  Holdings value:  {_rupees(p.holdings_value(prices))}")
        print(f"  Total value:     {_rupees(p.total_value(prices))}")
        print(f"  Total return:    {p.total_return_pct(prices):+.2f}%")
        if not p.holdings:
            print("  (no open holdings)")
            return
        print(f"\n  {'SYMBOL':<12}{'QTY':>6}{'AVG':>12}{'LTP':>12}{'MKT VALUE':>15}{'UNREAL P&L':>15}")
        for s, h in p.holdings.items():
            ltp = prices.get(s, h.avg_price)
            print(
                f"  {s:<12}{h.quantity:>6}{h.avg_price:>12,.2f}{ltp:>12,.2f}"
                f"{h.market_value(ltp):>15,.2f}{h.unrealized_pnl(ltp):>+15,.2f}"
            )
        print("  (symbols with no set price are shown at avg cost — use option 12)")

    def view_transactions(self) -> None:
        p = self._require_current()
        if not p.transactions:
            print("  no transactions yet.")
            return
        print(f"\n  {'ID':<14}{'TYPE':<6}{'SYMBOL':<12}{'QTY':>6}{'PRICE':>12}{'WHEN':<22}")
        for t in p.transactions:
            when = t.timestamp[:19].replace("T", " ")
            print(f"  {t.id:<14}{t.type:<6}{t.symbol:<12}{t.quantity:>6}{t.price:>12,.2f}  {when}")

    def view_pnl(self) -> None:
        p = self._require_current()
        prices = self._price_map()
        realized = p.realized_pnl()
        unrealized = p.unrealized_pnl(prices)
        print(f"\n  Realized P&L (booked):    {_pnl(realized)}")
        print(f"  Unrealized P&L (paper):   {_pnl(unrealized)}")
        print(f"  Combined:                 {_pnl(round(realized + unrealized, 2))}")
        print("  realized = profit locked in by sells; unrealized = paper gain on what you still hold")

    def view_journal(self) -> None:
        p = self._require_current()
        if not p.transactions:
            print("  journal is empty.")
            return
        for t in p.transactions:
            when = t.timestamp[:19].replace("T", " ")
            print(f"\n  [{t.id}] {t.type} {t.quantity} {t.symbol} @ {_rupees(t.price)}  ({when})")
            print(f"     reason: {t.reason}")
            if t.type == BUY:
                print(f"     confidence: {t.confidence}/5   tags: {', '.join(t.tags) or '—'}   still open: {t.open_quantity}")
            else:
                print(f"     realized P&L: {_pnl(t.realized_pnl or 0)}")
                for lot in t.closed_lots:
                    print(
                        f"       ↳ closed {lot.quantity} from buy {lot.buy_id}: "
                        f"conf {lot.confidence}, held {lot.holding_days:.2f}d, lot P&L {_pnl(lot.lot_pnl)}"
                    )
            if t.review:
                print(f"     review: {t.review}")

    def journal_analytics(self) -> None:
        p = self._require_current()
        conf_rows = journal.performance_by_confidence(p.transactions)
        tag_rows = journal.performance_by_tag(p.transactions)
        if not conf_rows and not tag_rows:
            print("  no closed trades yet — analytics need at least one sell.")
            return
        print("\n  === performance by confidence (closed trades only) ===")
        print(f"  {'BUCKET':<16}{'TRADES':>7}{'WIN%':>8}{'TOTAL P&L':>14}{'AVG P&L':>12}{'AVG DAYS':>10}")
        for s in conf_rows:
            print(
                f"  {s.label:<16}{s.closed_trades:>7}{s.win_rate*100:>7.0f}%"
                f"{s.total_pnl:>+14,.2f}{s.avg_pnl:>+12,.2f}{s.avg_holding_days:>10.1f}"
            )
        print("\n  === performance by tag ===")
        print(f"  {'TAG':<16}{'TRADES':>7}{'WIN%':>8}{'TOTAL P&L':>14}{'AVG P&L':>12}{'AVG DAYS':>10}")
        for s in tag_rows:
            print(
                f"  {s.label:<16}{s.closed_trades:>7}{s.win_rate*100:>7.0f}%"
                f"{s.total_pnl:>+14,.2f}{s.avg_pnl:>+12,.2f}{s.avg_holding_days:>10.1f}"
            )

    def review_trade(self) -> None:
        p = self._require_current()
        unreviewed = journal.needs_review(p.transactions)
        if unreviewed:
            print("  closed trades awaiting a review note:")
            for t in unreviewed:
                print(f"    {t.id}  sold {t.quantity} {t.symbol}  realized {_pnl(t.realized_pnl or 0)}")
        txn_id = _ask("transaction id to review: ")
        notes = _ask("retrospective notes: ")
        p.review(txn_id, notes)
        self._save()
        print("  ✓ review saved")

    def leaderboard(self) -> None:
        if not self.manager.portfolios:
            print("  no strategies yet.")
            return
        rows = self.manager.leaderboard(self._price_map())
        print("\n  === your strategy leaderboard ===")
        print(f"  {'#':<3}{'STRATEGY':<22}{'TOTAL VALUE':>16}{'RETURN':>10}{'REALIZED':>14}{'UNREAL':>14}")
        for r in rows:
            print(
                f"  {r['rank']:<3}{r['strategy']:<22}{r['total_value']:>16,.2f}"
                f"{r['return_pct']:>+9.2f}%{r['realized_pnl']:>+14,.2f}{r['unrealized_pnl']:>+14,.2f}"
            )

    def set_price(self) -> None:
        symbol = _ask("symbol: ")
        price = _ask_float("current price: ")
        self.prices.set_price(symbol, price)
        print(f"  ✓ {symbol.upper()} set to {_rupees(price)} (drives unrealized P&L this session)")
