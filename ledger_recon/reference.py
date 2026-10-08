"""
Payment-reference extraction from free-text bank descriptions.

Design rule: try EXACT lengths one after another (longest/most common first),
never a greedy range such as \\d{14,16}. When other digits are glued directly
behind a real reference, a greedy range over-consumes and silently returns a
wrong reference. An exact-length attempt can never take more than n digits.

Every candidate must also start with a known prefix; otherwise it is logged as
an anomaly and the row is treated as having no reference. Without this check,
unrelated digit runs could be reconciled as if they were real references.
"""

from __future__ import annotations

import re

import pandas as pd

from .config import ReconConfig


class ReferenceExtractor:
    def __init__(self, cfg: ReconConfig):
        self.cfg = cfg
        self.patterns = {
            channel: {n: re.compile(tpl.format(n=n), re.IGNORECASE) for n in cfg.candidate_lengths}
            for channel, tpl in cfg.channel_patterns.items()
        }
        self.anomalies: list[tuple[str, str, str]] = []  # (channel, digits, description)

    def is_known_prefix(self, digits: str) -> bool:
        return digits[: self.cfg.prefix_len] in self.cfg.prefix_to_account

    def extract(self, description) -> str | None:
        if description is None or pd.isna(description):
            return None
        text = str(description)
        for channel, by_len in self.patterns.items():
            for n in self.cfg.candidate_lengths:
                match = by_len[n].search(text)
                if match:
                    ref = match.group(1)
                    if self.is_known_prefix(ref):
                        return ref
                    self.anomalies.append((channel, ref, text))
                    break  # other lengths at this position share the same prefix
        return None

    def anomaly_summary(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for channel, digits, text in self.anomalies:
            entry = out.setdefault(digits, {"channel": channel, "count": 0, "example": text})
            entry["count"] += 1
        return out
