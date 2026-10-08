"""
Command-line interface.

    ledger-recon run  --data-dir data --output-dir output [--config cfg.json] [--force 2026-01-07]
    ledger-recon pair statement.csv ledger.csv --date 2026-01-05 -o report.xlsx
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from .config import ReconConfig
from .pipeline import reconcile_day, run_batch
from .report import write_report


def _config(path) -> ReconConfig:
    return ReconConfig.from_json(path) if path else ReconConfig()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ledger-recon", description="Reconcile a bank statement against an internal ledger."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Process every unprocessed date found in a folder.")
    run.add_argument("--data-dir", type=Path, default=Path("data"))
    run.add_argument("--output-dir", type=Path, default=Path("output"))
    run.add_argument("--config", type=Path)
    run.add_argument(
        "--force",
        nargs="*",
        default=[],
        metavar="YYYY-MM-DD",
        help="Process these dates even if the statement looks incomplete.",
    )
    run.add_argument("--no-recheck", action="store_true", help="Skip the tracker recheck step.")

    pair = sub.add_parser("pair", help="Reconcile one statement file against one ledger file.")
    pair.add_argument("statement", type=Path)
    pair.add_argument("ledger", type=Path)
    pair.add_argument("--date", required=True, help="Target date, YYYY-MM-DD.")
    pair.add_argument("-o", "--output", type=Path, default=Path("reconciliation_report.xlsx"))
    pair.add_argument("--config", type=Path)
    pair.add_argument("--force", action="store_true")

    args = parser.parse_args(argv)
    cfg = _config(args.config)

    if args.command == "run":
        if not args.data_dir.exists():
            raise SystemExit(f"Data folder not found: {args.data_dir}")
        run_batch(args.data_dir, args.output_dir, cfg, force=args.force, recheck=not args.no_recheck)
        return 0

    for p in (args.statement, args.ledger):
        if not p.exists():
            raise SystemExit(f"File not found: {p}")
    res = reconcile_day(args.statement, [args.ledger], date.fromisoformat(args.date), cfg, args.force)
    if res is None:
        return 1
    write_report(res["sheets"], args.output)
    s = res["summary"]
    print("Reconciliation complete.")
    for key in (
        "total_rows",
        "recon",
        "unrecon",
        "bank_only",
        "ledger_only",
        "ambiguous_rows",
        "wrong_routing",
        "weak_matches",
        "rejected_rows",
    ):
        print(f"  {key:<15}: {s[key]}")
    print(f"Report written to: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
