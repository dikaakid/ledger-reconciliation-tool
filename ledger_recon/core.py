"""
Core matching logic.

Statement credits and successful ledger rows are paired on a composite key:

    (reference, amount in minor units, occurrence index)

The occurrence index is the 1-based chronological position inside each
(reference, amount) group, so repeated identical payments pair one-to-one.
The pairing is only trustworthy when both sides hold the same number of rows
for the group; otherwise the WHOLE group is flagged for manual verification
(including rows labelled "Recon"), because a count mismatch can shift the
pairing by one position for every row in the group.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .config import ReconConfig

KEYS = ["reference", "amount_minor", "occurrence"]

OUTPUT_COLUMNS = (
    KEYS
    + [
        "amount",
        "bank_txn_id",
        "bank_account_no",
        "bank_posted_at",
        "bank_description",
        "ledger_id",
        "ledger_created_at",
        "ledger_username",
    ]
    + [
        "Match?",
        "case",
        "Time_Gap_Minutes",
        "Match_Quality",
        "Routing_Check",
        "Investigation_Hint",
        "Pairing_Ambiguous",
    ]
)


def statement_looks_incomplete(statement, ledger, target_date: date, meta: dict, cfg: ReconConfig):
    """The ledger shows activity but the statement has zero referenced credits.

    Typical cause: an intraday or placeholder statement was downloaded. Reconciling
    it would create hundreds of false breaks, so the date is skipped unless forced.
    """
    n_cr_ref = int(((statement["direction"] == "CR") & statement["reference"].notna()).sum())
    n_ledger = int((ledger["ledger_date"] == target_date).sum())
    reasons: list[str] = []
    if n_ledger > 0 and n_cr_ref == 0:
        reasons.append(f"ledger has {n_ledger} successful rows but the statement has 0 referenced credits")
        if meta.get("placeholder_rows"):
            reasons.append(
                f"statement contains {meta['placeholder_rows']} '{cfg.placeholder_text}' placeholder rows"
            )
    return bool(reasons), reasons


def build_line_per_line(
    statement: pd.DataFrame, ledger: pd.DataFrame, target_date: date, cfg: ReconConfig
) -> pd.DataFrame:
    cr = statement[(statement["direction"] == "CR") & statement["reference"].notna()].copy()
    cr = cr.sort_values(["reference", "amount_minor", "posted_at"], kind="stable").reset_index(drop=True)
    cr["occurrence"] = cr.groupby(["reference", "amount_minor"]).cumcount() + 1

    led = ledger.sort_values(["reference", "amount_minor", "created_at"], kind="stable").reset_index(
        drop=True
    )
    led["occurrence"] = led.groupby(["reference", "amount_minor"]).cumcount() + 1

    # Non-key columns are renamed BEFORE merging so generic names can never
    # collide or silently overwrite each other.
    bank_side = cr[KEYS + ["txn_id", "account_no", "posted_at", "posted_date", "description"]].rename(
        columns={
            "txn_id": "bank_txn_id",
            "account_no": "bank_account_no",
            "posted_at": "bank_posted_at",
            "posted_date": "bank_posted_date",
            "description": "bank_description",
        }
    )
    ledger_side = led[KEYS + ["ledger_id", "created_at", "ledger_date", "username"]].rename(
        columns={"created_at": "ledger_created_at", "username": "ledger_username"}
    )

    m = pd.merge(bank_side, ledger_side, on=KEYS, how="outer", indicator=True)

    # Scope: ledger-only rows must belong to the target date.
    keep = (m["_merge"] != "right_only") | (m["ledger_date"] == target_date)
    m = m.loc[keep.astype(bool)].reset_index(drop=True)

    # TRUE group sizes, taken before the merge (post-merge fills would understate them).
    bank_sizes = cr.groupby(["reference", "amount_minor"]).size().to_dict()
    ledger_sizes = led.groupby(["reference", "amount_minor"]).size().to_dict()
    pairs = list(zip(m["reference"], m["amount_minor"], strict=True))
    nb = [int(bank_sizes.get(k, 0)) for k in pairs]
    nl = [int(ledger_sizes.get(k, 0)) for k in pairs]
    side = m["_merge"].astype(str).tolist()

    m["amount"] = m["amount_minor"] / (10**cfg.amount_decimals)
    m["Match?"] = np.where(m["_merge"] == "both", "Recon", "Unrecon")

    def label(s, b_n, l_n):
        if s == "both":
            return None
        if s == "left_only":
            if l_n == 0:
                return "WAITING_LEDGER" if b_n == 1 else f"BANK {b_n}x, NOT FOUND IN LEDGER"
            return f"BANK {b_n}x vs LEDGER {l_n}x"
        return f"LEDGER SUCCESS WITHOUT BANK CREDIT (ledger {l_n}x, bank {b_n}x) - MANUAL REVIEW"

    cases = [label(s, b_n, l_n) for s, b_n, l_n in zip(side, nb, nl, strict=True)]

    # Time proximity of paired rows.
    bp = pd.to_datetime(m["bank_posted_at"], errors="coerce")
    lc = pd.to_datetime(m["ledger_created_at"], errors="coerce")
    gap = ((bp - lc).abs().dt.total_seconds() / 60).where(m["Match?"] == "Recon")
    m["Time_Gap_Minutes"] = gap.round(2)

    def quality(g):
        if pd.isna(g):
            return None
        if g <= cfg.strong_minutes:
            return "Strong"
        if g <= cfg.moderate_minutes:
            return "Moderate - manual check recommended"
        return "Weak - MANUAL CHECK REQUIRED"

    m["Match_Quality"] = [quality(g) for g in m["Time_Gap_Minutes"]]

    # Routing: the reference prefix says which account the money must land in.
    def routing(match, ref, acct, d):
        if match != "Recon" or pd.isna(acct) or d is None or pd.isna(d):
            return None
        if d < cfg.routing_effective_date:
            return None
        expected = cfg.prefix_to_account.get(str(ref)[: cfg.prefix_len])
        if expected is None:
            return None
        return "OK" if str(acct) == expected else f"WRONG ROUTING (expected {expected})"

    m["Routing_Check"] = [
        routing(a, r, c, d)
        for a, r, c, d in zip(
            m["Match?"], m["reference"], m["bank_account_no"], m["bank_posted_date"], strict=True
        )
    ]

    # Investigation hint by how often a reference is used on the day.
    freq = cr.groupby("reference").size().add(led.groupby("reference").size(), fill_value=0)

    def hint(ref):
        if ref is None or pd.isna(ref):
            return None
        n = int(freq.get(ref, 0))
        if n > cfg.high_frequency_threshold:
            return f"High-frequency reference (used {n}x): check the transaction-level history source"
        return f"Regular reference (used {n}x): check the reference registration source"

    m["Investigation_Hint"] = [hint(r) for r in m["reference"]]

    # Pairing ambiguity: both sides present but counts differ -> verify the WHOLE group.
    def ambiguity(b_n, l_n):
        if b_n and l_n and b_n != l_n:
            return (
                f"AMBIGUOUS: this reference+amount group is {b_n}x in bank vs {l_n}x in ledger. "
                f"Verify the whole group manually, including rows marked Recon."
            )
        return None

    m["Pairing_Ambiguous"] = [ambiguity(b_n, l_n) for b_n, l_n in zip(nb, nl, strict=True)]

    # Username auto-fill for bank-only rows, only when the reference maps to exactly one username.
    hist = (
        led.dropna(subset=["reference"])
        .groupby("reference")["username"]
        .apply(lambda s: sorted(s.dropna().unique().tolist()))
    )
    fills, notes = [], []
    for ref, s in zip(m["reference"], side, strict=True):
        if s != "left_only":
            fills.append(None)
            notes.append("")
            continue
        cands = hist.get(ref, [])
        if len(cands) == 1:
            fills.append(cands[0])
            notes.append(" | username auto-filled from same-day reference history")
        elif len(cands) > 1:
            fills.append(None)
            notes.append(f" | username NOT auto-filled: {len(cands)} different usernames, check manually")
        else:
            fills.append(None)
            notes.append("")
    current = m["ledger_username"].astype(object)
    m["ledger_username"] = [
        c if (c is not None and not pd.isna(c)) else f for c, f in zip(current, fills, strict=True)
    ]
    m["case"] = [((c or "") + n) or None for c, n in zip(cases, notes, strict=True)]

    return m[OUTPUT_COLUMNS]


def summarize(lpl: pd.DataFrame, rejected: int = 0) -> dict:
    unrecon = lpl["Match?"] == "Unrecon"
    has_bank = lpl["bank_txn_id"].notna()
    has_ledger = lpl["ledger_id"].notna()
    return {
        "total_rows": int(len(lpl)),
        "recon": int((lpl["Match?"] == "Recon").sum()),
        "unrecon": int(unrecon.sum()),
        "bank_only": int((unrecon & has_bank).sum()),
        "ledger_only": int((unrecon & has_ledger & ~has_bank).sum()),
        "ambiguous_rows": int(lpl["Pairing_Ambiguous"].notna().sum()),
        "wrong_routing": int(lpl["Routing_Check"].astype(str).str.startswith("WRONG").sum()),
        "weak_matches": int(lpl["Match_Quality"].astype(str).str.startswith("Weak").sum()),
        "rejected_rows": int(rejected),
    }
