import shutil
from pathlib import Path

import pandas as pd
import pytest

from ledger_recon.cli import main
from ledger_recon.config import ReconConfig
from ledger_recon.pipeline import run_batch

SAMPLE = Path(__file__).resolve().parents[1] / "examples" / "dummy_data"


@pytest.fixture
def data(tmp_path):
    d = tmp_path / "data"
    shutil.copytree(SAMPLE, d)
    return d


def test_batch_on_sample_data_matches_documented_numbers(data, tmp_path):
    out = tmp_path / "out"
    result = run_batch(data, out, ReconConfig(), log=lambda *_: None)
    day1 = result["days"][pd.Timestamp("2026-01-05").date()]
    assert day1 == {
        "total_rows": 70,
        "recon": 62,
        "unrecon": 8,
        "bank_only": 5,
        "ledger_only": 3,
        "ambiguous_rows": 4,
        "wrong_routing": 1,
        "weak_matches": 2,
        "rejected_rows": 3,
    }
    assert not (out / "recon_2026-01-07.xlsx").exists()  # incomplete statement skipped
    assert result["recheck"]["resolved"] == 2  # cross-midnight pair closed


def test_second_run_skips_finished_dates_and_force_overrides_guard(data, tmp_path):
    out = tmp_path / "out"
    run_batch(data, out, ReconConfig(), log=lambda *_: None)
    again = run_batch(data, out, ReconConfig(), log=lambda *_: None)
    assert again["days"] == {}
    forced = run_batch(data, out, ReconConfig(), force=["2026-01-07"], log=lambda *_: None)
    assert (out / "recon_2026-01-07.xlsx").exists() and len(forced["days"]) == 1


def test_report_contains_all_sheets(data, tmp_path):
    run_batch(data, tmp_path / "out", ReconConfig(), log=lambda *_: None)
    names = pd.ExcelFile(tmp_path / "out" / "recon_2026-01-05.xlsx").sheet_names
    assert names == [
        "Statement Raw",
        "Ledger Raw",
        "Line Per Line",
        "Non-Reference Rows",
        "Rejected Rows",
        "Summary",
        "Pivot per Account",
    ]


def test_cli_pair_mode(data, tmp_path, capsys):
    code = main(
        [
            "pair",
            str(data / "statement_2026-01-05.csv"),
            str(data / "ledger_2026-01-05_2026-01-06.csv"),
            "--date",
            "2026-01-05",
            "-o",
            str(tmp_path / "r.xlsx"),
        ]
    )
    assert code == 0 and (tmp_path / "r.xlsx").exists() and "recon" in capsys.readouterr().out


def test_config_json_rejects_unknown_keys(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"nope": 1}')
    with pytest.raises(ValueError, match="Unknown config keys"):
        ReconConfig.from_json(p)
