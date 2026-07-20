"""Live price diagnostic — run this on YOUR machine to see what actually works.

    python -m engine.pricecheck

Why this exists as a script rather than a test: whether NSE answers depends on
your IP, not on your code. NSE serves HTTP 403 to most datacenter/cloud
addresses but usually allows ordinary Indian residential connections. A unit
test that depends on that would be flaky, so instead you get a diagnostic you
run by hand when prices look wrong.

It tells you, in order:
  1. can this machine reach NSE (real-time)?
  2. can it reach Yahoo (delayed ~15 min, but reliable from anywhere)?
  3. what does the configured chain actually return?
"""

from __future__ import annotations

import sys

from .prices import (
    NsePythonPriceSource,
    YFinancePriceSource,
    build_source,
    market_is_open,
)

SAMPLE = ["RELIANCE", "TCS", "INFY"]


def _use_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main() -> None:
    _use_utf8()
    print("=" * 62)
    print(" Paper Trading — live price diagnostic")
    print("=" * 62)
    print(f"NSE market open right now: {'YES' if market_is_open() else 'no (showing last close)'}")

    # 1. NSE
    print("\n[1] NSE via nsepython (real-time)")
    ok, msg = NsePythonPriceSource().healthcheck()
    print(f"    reachable: {'YES' if ok else 'NO'}  —  {msg}")
    if ok:
        got = NsePythonPriceSource().get_prices(SAMPLE)
        print(f"    prices: {got}")
    else:
        print("    -> This is normal on cloud/datacenter IPs. NSE blocks them.")
        print("       If you're on a home connection in India and still see this,")
        print("       try again during market hours, or use yfinance mode.")

    # 2. Yahoo
    print("\n[2] Yahoo Finance via yfinance (delayed ~15min, works anywhere)")
    try:
        yf_src = YFinancePriceSource()
        got = yf_src.get_prices(SAMPLE)
        if got:
            print(f"    reachable: YES  —  prices: {got}")
        else:
            print("    reachable: NO  —  empty response (possibly rate-limited; retry in a minute)")
    except Exception as e:
        print(f"    reachable: NO  —  {type(e).__name__}: {str(e)[:120]}")

    # 3. The configured chain
    print("\n[3] Configured chain (what the app will actually use)")
    chain = build_source("auto")
    got = chain.get_prices(SAMPLE)
    print(f"    resolved prices: {got}")
    missing = [s for s in SAMPLE if s not in got]
    if missing:
        print(f"    could not price: {missing}")

    # 4. History (drives the charts)
    print("\n[4] History for charts")
    rows = chain.get_history("RELIANCE", "1mo")
    if rows:
        print(f"    RELIANCE 1mo: {len(rows)} candles, {rows[0]['date']} .. {rows[-1]['date']}")
        print(f"    latest close: {rows[-1]['close']}")
    else:
        print("    no history available — charts will be empty")

    print("\nDone. Set PAPERTRADING_PRICE_SOURCE=nse|yfinance|auto|manual to force a mode.")


if __name__ == "__main__":
    main()
