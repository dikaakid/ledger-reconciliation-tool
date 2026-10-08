"""
Generate fully SYNTHETIC sample data for the demo.

Every account number, reference and amount below is fictional. The scenarios
are chosen so that each feature of the engine has something to show:

  normal matches, a high-frequency reference, glued trailing digits, weak time
  matches, wrong routing, an ambiguous group (4 bank vs 3 ledger), bank-only
  and ledger-only rows, an amount mismatch, non-reference rows, an unknown-prefix
  anomaly, rejected rows, failed ledger rows, a cross-midnight settlement, and
  an incomplete (placeholder) statement day.

Usage:  python examples/generate_sample_data.py
"""

from __future__ import annotations

import csv
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np

OUT = Path(__file__).parent / "dummy_data"
PREFIX_ACCOUNT = {
    "88001": "0100000001",
    "88002": "0100000001",
    "88003": "0100000002",
    "88004": "0100000003",
    "88005": "0100000002",
}
PREFIXES = list(PREFIX_ACCOUNT)
STATEMENT_COLS = ["txn_id", "account_no", "posted_at", "description", "direction", "amount"]
LEDGER_COLS = ["ledger_id", "reference", "amount", "created_at", "status", "username"]
FMT = "%Y-%m-%d %H:%M:%S"


class Day:
    def __init__(self, d: date, rng: np.random.Generator):
        self.d, self.rng = d, rng
        self.statement: list[dict] = []
        self.ledger: list[dict] = []
        self._used: set[str] = set()

    # -- helpers ---------------------------------------------------------
    def ref(self, prefix: str | None = None, length: int = 16) -> str:
        prefix = prefix or PREFIXES[int(self.rng.integers(0, len(PREFIXES)))]
        while True:
            digits = "".join(str(x) for x in self.rng.integers(0, 10, size=length - len(prefix)))
            r = prefix + digits
            if r not in self._used:
                self._used.add(r)
                return r

    def at(self, minutes: float) -> datetime:
        return datetime.combine(self.d, time(9, 0)) + timedelta(minutes=minutes)

    def desc(self, ref: str, channel: str, glue: str = "", lower: bool = False) -> str:
        n = len(self.statement) + 1
        text = {
            "TRF": f"TRF {ref} FROM CUSTOMER {n}",
            "REF": f"INCOMING REF{ref}{glue} MA:{n}",
            "LEADING": f"{ref}#PAYMENT FROM CUSTOMER {n}",
        }[channel]
        return text.lower() if lower else text

    def bank(self, ref, amount, when, channel="TRF", glue="", account=None, lower=False, desc=None):
        n = len(self.statement) + 1
        self.statement.append(
            {
                "txn_id": f"B{self.d:%m%d}-{n:04d}",
                "account_no": account or PREFIX_ACCOUNT[ref[:5]],
                "posted_at": when.strftime(FMT),
                "description": desc if desc is not None else self.desc(ref, channel, glue, lower),
                "direction": "CR",
                "amount": amount,
            }
        )

    def led(self, ref, amount, when, username="merchant_1", status="SUCCESS", created=None):
        n = len(self.ledger) + 1
        self.ledger.append(
            {
                "ledger_id": f"L{self.d:%m%d}-{n:04d}",
                "reference": ref,
                "amount": amount,
                "created_at": created if created is not None else when.strftime(FMT),
                "status": status,
                "username": username,
            }
        )

    def pair(self, ref, amount, minutes, delay_s=20, **kw):
        when = self.at(minutes)
        username = kw.pop("username", f"merchant_{int(ref[-2:]) % 7}")
        ref_cell = kw.pop("ledger_ref", ref)
        self.bank(ref, amount, when, **kw)
        self.led(ref_cell, amount, when + timedelta(seconds=delay_s), username=username)


def build_day(d: date, rng, cross_midnight_out: bool = False) -> Day:
    day = Day(d, rng)
    channels = ["TRF", "REF", "LEADING"]

    for i in range(40):  # 1. normal matches
        length = 15 if i % 10 == 0 else 14 if i % 17 == 0 else 16
        ref = day.ref(length=length)
        amount = int(rng.integers(10, 500)) * 1000
        day.pair(
            ref, amount, i * 3, delay_s=int(rng.integers(5, 50)) if i % 13 else 240, channel=channels[i % 3]
        )

    hf = day.ref("88002")  # 2. high-frequency reference
    for i in range(12):
        day.pair(hf, int(rng.choice([10000, 20000, 50000])), 130 + i * 2, delay_s=10)

    for _ in range(3):  # 3. digits glued behind the reference
        day.pair(day.ref(), int(rng.integers(5, 90)) * 1000, 170 + _, channel="REF", glue="424242")

    for k in range(2):  # 4. weak time match (25 min apart)
        day.pair(day.ref(), 33000 + k * 1000, 180 + k, delay_s=1500)

    day.pair(day.ref("88001"), 480000, 190, account="0100000003")  # 5. wrong routing

    a = day.ref("88003")  # 6. ambiguous group: 4 bank vs 3 ledger
    for k in range(4):
        day.bank(a, 250000, day.at(200 + k * 10))
    for k in range(3):
        day.led(a, 250000, day.at(200 + k * 10) + timedelta(seconds=10), username="merchant_3")

    for k in range(2):  # 7. bank-only (waiting for ledger)
        day.bank(day.ref(), 77000 + k * 1000, day.at(240 + k))

    r = day.ref("88004")  # 8. amount mismatch
    day.bank(r, 150000, day.at(250), channel="REF")
    day.led(r, 155000, day.at(250) + timedelta(seconds=15), username="merchant_5")

    for k in range(2):  # 9. ledger-only
        day.led(day.ref(), 64000 + k * 1000, day.at(260 + k), username="merchant_2")

    day.statement.append(
        {
            "txn_id": f"B{d:%m%d}-A001",
            "account_no": "0100000001",  # 10. non-reference rows
            "posted_at": day.at(5).strftime(FMT),
            "description": "MONTHLY ADMIN FEE",
            "direction": "DB",
            "amount": 15000,
        }
    )
    day.statement.append(
        {
            "txn_id": f"B{d:%m%d}-A002",
            "account_no": "0100000001",
            "posted_at": day.at(6).strftime(FMT),
            "description": "INTEREST CREDIT",
            "direction": "CR",
            "amount": 1200,
        }
    )
    day.statement.append(
        {
            "txn_id": f"B{d:%m%d}-A003",
            "account_no": "0100000002",  # unknown prefix
            "posted_at": day.at(7).strftime(FMT),
            "description": "TRF9999900000000001 FROM UNKNOWN",
            "direction": "CR",
            "amount": 7000,
        }
    )

    for k in range(2):  # 11. failed ledger rows (excluded)
        day.led(day.ref(), 12000, day.at(270 + k), status="FAILED")

    day.statement.append(
        {
            "txn_id": f"B{d:%m%d}-R001",
            "account_no": "0100000001",  # 12. rejected rows
            "posted_at": day.at(8).strftime(FMT),
            "description": "TRF 88001000000000999 BAD",
            "direction": "CR",
            "amount": "abc",
        }
    )
    day.led(day.ref(), 9000, day.at(280), created="not-a-date")

    ws_ref = day.ref()  # 13. lower-case statement text + padded ledger reference
    day.pair(ws_ref, 56000, 285, lower=True)
    day.ledger[-1]["reference"] = f"  {ws_ref} "

    if cross_midnight_out:  # 14. settles across midnight
        q = day.ref()
        when = datetime.combine(d, time(23, 59, 30))
        day.bank(q, 91000, when)
        day.cross = (q, 91000, datetime.combine(d + timedelta(days=1), time(0, 0, 20)))
    return day


def write_csv(path: Path, cols: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.csv"):
        old.unlink()
    rng = np.random.default_rng(2026)
    d1, d2, d3 = date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)

    day1 = build_day(d1, rng, cross_midnight_out=True)
    day2 = build_day(d2, rng)
    q, amount, when = day1.cross
    day2.led(q, amount, when, username="merchant_4")  # the other half of the cross-midnight payment

    write_csv(OUT / "statement_2026-01-05.csv", STATEMENT_COLS, day1.statement)
    write_csv(OUT / "statement_2026-01-06.csv", STATEMENT_COLS, day2.statement)
    write_csv(OUT / "ledger_2026-01-05_2026-01-06.csv", LEDGER_COLS, day1.ledger + day2.ledger)

    day3 = Day(d3, rng)  # incomplete statement day
    for acct in ("0100000001", "0100000002"):
        day3.statement.append(
            {
                "txn_id": f"B0107-P{acct[-1]}",
                "account_no": acct,
                "posted_at": day3.at(0).strftime(FMT),
                "description": "No transaction found",
                "direction": "CR",
                "amount": "",
            }
        )
    for i in range(30):
        day3.led(day3.ref(), 10000 + i * 500, day3.at(i * 5))
    write_csv(OUT / "statement_2026-01-07.csv", STATEMENT_COLS, day3.statement)
    write_csv(OUT / "ledger_2026-01-07.csv", LEDGER_COLS, day3.ledger)
    print(f"Sample data written to {OUT}")


if __name__ == "__main__":
    main()
