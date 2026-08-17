"""Orca hard failures.

All Orca-native exceptions derive from OrcaError so that a single
`except OrcaError` can never be defeated by a stray `except RuntimeError`
or `except ValueError` upstream. Builtin bases are kept where they carry
real semantics (PermissionError, TimeoutError) via multiple inheritance.
"""


class OrcaError(Exception):
    """Base for every Orca-native failure. Catch this, not RuntimeError."""


class HardPrivilegeError(OrcaError, PermissionError):
    """Hard privilege denials — never treat as soft results."""


class OrcaConfigError(OrcaError):
    """Required configuration missing or invalid. Fail closed, do not degrade."""


class CostCapExceeded(OrcaError):
    """Per-run or per-day ceiling exceeded."""


class CostLedgerCorrupt(OrcaError):
    """Day cost ledger unreadable/corrupt — fail closed."""


class UnknownModelError(OrcaError):
    """Model ID not in PRICE_TABLE."""


class PriceTableStaleError(OrcaError):
    """PRICE_TABLE_AS_OF is older than the permitted age — refuse to bill."""


class NTPNotSyncedError(OrcaError):
    """Clock not NTP-synchronized — refuse to arm or fire the scheduler (A14)."""


class GateTimeoutError(OrcaError, TimeoutError):
    """Human gate timed out — fail CLOSED (deny)."""
