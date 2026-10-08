"""Ledger reconciliation toolkit.

Reconciles a bank statement against an internal ledger when the two share no
common unique transaction identifier.
"""

from .config import ReconConfig
from .core import build_line_per_line, summarize

__version__ = "0.2.0"
__all__ = ["ReconConfig", "build_line_per_line", "summarize"]
