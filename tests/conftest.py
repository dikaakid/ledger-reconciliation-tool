from datetime import date

import pandas as pd
import pytest

from ledger_recon.config import ReconConfig
from ledger_recon.core import build_line_per_line
from ledger_recon.loaders import filter_window, load_ledger, load_statement

S_COLS = ["txn_id", "account_no", "posted_at", "description", "direction", "amount"]
L_COLS = ["ledger_id", "reference", "amount", "created_at", "status", "username"]

REF = "8800112345678901"  # 16 digits, prefix 88001 -> account 0100000001
REF2 = "8800312345678901"  # prefix 88003 -> account 0100000002
DAY = date(2026, 1, 5)


@pytest.fixture
def cfg():
    return ReconConfig()


@pytest.fixture
def run(cfg):
    """Load both sides from tuples and return the Line Per Line frame."""

    def _run(statement_rows, ledger_rows, d=DAY):
        st, _, _, _ = load_statement(pd.DataFrame(statement_rows, columns=S_COLS), cfg)
        led, _, _ = load_ledger(pd.DataFrame(ledger_rows, columns=L_COLS), cfg)
        led, _ = filter_window(led, d, d)
        return build_line_per_line(st, led, d, cfg)

    return _run


def bank(txn, when, ref=REF, amount=100000, account="0100000001", direction="CR", desc=None):
    return (txn, account, when, desc or f"TRF {ref} FROM CUSTOMER", direction, amount)


def led(lid, when, ref=REF, amount=100000, status="SUCCESS", user="merchant_1"):
    return (lid, ref, amount, when, status, user)
