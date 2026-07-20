"""Typed errors so callers (CLI now, Flask later) can react to *why* a trade
failed, instead of parsing error strings. Each maps to a clear user message."""


class TradingError(Exception):
    """Base class for anything the engine rejects on purpose."""


class InsufficientFunds(TradingError):
    pass


class InsufficientHoldings(TradingError):
    pass


class InvalidTrade(TradingError):
    """Bad inputs: non-positive quantity/price, confidence out of range, etc."""


class StorageError(Exception):
    """Raised when the JSON store cannot be read or is corrupt."""
