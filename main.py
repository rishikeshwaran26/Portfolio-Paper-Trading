"""Entry point for the Phase 1 CLI.

    python main.py

Everything lives under engine/. This file just wires up and launches the CLI so
the package stays import-clean for the tests and the future Flask app.
"""

import sys

from engine.cli import TradingCLI


def _use_utf8() -> None:
    """The default Windows console encoding (cp1252) can't print the ₹ symbol.
    Reconfigure the streams to UTF-8 so the rupee sign and P&L arrows render
    everywhere. errors='replace' means a truly unmappable char degrades to '?'
    instead of crashing."""
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main() -> None:
    _use_utf8()
    TradingCLI().run()


if __name__ == "__main__":
    main()
