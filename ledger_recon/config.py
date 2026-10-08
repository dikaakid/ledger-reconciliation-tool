"""
Configuration for the reconciliation engine.

Everything that is specific to a data provider (reference formats, prefix
routing table, column names, thresholds) lives here, so the engine itself
contains no provider-specific knowledge. Override any field with a JSON file:

    ledger-recon run --config my_config.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path

# Regex templates. "{n}" is replaced by each candidate length (exact length,
# never a range -- see reference.py). Capture group 1 must be the reference.
DEFAULT_CHANNEL_PATTERNS: dict[str, str] = {
    "TRF": r"TRF\s*(\d{{{n}}})",
    "REF": r"REF(\d{{{n}}})",
    "LEADING": r"^(\d{{{n}}})#",
}

# Fictional routing table: reference prefix -> account the money must land in.
DEFAULT_PREFIX_TO_ACCOUNT: dict[str, str] = {
    "88001": "0100000001",
    "88002": "0100000001",
    "88003": "0100000002",
    "88004": "0100000003",
    "88005": "0100000002",
}


@dataclass
class ReconConfig:
    # --- reference extraction -------------------------------------------
    candidate_lengths: tuple = (16, 15, 14)
    channel_patterns: dict = field(default_factory=lambda: dict(DEFAULT_CHANNEL_PATTERNS))
    prefix_len: int = 5
    prefix_to_account: dict = field(default_factory=lambda: dict(DEFAULT_PREFIX_TO_ACCOUNT))
    routing_effective_date: date = date(2026, 1, 1)

    # --- matching -------------------------------------------------------
    amount_decimals: int = 2  # amounts are compared as integer minor units
    ledger_success_status: str = "SUCCESS"
    ledger_window_days: int = 0  # 0 = same calendar day only (auditable)
    high_frequency_threshold: int = 5

    # --- confidence thresholds (minutes between paired rows) ------------
    strong_minutes: float = 1
    moderate_minutes: float = 10

    # --- guards / tracker -----------------------------------------------
    placeholder_text: str = "no transaction found"
    recheck_max_days: int = 7  # a pending bank row may only resolve against
    # a ledger row up to N days later
    tracker_backup_keep: int = 10

    # --- column renames: {"your column": "canonical column"} -------------
    statement_columns: dict = field(default_factory=dict)
    ledger_columns: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, path: str | Path) -> ReconConfig:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        unknown = set(raw) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown config keys: {sorted(unknown)}")
        if "routing_effective_date" in raw:
            raw["routing_effective_date"] = date.fromisoformat(raw["routing_effective_date"])
        if "candidate_lengths" in raw:
            raw["candidate_lengths"] = tuple(raw["candidate_lengths"])
        return cls(**raw)
