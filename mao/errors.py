"""Orca hard failures."""


class HardPrivilegeError(PermissionError):
    """Hard privilege denials — never treat as soft results."""


class CostCapExceeded(RuntimeError):
    """Per-run or per-day ceiling exceeded."""


class CostLedgerCorrupt(Exception):
    """Day cost ledger unreadable/corrupt — fail closed. Not a RuntimeError sibling."""


class UnknownModelError(ValueError):
    """Model ID not in PRICE_TABLE."""


class GateTimeoutError(TimeoutError):
    """Human gate timed out — fail CLOSED (deny)."""
