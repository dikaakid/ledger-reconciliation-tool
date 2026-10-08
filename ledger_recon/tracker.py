"""
Cumulative tracker of unreconciled items.

Safety properties:
  * the tracker is validated BEFORE any daily file is produced (fail fast);
  * every write goes to a temp file, is validated, the old tracker is backed up,
    and only then is it swapped in atomically (os.replace);
  * re-running a date is idempotent (rows are de-duplicated on a stable key);
  * sheets are named YYYY-MM so months of different years never collide;
  * a registry of already-consumed ledger ids prevents the same ledger row from
    resolving two different pending bank rows;
  * a pending bank row may only resolve against a ledger row at most
    `recheck_max_days` later -- never against an unrelated row from another month.
"""

from __future__ import annotations

import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .config import ReconConfig
from .report import style_workbook

TRACKER_NAME = "unreconciled_tracker.xlsx"
SHEET_RESOLVED = "Resolved"
SHEET_CONSUMED = "Consumed_Ledger_IDs"
RESERVED = {SHEET_RESOLVED, SHEET_CONSUMED}
COLORS = {SHEET_RESOLVED: "2E7D32", SHEET_CONSUMED: "7F7F7F"}
PENDING_COLOR = "C00000"


def is_valid_xlsx(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as z:
            return z.testzip() is None
    except Exception:
        return False


def ensure_tracker_valid(path: Path) -> None:
    if path.exists() and not is_valid_xlsx(path):
        raise SystemExit(f"[STOP] Tracker is corrupt: {path}. Restore a backup and re-run.")


def commit_tracker(tmp: Path, path: Path, keep: int = 10) -> None:
    if not is_valid_xlsx(tmp):
        raise RuntimeError(f"Temporary tracker invalid, original untouched: {tmp}")
    if path.exists() and is_valid_xlsx(path):
        backup_dir = path.parent / "tracker_backups"
        backup_dir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        shutil.copy2(path, backup_dir / f"{path.stem}_{stamp}.xlsx")
        for old in sorted(backup_dir.glob(f"{path.stem}_*.xlsx"))[:-keep]:
            old.unlink(missing_ok=True)
    try:
        os.replace(tmp, path)
    except PermissionError:
        raise PermissionError(f"Tracker is open in another program. Close it and re-run: {path}") from None


def _save(sheets: dict, path: Path, keep: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.xlsx")
    with pd.ExcelWriter(tmp, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name[:31], index=False)
    colors = {n: COLORS.get(n, PENDING_COLOR) for n in sheets}
    style_workbook(tmp, colors)
    commit_tracker(tmp, path, keep)


def _read(path: Path) -> dict:
    return pd.read_excel(path, sheet_name=None, dtype=str) if path.exists() else {}


def _key(df: pd.DataFrame) -> pd.Series:
    has_bank = df["bank_txn_id"].notna() & (df["bank_txn_id"].astype(str).str.strip() != "")
    return pd.Series(
        np.where(has_bank, "B_" + df["bank_txn_id"].astype(str), "L_" + df["ledger_id"].astype(str)),
        index=df.index,
    )


def _month(row) -> str:
    raw = row.get("bank_posted_at")
    if pd.isna(raw):
        raw = row.get("ledger_created_at")
    ts = pd.to_datetime(raw, errors="coerce")
    return "unknown" if pd.isna(ts) else ts.strftime("%Y-%m")


def update_tracker(new_rows: pd.DataFrame, path: Path, cfg: ReconConfig | None = None) -> None:
    """Add unreconciled rows per month sheet. Idempotent."""
    cfg = cfg or ReconConfig()
    if new_rows.empty:
        return
    new_rows = new_rows.copy()
    new_rows["_month"] = new_rows.apply(_month, axis=1)
    new_rows = new_rows.astype("string")

    existing = _read(path)
    reserved = {k: v for k, v in existing.items() if k in RESERVED}
    pending = {k: v for k, v in existing.items() if k not in RESERVED}

    for month in set(pending) | set(new_rows["_month"].dropna()):
        old = pending.get(month, pd.DataFrame())
        new = new_rows[new_rows["_month"] == month].drop(columns="_month")
        combined = pd.concat([old, new], ignore_index=True)
        combined["_key"] = _key(combined)
        combined = combined.drop_duplicates("_key", keep="last").drop(columns="_key")
        sort_col = "bank_posted_at" if "bank_posted_at" in combined.columns else combined.columns[0]
        pending[month] = combined.sort_values(sort_col, na_position="last").reset_index(drop=True)

    _save({**dict(sorted(pending.items())), **reserved}, path, cfg.tracker_backup_keep)


def record_consumed_ids(ids: list, path: Path, cfg: ReconConfig | None = None) -> None:
    cfg = cfg or ReconConfig()
    if not ids:
        return
    sheets = _read(path)
    current = sheets.get(SHEET_CONSUMED, pd.DataFrame(columns=["ledger_id"]))
    merged = pd.concat([current, pd.DataFrame({"ledger_id": [str(i) for i in ids]})], ignore_index=True)
    sheets[SHEET_CONSUMED] = merged.dropna().drop_duplicates().reset_index(drop=True)
    _save(sheets, path, cfg.tracker_backup_keep)


def recheck_tracker(path: Path, ledger_pool: pd.DataFrame, cfg: ReconConfig | None = None) -> dict:
    """Re-test pending bank rows against ledger rows that have arrived since.

    `ledger_pool` is the validated ledger (all dates currently available).
    Returns counts: {"resolved": n, "still_pending": n}.
    """
    cfg = cfg or ReconConfig()
    if not path.exists():
        return {"resolved": 0, "still_pending": 0}

    sheets = _read(path)
    resolved_old = sheets.pop(SHEET_RESOLVED, pd.DataFrame())
    consumed_df = sheets.pop(SHEET_CONSUMED, pd.DataFrame(columns=["ledger_id"]))
    consumed = set(consumed_df["ledger_id"].dropna().astype(str))

    pool: dict = {}
    usable = ledger_pool[~ledger_pool["ledger_id"].astype(str).isin(consumed)]
    for r in usable.sort_values("created_at").itertuples():
        pool.setdefault((r.reference, int(r.amount_minor)), []).append((str(r.ledger_id), r.ledger_date))

    now = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    new_consumed: list[str] = []
    resolved_frames: list[pd.DataFrame] = []
    pending_out: dict = {}

    # Pass 1: bank-side pending rows look for a ledger row.
    for month, df in sheets.items():
        df = df.copy()
        resolved_mask, via, status = [], [], []
        for _, row in df.iterrows():
            if pd.isna(row.get("bank_txn_id")) or str(row.get("bank_txn_id")).strip() == "":
                resolved_mask.append(False)
                via.append(None)
                status.append("Cannot be rechecked (ledger-only row, no statement entry)")
                continue
            bank_day = pd.to_datetime(row["bank_posted_at"], errors="coerce")
            key = (row.get("reference"), int(float(row["amount_minor"])))
            chosen = None
            for i, (_lid, ldate) in enumerate(pool.get(key, [])):
                gap = (pd.Timestamp(ldate).normalize() - bank_day.normalize()).days
                if 0 <= gap <= cfg.recheck_max_days:
                    chosen = pool[key].pop(i)
                    break
            if chosen:
                resolved_mask.append(True)
                via.append(chosen[0])
                status.append("Resolved")
                new_consumed.append(chosen[0])
            else:
                resolved_mask.append(False)
                via.append(None)
                status.append("Still pending")
        mask = pd.Series(resolved_mask, index=df.index)
        df["Recheck_Status"], df["Last_Rechecked"] = status, now
        if mask.any():
            res = df[mask].copy()
            res["Resolved_Ledger_ID"] = pd.Series(via, index=df.index)[mask]
            res["Resolved_At"] = now
            resolved_frames.append(res)
        pending_out[month] = df[~mask].reset_index(drop=True)

    # Pass 2: ledger-only pending rows whose ledger id was just consumed are the other half
    # of a pair resolved above -- resolve them too, so one transaction is never counted twice.
    consumed_now = set(new_consumed)
    for month, df in pending_out.items():
        if df.empty:
            continue
        is_ledger_only = df["bank_txn_id"].isna() & df["ledger_id"].astype(str).isin(consumed_now)
        if is_ledger_only.any():
            res = df[is_ledger_only].copy()
            res["Recheck_Status"], res["Resolved_Ledger_ID"] = "Resolved", res["ledger_id"]
            res["Resolved_At"] = now
            resolved_frames.append(res)
            pending_out[month] = df[~is_ledger_only].reset_index(drop=True)

    out = {m: d for m, d in sorted(pending_out.items())}
    out[SHEET_RESOLVED] = pd.concat([resolved_old] + resolved_frames, ignore_index=True)
    all_consumed = pd.concat([consumed_df, pd.DataFrame({"ledger_id": new_consumed})], ignore_index=True)
    out[SHEET_CONSUMED] = all_consumed.dropna().drop_duplicates().reset_index(drop=True)
    _save(out, path, cfg.tracker_backup_keep)

    return {
        "resolved": int(sum(len(f) for f in resolved_frames)),
        "still_pending": int(sum(len(d) for d in pending_out.values())),
    }
