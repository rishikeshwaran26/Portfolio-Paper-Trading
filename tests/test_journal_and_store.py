"""Tests for the journal analytics, the manager, and SQLite persistence."""

import os

import pytest

from engine import journal
from engine.db import init_db, transaction
from engine.errors import InvalidTrade
from engine.portfolio import Portfolio
from engine.repository import JournalRepository, SqlitePortfolioManager, UserRepository


# --- journal analytics -------------------------------------------------------
def _closed_scenario() -> Portfolio:
    """Two confidence-5 winners and one confidence-2 loser, so the analytics
    have something meaningful to separate."""
    p = Portfolio(name="J", cash=1_000_000)
    p.buy("A", 10, 100, reason="high conviction", confidence=5, tags=["breakout"])
    p.sell("A", 10, 150, reason="target")          # +500, conf 5
    p.buy("B", 10, 100, reason="high conviction", confidence=5, tags=["breakout"])
    p.sell("B", 10, 140, reason="target")          # +400, conf 5
    p.buy("C", 10, 100, reason="low conviction", confidence=2, tags=["earnings play"])
    p.sell("C", 10, 80, reason="stop")             # -200, conf 2
    return p


def test_performance_by_confidence_separates_buckets():
    p = _closed_scenario()
    stats = {s.label: s for s in journal.performance_by_confidence(p.transactions)}
    assert stats["confidence 5"].total_pnl == 900.0
    assert stats["confidence 5"].win_rate == 1.0
    assert stats["confidence 2"].total_pnl == -200.0
    assert stats["confidence 2"].win_rate == 0.0


def test_performance_by_tag_separates_buckets():
    p = _closed_scenario()
    stats = {s.label: s for s in journal.performance_by_tag(p.transactions)}
    assert stats["breakout"].closed_trades == 2
    assert stats["breakout"].total_pnl == 900.0
    assert stats["earnings play"].total_pnl == -200.0


def test_by_outcome_filters_wins_and_losses():
    p = _closed_scenario()
    wins = journal.by_outcome(p.transactions, profitable=True)
    losses = journal.by_outcome(p.transactions, profitable=False)
    assert {t.symbol for t in wins} == {"A", "B"}
    assert {t.symbol for t in losses} == {"C"}


def test_by_tag_returns_buys_and_matching_sells():
    p = _closed_scenario()
    hits = journal.by_tag(p.transactions, "breakout")
    assert {t.symbol for t in hits} == {"A", "B"}


def test_needs_review_lists_unreviewed_sells():
    p = _closed_scenario()
    p.review(p.transactions[1].id, "took profit at plan")
    assert len(journal.needs_review(p.transactions)) == 2


# --- SQLite-backed manager ---------------------------------------------------
@pytest.fixture
def db(tmp_path):
    """A throwaway database with one user registered."""
    path = str(tmp_path / "t.db")
    init_db(path)
    UserRepository(path).insert(
        {"id": "u1", "username": "t", "password_hash": "x", "created_at": "now"}
    )
    return path


def _manager(db) -> SqlitePortfolioManager:
    return SqlitePortfolioManager(db, "u1")


def test_manager_create_and_duplicate(db):
    m = _manager(db)
    m.create_strategy("Momentum", 500_000)
    assert "Momentum" in m.names()
    with pytest.raises(InvalidTrade):
        m.create_strategy("Momentum")


def test_leaderboard_ranks_by_total_value(db):
    m = _manager(db)
    a = m.create_strategy("A", 100_000)
    b = m.create_strategy("B", 100_000)
    a.buy("X", 10, 1000, reason="x", confidence=3)   # holds; price will rise
    b.buy("Y", 10, 1000, reason="y", confidence=3)
    board = m.leaderboard({"X": 2000, "Y": 1100})    # A up more than B
    assert board[0]["strategy"] == "A"
    assert board[0]["rank"] == 1
    assert board[1]["strategy"] == "B"


def test_save_and_load_round_trip(db):
    """The critical migration test: EVERYTHING must survive a save/load cycle —
    holdings, journal fields, FIFO open_quantity, closed lots, reviews."""
    m = _manager(db)
    p = m.create_strategy("S", 100_000)
    p.buy("Z", 5, 200, reason="thesis", confidence=4, tags=["t1", "t2"])
    p.buy("Z", 5, 300, reason="add", confidence=2, tags=[])
    sell = p.sell("Z", 7, 400, reason="target")
    p.review(sell.id, "sold well")
    m.save()

    p2 = _manager(db).load().get("S")
    assert p2.cash == p.cash
    assert p2.holdings["Z"].quantity == 3
    assert p2.holdings["Z"].avg_price == 250.0
    assert p2.transactions[0].tags == ["t1", "t2"]
    # FIFO state: first buy fully drawn down, second has 3 open
    assert p2.transactions[0].open_quantity == 0
    assert p2.transactions[1].open_quantity == 3
    # sell carries its closed lots with the ORIGINAL buys' confidence
    lots = p2.transactions[2].closed_lots
    assert [(l.quantity, l.confidence) for l in lots] == [(5, 4), (2, 2)]
    assert p2.transactions[2].review == "sold well"


def test_load_empty_db_returns_no_strategies(db):
    assert _manager(db).load().names() == []


def test_deleting_strategy_persists(db):
    m = _manager(db)
    m.create_strategy("Gone", 1000)
    m.save()
    m2 = _manager(db).load()
    m2.delete_strategy("Gone")
    m2.save()
    assert _manager(db).load().names() == []


def test_two_users_are_isolated_at_the_db_layer(db):
    UserRepository(db).insert(
        {"id": "u2", "username": "other", "password_hash": "x", "created_at": "now"}
    )
    m1 = SqlitePortfolioManager(db, "u1")
    m1.create_strategy("Mine", 1000)
    m1.save()
    assert SqlitePortfolioManager(db, "u2").load().names() == []


def test_no_stray_files_besides_db(db, tmp_path):
    m = _manager(db)
    m.create_strategy("S", 1000)
    m.save()
    # WAL mode creates -wal/-shm companions; nothing else should appear
    files = {f for f in os.listdir(tmp_path) if not f.startswith("t.db")}
    assert files == set()


# --- SQL analytics must agree with the Python reference ---------------------
def test_sql_by_tag_matches_python_reference(db):
    """JournalRepository computes by-tag stats in SQL; journal.py is the Python
    reference. They must produce identical numbers or one of them is wrong."""
    m = _manager(db)
    p = m.create_strategy("J", 1_000_000)
    p.buy("A", 10, 100, reason="x", confidence=5, tags=["breakout"])
    p.sell("A", 10, 150, reason="t")
    p.buy("B", 10, 100, reason="x", confidence=5, tags=["breakout"])
    p.sell("B", 10, 140, reason="t")
    p.buy("C", 10, 100, reason="x", confidence=2, tags=["earnings play"])
    p.sell("C", 10, 80, reason="s")
    m.save()

    py = {s.label: s for s in journal.performance_by_tag(p.transactions)}
    sql = {r["label"]: r for r in JournalRepository(db, "u1").performance_by_tag()}

    assert set(py) == set(sql)
    for label in py:
        assert sql[label]["total_pnl"] == py[label].total_pnl, label
        assert sql[label]["closed_trades"] == py[label].closed_trades, label
        assert sql[label]["win_rate"] == py[label].win_rate, label


def test_foreign_keys_cascade_on_user_delete(db):
    """Deleting a user must take all their data with them — that's what the
    ON DELETE CASCADE clauses are for (and PRAGMA foreign_keys=ON enables)."""
    m = _manager(db)
    p = m.create_strategy("S", 1000)
    p.buy("Z", 1, 100, reason="x", confidence=3)
    m.save()
    with transaction(db) as conn:
        conn.execute("DELETE FROM users WHERE id = 'u1'")
    with transaction(db) as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM portfolios").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()["n"] == 0
