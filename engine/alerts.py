"""Price alerts: "tell me when RELIANCE goes above ₹2,900".

Kept in the engine because the *rule* — when does an alert fire? — is domain
logic and should be unit-testable without HTTP, threads or a database. Storage
lives in engine.repository.AlertRepository; this module owns the decision.

An alert has a lifecycle:
    active  --price crosses target-->  triggered  --user acknowledges-->  dismissed

We keep triggered alerts around rather than deleting them, so the UI can show a
banner until you acknowledge it, and so you can see what fired recently.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

ABOVE = "above"
BELOW = "below"

ACTIVE = "active"
TRIGGERED = "triggered"
DISMISSED = "dismissed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Alert:
    id: str
    symbol: str
    target_price: float
    direction: str  # ABOVE or BELOW
    note: str = ""
    status: str = ACTIVE
    created_at: str = field(default_factory=_now)
    triggered_at: Optional[str] = None
    triggered_price: Optional[float] = None

    def should_trigger(self, price: float) -> bool:
        """The whole rule, in one place: an active alert fires when the current
        price crosses its target in the configured direction."""
        if self.status != ACTIVE:
            return False
        if self.direction == ABOVE:
            return price >= self.target_price
        return price <= self.target_price

    def trigger(self, price: float) -> None:
        self.status = TRIGGERED
        self.triggered_at = _now()
        self.triggered_price = round(float(price), 2)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Alert":
        return cls(
            id=d["id"],
            symbol=d["symbol"],
            target_price=float(d["target_price"]),
            direction=d.get("direction", ABOVE),
            note=d.get("note", ""),
            status=d.get("status", ACTIVE),
            created_at=d.get("created_at", _now()),
            triggered_at=d.get("triggered_at"),
            triggered_price=(float(d["triggered_price"]) if d.get("triggered_price") is not None else None),
        )
