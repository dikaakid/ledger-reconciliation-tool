import pandas as pd
import pytest
from conftest import L_COLS, REF, S_COLS, bank, led

from ledger_recon.config import ReconConfig
from ledger_recon.loaders import load_ledger, load_statement


def test_leading_zeros_in_account_numbers_survive_csv_roundtrip(tmp_path, cfg):
    path = tmp_path / "s.csv"
    pd.DataFrame([bank("B1", "2026-01-05 10:00:00")], columns=S_COLS).to_csv(path, index=False)
    valid, *_ = load_statement(path, cfg)
    assert valid.loc[0, "account_no"] == "0100000001"


def test_text_is_stripped_and_normalised(cfg):
    valid, *_ = load_ledger(
        pd.DataFrame([led("L1", "2026-01-05 10:00:00", ref=f"  {REF} ", status=" success ")], columns=L_COLS),
        cfg,
    )
    assert valid.loc[0, "reference"] == REF


def test_amounts_become_integer_minor_units_without_float_error(cfg):
    rows = [led("L1", "2026-01-05 10:00:00", amount=0.1 + 0.2), led("L2", "2026-01-05 10:00:00", amount=0.3)]
    valid, *_ = load_ledger(pd.DataFrame(rows, columns=L_COLS), cfg)
    assert valid["amount_minor"].tolist() == [30, 30]


def test_unparseable_rows_are_rejected_not_coerced(cfg):
    rows = [
        bank("B1", "garbage"),
        bank("B2", "2026-01-05 10:00:00", amount="abc"),
        bank("B3", "2026-01-05 10:00:00", direction="XX"),
        bank("B4", "2026-01-05 10:00:00"),
    ]
    valid, rejected, *_ = load_statement(pd.DataFrame(rows, columns=S_COLS), cfg)
    assert valid["txn_id"].tolist() == ["B4"]
    assert set(rejected["reject_reason"]) == {
        "invalid posted_at",
        "invalid amount",
        "invalid direction (expected CR or DB)",
    }


def test_duplicate_ids_are_rejected(cfg):
    rows = [led("L1", "2026-01-05 10:00:00"), led("L1", "2026-01-05 11:00:00")]
    valid, rejected, _ = load_ledger(pd.DataFrame(rows, columns=L_COLS), cfg)
    assert len(valid) == 1 and rejected["reject_reason"].tolist() == ["duplicate ledger_id"]


def test_non_success_ledger_rows_are_excluded_and_counted(cfg):
    rows = [led("L1", "2026-01-05 10:00:00"), led("L2", "2026-01-05 10:00:00", status="FAILED")]
    valid, _, meta = load_ledger(pd.DataFrame(rows, columns=L_COLS), cfg)
    assert valid["ledger_id"].tolist() == ["L1"] and meta["non_success_rows"] == 1


def test_placeholder_statement_rows_are_removed_and_counted(cfg):
    rows = [bank("B1", "2026-01-05 00:00:00", amount=None, desc="No transaction found")]
    valid, rejected, meta, _ = load_statement(pd.DataFrame(rows, columns=S_COLS), cfg)
    assert valid.empty and rejected.empty and meta["placeholder_rows"] == 1


def test_missing_columns_raise_clear_error(cfg):
    with pytest.raises(ValueError, match="statement is missing required columns"):
        load_statement(pd.DataFrame({"txn_id": ["B1"]}), cfg)


def test_column_rename_via_config():
    cfg = ReconConfig(
        ledger_columns={
            "id": "ledger_id",
            "ref": "reference",
            "amt": "amount",
            "ts": "created_at",
            "state": "status",
        }
    )
    df = pd.DataFrame(
        [("L1", REF, 5, "2026-01-05 10:00:00", "SUCCESS")], columns=["id", "ref", "amt", "ts", "state"]
    )
    valid, *_ = load_ledger(df, cfg)
    assert valid.loc[0, "ledger_id"] == "L1"
