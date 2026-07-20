"""Periodic portfolio snapshots — the history that makes comparison charts possible.

Why this exists: a Portfolio only knows what it's worth RIGHT NOW. To draw
"return % over time for Momentum vs Value Picks" you need the past, and the past
is only knowable if you recorded it. So a background job appends a row per
strategy per day.

This module holds only the SHAPE of a snapshot. Storage lives in
engine.repository.SnapshotRepository, where the `snapshots` table uses
(user_id, date, strategy) as its primary key — so re-running the job on the same
day upserts that day's row instead of appending a duplicate point, which keeps
the chart honest. Under JSON that de-duplication needed a manual scan; in SQL
it's just ON CONFLICT DO UPDATE.

One flat row per (date, strategy) maps directly onto what a charting library
wants, so `series()` can reshape it for recharts with no work in the frontend.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone


@dataclass
class Snapshot:
    date: str  # YYYY-MM-DD — the de-duplication key
    timestamp: str
    strategy: str
    total_value: float
    return_pct: float
    cash: float
    realized_pnl: float
    unrealized_pnl: float

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Snapshot":
        return cls(
            date=d["date"],
            timestamp=d["timestamp"],
            strategy=d["strategy"],
            total_value=float(d["total_value"]),
            return_pct=float(d["return_pct"]),
            cash=float(d.get("cash", 0)),
            realized_pnl=float(d.get("realized_pnl", 0)),
            unrealized_pnl=float(d.get("unrealized_pnl", 0)),
        )
