"""Runs the market screener asynchronously and reports live progress.

Why a service object and not just a route
-----------------------------------------
A full-exchange scan takes ~a minute (yfinance rate limits force batching). We
must NOT block an HTTP request for that long, and we must NOT let two scans run
at once (they'd fight over the same rows). So one long-lived ScreenerService per
app owns a single worker thread and a bit of in-memory progress state:

    POST /screener/scan   -> service.start()   (returns immediately, 202)
    GET  /screener/status -> service.snapshot() (the live progress bar)
    GET  /screener        -> reads the finished result from SQLite

The finished movers are persisted (ScreenerRepository); only the transient
"37% done, scanning 700/1900" progress lives here in memory, because it's
worthless the moment the scan ends.
"""

from __future__ import annotations

import threading
from datetime import datetime

from engine import screener, universe
from engine.prices import IST
from engine.repository import ScreenerRepository


def today_ist() -> str:
    """The date the scan is 'for', in IST — the market's timezone. A scan run at
    01:00 UTC is still 'today' for NSE, so we must not use UTC's date here."""
    return datetime.now(IST).strftime("%Y-%m-%d")


class ScreenerService:
    def __init__(self):
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state: dict = {
            "status": "idle",     # idle | running | done | error
            "done": 0,
            "total": 0,
            "percent": 0,
            "message": "",
            "run_id": None,
            "error": None,
            "started_at": None,
            "finished_at": None,
        }

    # -- state ----------------------------------------------------------------
    def is_running(self) -> bool:
        with self._lock:
            return self._state["status"] == "running"

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def _set(self, **kw) -> None:
        with self._lock:
            self._state.update(kw)

    # -- control --------------------------------------------------------------
    def start(
        self,
        db_path: str,
        cache_path: str,
        data,
        scan_date: str | None = None,
        min_volume: int = screener.DEFAULT_MIN_VOLUME,
        chunk_size: int = 100,
    ) -> bool:
        """Kick off a scan in the background. Returns False if one is already
        running (the caller turns that into a 409) or if no data provider is
        configured."""
        if data is None:
            return False
        with self._lock:
            if self._state["status"] == "running":
                return False
            self._state.update(
                status="running", done=0, total=0, percent=0,
                message="Starting scan…", run_id=None, error=None,
                started_at=datetime.now(IST).isoformat(), finished_at=None,
            )
        scan_date = scan_date or today_ist()
        self._thread = threading.Thread(
            target=self._run,
            args=(db_path, cache_path, data, scan_date, min_volume, chunk_size),
            name="screener-scan",
            daemon=True,
        )
        self._thread.start()
        return True

    def _run(self, db_path, cache_path, data, scan_date, min_volume, chunk_size) -> None:
        repo = ScreenerRepository(db_path)
        run_id = None
        try:
            run_id = repo.create_run(scan_date)
            self._set(run_id=run_id)

            def progress(done, total, message):
                pct = int(done / total * 100) if total else 0
                self._set(done=done, total=total, percent=pct, message=message)

            rows, source = universe.load_universe(cache_path)
            self._set(total=len(rows), message=f"Scanning {len(rows)} stocks…")
            result = screener.scan(
                rows, data, source=source,
                min_volume=min_volume, chunk_size=chunk_size, progress=progress,
            )
            repo.finish_run(run_id, result)
            self._set(
                status="done", percent=100,
                message=f"Found {len(result.movers)} movers across {len(rows)} stocks",
                finished_at=datetime.now(IST).isoformat(),
            )
        except Exception as e:  # a scan blowing up must not kill the thread silently
            if run_id is not None:
                try:
                    repo.fail_run(run_id, f"{type(e).__name__}: {e}")
                except Exception:
                    pass
            self._set(
                status="error", error=f"{type(e).__name__}: {e}",
                message="Scan failed", finished_at=datetime.now(IST).isoformat(),
            )
