"""
Loading and validation.

Rules that fix the classic silent-corruption problems:
  * every column is read as TEXT first (no lost leading zeros in account numbers);
  * text is stripped and case-normalised (no false breaks from "ACC-1 " vs "ACC-1");
  * amounts become integer minor units (no float-equality surprises);
  * rows with an unparseable timestamp/amount are REJECTED and reported, never
    silently coerced into NaT/NaN and matched anyway.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from .config import ReconConfig
from .reference import ReferenceExtractor

STATEMENT_REQUIRED = ["txn_id", "account_no", "posted_at", "description", "direction", "amount"]
LEDGER_REQUIRED = ["ledger_id", "reference", "amount", "created_at", "status"]


def _read(src, rename: dict, side: str, required: list[str]) -> pd.DataFrame:
    if isinstance(src, pd.DataFrame):
        df = src.copy()
    else:
        df = pd.read_csv(src, dtype=str, keep_default_na=False, na_values=[""])
    if rename:
        df = df.rename(columns=rename)
    missing = set(required) - set(df.columns)
    if missing:
        raise ValueError(
            f"{side} is missing required columns: {sorted(missing)}. Expected: {sorted(required)}."
        )
    df = df.astype("string")
    for col in df.columns:
        df[col] = df[col].str.strip()
    return df


def _flagger(index):
    reason = pd.Series("", index=index, dtype="object")

    def flag(mask, text):
        mask = pd.Series(mask, index=index).fillna(False).astype(bool)
        reason.loc[mask & (reason == "")] = text

    return reason, flag


def _to_minor(amount: pd.Series, decimals: int) -> pd.Series:
    return (amount * (10**decimals)).round().astype("int64")


def _object(series: pd.Series) -> pd.Series:
    return series.astype(object).where(series.notna(), None)


def load_statement(src, cfg: ReconConfig):
    """Return (valid_df, rejected_df, meta, extractor) for a bank statement."""
    df = _read(src, cfg.statement_columns, "statement", STATEMENT_REQUIRED)

    placeholder = df["description"].str.lower() == cfg.placeholder_text.lower()
    meta = {"placeholder_rows": int(placeholder.fillna(False).sum())}
    df = df[~placeholder.fillna(False)].reset_index(drop=True)

    df["account_no"] = df["account_no"].str.upper()
    df["direction"] = df["direction"].str.upper()
    posted = pd.to_datetime(df["posted_at"], errors="coerce", format="ISO8601")
    amount = pd.to_numeric(df["amount"], errors="coerce")

    reason, flag = _flagger(df.index)
    flag(df["txn_id"].isna(), "missing txn_id")
    flag(posted.isna(), "invalid posted_at")
    flag(amount.isna(), "invalid amount")
    flag(~df["direction"].isin(["CR", "DB"]), "invalid direction (expected CR or DB)")
    flag(df["txn_id"].duplicated(keep="first") & df["txn_id"].notna(), "duplicate txn_id")

    ok = reason == ""
    rejected = df[~ok].copy()
    rejected["reject_reason"] = reason[~ok]

    valid = df[ok].copy().reset_index(drop=True)
    valid["posted_at"] = posted[ok].reset_index(drop=True)
    valid["posted_date"] = valid["posted_at"].dt.date
    valid["amount_minor"] = _to_minor(amount[ok].reset_index(drop=True), cfg.amount_decimals)
    valid["amount"] = valid["amount_minor"] / (10**cfg.amount_decimals)

    extractor = ReferenceExtractor(cfg)
    valid["reference"] = valid["description"].apply(extractor.extract)
    for col in ["txn_id", "account_no", "description", "direction"]:
        valid[col] = _object(valid[col])
    valid["reference"] = _object(valid["reference"])
    return valid, rejected, meta, extractor


def load_ledger(src, cfg: ReconConfig):
    """Return (valid_df, rejected_df, meta) for an internal ledger export."""
    df = _read(src, cfg.ledger_columns, "ledger", LEDGER_REQUIRED)
    if "username" not in df.columns:
        df["username"] = pd.NA

    df["reference"] = df["reference"].str.upper()
    df["status"] = df["status"].str.upper()
    created = pd.to_datetime(df["created_at"], errors="coerce", format="ISO8601")
    amount = pd.to_numeric(df["amount"], errors="coerce")

    reason, flag = _flagger(df.index)
    flag(df["ledger_id"].isna(), "missing ledger_id")
    flag(df["reference"].isna(), "missing reference")
    flag(created.isna(), "invalid created_at")
    flag(amount.isna(), "invalid amount")
    flag(df["ledger_id"].duplicated(keep="first") & df["ledger_id"].notna(), "duplicate ledger_id")

    ok = reason == ""
    rejected = df[~ok].copy()
    rejected["reject_reason"] = reason[~ok]

    valid = df[ok].copy().reset_index(drop=True)
    valid["created_at"] = created[ok].reset_index(drop=True)
    valid["ledger_date"] = valid["created_at"].dt.date
    valid["amount_minor"] = _to_minor(amount[ok].reset_index(drop=True), cfg.amount_decimals)
    valid["amount"] = valid["amount_minor"] / (10**cfg.amount_decimals)

    is_success = valid["status"] == cfg.ledger_success_status.upper()
    meta = {"non_success_rows": int((~is_success).sum())}
    valid = valid[is_success].reset_index(drop=True)
    for col in ["ledger_id", "reference", "status", "username"]:
        valid[col] = _object(valid[col])
    return valid, rejected, meta


def filter_window(ledger: pd.DataFrame, start: date, end: date):
    """Keep only ledger rows inside [start, end]. Returns (kept, dropped_count)."""
    inside = (ledger["ledger_date"] >= start) & (ledger["ledger_date"] <= end)
    return ledger[inside].reset_index(drop=True), int((~inside).sum())
