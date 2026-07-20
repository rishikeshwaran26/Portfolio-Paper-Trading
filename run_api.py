"""Start the Flask dev server.

    python run_api.py

Serves on http://127.0.0.1:5000. This is Flask's built-in dev server — fine for
local development and the React frontend in Phase 3, but not for production
(you'd put gunicorn/uwsgi in front later).
"""

import sys

from api import create_app
from api.jobs import should_start_worker


def _use_utf8() -> None:
    # Same reason as main.py: let ₹ and P&L text print on the Windows console.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


if __name__ == "__main__":
    _use_utf8()
    DEBUG = True
    # should_start_worker() stops Flask's auto-reloader from running the
    # background jobs twice (once in the parent process, once in the child).
    app = create_app(
        start_worker=should_start_worker(DEBUG),
        alert_interval=15,     # poll prices for alerts every 15s
        snapshot_interval=300,  # refresh today's snapshot row every 5 min
                                # (data stays one point per day — see jobs.py)
    )
    # debug=True gives auto-reload and readable tracebacks in the terminal while
    # developing. Turn it off for anything internet-facing.
    app.run(host="127.0.0.1", port=5000, debug=DEBUG)
