# Ledger Reconciliation Tool

[![CI](https://github.com/dikaakid/ledger-reconciliation-tool/actions/workflows/ci.yml/badge.svg)](https://github.com/dikaakid/ledger-reconciliation-tool/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.12%20%7C%203.13-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/lint-ruff-261230)](https://docs.astral.sh/ruff/)

Reconcile a **bank statement** against an **internal ledger** when the two systems share **no common
unique transaction ID**, and get an Excel report a finance team can act on the same day.

## The problem

Two systems record the same payments. They were built independently, so there is no shared key to
join on. The only thing both sides agree on is *what* was paid: a payment reference, an amount, and
roughly *when*. Naive joins on those fields break as soon as the same customer pays the same amount
twice, a reference is glued to other digits, or a text field carries a stray space.

## What it does

| Capability | How |
|---|---|
| Matches repeated identical payments one-to-one | Composite key `(reference, amount, occurrence index)` with chronological tie-breaking |
| Extracts references from free-text bank descriptions | Exact-length, prefix-validated patterns (never a greedy range that swallows glued digits) |
| Warns when pairing cannot be trusted | If a reference+amount group has a different row count on each side, the **whole group** is flagged, including rows marked `Recon` |
| Scores every match | `Strong` (<= 1 min), `Moderate` (<= 10 min), `Weak` (> 10 min) by time gap |
| Catches mis-routed money | The reference prefix defines the account it must land in |
| Refuses bad input quietly passing as good | Unparseable dates/amounts are **rejected and reported**, never coerced; leading zeros in account numbers survive; text is trimmed and case-normalised; amounts are compared as integer minor units |
| Protects you from half-downloaded statements | A day whose statement has no referenced credits while the ledger is busy is skipped unless `--force`d |
| Keeps a cumulative tracker of open items | Month sheets (`YYYY-MM`), idempotent re-runs, validated + backed-up + atomic writes, and a **recheck** that resolves late-arriving ledger rows |

## Quickstart

    pip install -r requirements.txt
    python -m ledger_recon.cli run --data-dir examples/dummy_data --output-dir output

(or `pip install -e .` and use the `ledger-recon` command). The sample data under
`examples/dummy_data/` is fully synthetic and can be regenerated with
`python examples/generate_sample_data.py`.

Expected output on the sample data (verified by `tests/test_pipeline.py`):

    === Processing 2026-01-05 ===
      Line Per Line: 70 rows | Recon 62 | Unrecon 8 | ambiguous 4 | wrong routing 1 | weak matches 2
    === Processing 2026-01-06 ===
      Line Per Line: 70 rows | Recon 62 | Unrecon 8 | ambiguous 4 | wrong routing 1 | weak matches 2
    === Processing 2026-01-07 ===
      [SKIPPED - STATEMENT LOOKS INCOMPLETE] 2026-01-07
    === Recheck === resolved rows moved: 2 | still pending: 14

See [docs/SAMPLE_OUTPUT.md](docs/SAMPLE_OUTPUT.md) for real excerpts of the report (unreconciled rows, ambiguous group, weak matches, rejected rows, tracker).

One day only:

    python -m ledger_recon.cli pair examples/dummy_data/statement_2026-01-05.csv \
        examples/dummy_data/ledger_2026-01-05_2026-01-06.csv --date 2026-01-05 -o report.xlsx

## Input format

Files are discovered by name in `--data-dir`:

* `statement_YYYY-MM-DD.csv` - one file per day
* `ledger_YYYY-MM-DD.csv` or a bulk range `ledger_YYYY-MM-DD_YYYY-MM-DD.csv`

| Statement column | Meaning |
|---|---|
| `txn_id` | Unique id within the statement |
| `account_no` | Account the money landed in (kept as text) |
| `posted_at` | ISO-8601 timestamp |
| `description` | Free text the reference is extracted from |
| `direction` | `CR` or `DB` (only credits are matched) |
| `amount` | Numeric |

| Ledger column | Meaning |
|---|---|
| `ledger_id` | Unique id within the ledger |
| `reference` | Payment reference |
| `amount` | Numeric |
| `created_at` | ISO-8601 timestamp |
| `status` | Only `SUCCESS` rows (configurable) are reconciled |
| `username` | Optional; used to pre-fill the owner of unmatched bank rows |

If your files use other column names, map them in a JSON config (`statement_columns`,
`ledger_columns`) - see below.

## Configuration

Everything provider-specific lives in `ledger_recon/config.py` and can be overridden with
`--config my_config.json`: reference patterns and lengths, the prefix-to-account routing table,
the routing effective date, thresholds, the incomplete-statement placeholder text, the recheck
window, and column renames.

    {
      "candidate_lengths": [18, 17, 16],
      "prefix_to_account": {"12345": "0011223344"},
      "ledger_columns": {"trx_id": "ledger_id", "va": "reference"}
    }

## Output

`recon_YYYY-MM-DD.xlsx` per day with sheets: **Statement Raw**, **Ledger Raw**, **Line Per Line**
(the result; filter `Match?`, `case`, `Pairing_Ambiguous`, `Routing_Check`), **Non-Reference Rows**,
**Rejected Rows**, **Summary**, **Pivot per Account**. Plus one cumulative
`unreconciled_tracker.xlsx` (open items by month, `Resolved`, and a consumed-ID registry).

## Known limitations

* **Same-day window by design.** A payment that crosses midnight appears as unreconciled on its
  statement day and is closed by the tracker recheck (up to `recheck_max_days` later).
* **Pairing is by chronological order, not by optimal time assignment.** When group counts differ,
  the pairing may be off by one position; that is exactly why the whole group is flagged.
* **Exact amount match** (to the configured number of decimals). Fee- or FX-adjusted amounts need a
  tolerance-based approach, which this tool does not implement.
* **One currency per run.** Split files per currency.
* Rows with an unparseable date cannot be assigned to a day, so they are listed in the
  `Rejected Rows` sheet of every report that reads the same ledger file.

## Project structure

    ledger_recon/        engine: config, reference, loaders, core, tracker, report, pipeline, cli
    tests/               pytest suite (41 tests: extraction, loading, matching, tracker, end-to-end)
    examples/            synthetic sample data + generator
    docs/                ARCHITECTURE.md (design rationale), SAMPLE_OUTPUT.md (real output excerpts)
    .github/             CI workflow, issue and pull-request templates

## Development

    pip install -e ".[dev]"
    ruff format . && ruff check .
    pytest

The suite covers extraction, loading rules, matching, tracker safety and an end-to-end run on the
sample data. Each key rule was also mutation-checked (breaking the rule makes a test fail). CI runs
tests on Python 3.10, 3.12 and 3.13 on Linux and Windows, plus lint and a package build. See
[CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design rationale.

## License

MIT - see [LICENSE](LICENSE).
