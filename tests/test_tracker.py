import pandas as pd
import pytest
from conftest import REF

from ledger_recon.config import ReconConfig
from ledger_recon.tracker import (
    SHEET_CONSUMED,
    SHEET_RESOLVED,
    ensure_tracker_valid,
    recheck_tracker,
    record_consumed_ids,
    update_tracker,
)


def row(bank_id=None, ledger_id=None, ref=REF, amount_minor=10000000, bank_at=None, ledger_at=None):
    return {
        "reference": ref,
        "amount_minor": amount_minor,
        "bank_txn_id": bank_id,
        "ledger_id": ledger_id,
        "bank_posted_at": bank_at,
        "ledger_created_at": ledger_at,
        "Match?": "Unrecon",
    }


def pool(*items):
    """items: (ledger_id, created_at string)"""
    df = pd.DataFrame(
        [
            {"ledger_id": i, "reference": REF, "amount_minor": 10000000, "created_at": pd.Timestamp(t)}
            for i, t in items
        ]
    )
    df["ledger_date"] = df["created_at"].dt.date
    return df


def sheets(path):
    return pd.read_excel(path, sheet_name=None, dtype=str)


def test_months_use_year_and_month_so_years_never_collide(tmp_path):
    p = tmp_path / "t.xlsx"
    update_tracker(
        pd.DataFrame([row("B1", bank_at="2026-01-05 10:00:00"), row("B2", bank_at="2027-01-05 10:00:00")]), p
    )
    assert set(sheets(p)) == {"2026-01", "2027-01"}


def test_update_is_idempotent(tmp_path):
    p = tmp_path / "t.xlsx"
    rows = pd.DataFrame([row("B1", bank_at="2026-01-05 10:00:00")])
    update_tracker(rows, p)
    update_tracker(rows, p)
    assert len(sheets(p)["2026-01"]) == 1


def test_previous_tracker_is_backed_up_on_rewrite(tmp_path):
    p = tmp_path / "t.xlsx"
    update_tracker(pd.DataFrame([row("B1", bank_at="2026-01-05 10:00:00")]), p)
    update_tracker(pd.DataFrame([row("B2", bank_at="2026-01-05 11:00:00")]), p)
    assert len(list((tmp_path / "tracker_backups").glob("t_*.xlsx"))) == 1


def test_corrupt_tracker_stops_the_run(tmp_path):
    p = tmp_path / "t.xlsx"
    p.write_bytes(b"not a zip")
    with pytest.raises(SystemExit):
        ensure_tracker_valid(p)


def test_recheck_resolves_within_window_and_closes_the_ledger_only_twin(tmp_path):
    p = tmp_path / "t.xlsx"
    update_tracker(
        pd.DataFrame(
            [row("B1", bank_at="2026-01-05 23:59:30"), row(ledger_id="L9", ledger_at="2026-01-06 00:00:20")]
        ),
        p,
    )
    out = recheck_tracker(p, pool(("L9", "2026-01-06 00:00:20")), ReconConfig())
    s = sheets(p)
    assert out == {"resolved": 2, "still_pending": 0}
    assert len(s[SHEET_RESOLVED]) == 2 and s["2026-01"].empty
    assert "L9" in s[SHEET_CONSUMED]["ledger_id"].tolist()


def test_recheck_never_resolves_against_a_row_from_weeks_later(tmp_path):
    p = tmp_path / "t.xlsx"
    update_tracker(pd.DataFrame([row("B1", bank_at="2026-01-05 10:00:00")]), p)
    out = recheck_tracker(p, pool(("L9", "2026-01-27 10:00:00")), ReconConfig())  # 22 days later
    assert out["resolved"] == 0 and len(sheets(p)["2026-01"]) == 1


def test_a_consumed_ledger_id_cannot_resolve_a_second_row(tmp_path):
    p = tmp_path / "t.xlsx"
    update_tracker(
        pd.DataFrame([row("B1", bank_at="2026-01-05 10:00:00"), row("B2", bank_at="2026-01-05 11:00:00")]), p
    )
    out = recheck_tracker(p, pool(("L9", "2026-01-05 12:00:00")), ReconConfig())
    assert out["resolved"] == 1 and out["still_pending"] == 1
    record_consumed_ids(["L9"], p)
    assert recheck_tracker(p, pool(("L9", "2026-01-05 12:00:00")), ReconConfig())["resolved"] == 0
