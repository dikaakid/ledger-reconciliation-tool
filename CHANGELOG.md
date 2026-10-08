# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-10-08

### Added
- Exact-length, prefix-validated reference extraction from free-text bank descriptions.
- Composite-key matching on `(reference, amount, occurrence index)`.
- Whole-group ambiguity flag, time-proximity match quality, routing check, username pre-fill.
- Incomplete-statement guard with `--force` override.
- Cumulative unreconciled tracker: `YYYY-MM` sheets, idempotent updates, validated + backed-up +
  atomic writes, consumed-ID registry, bounded recheck.
- JSON configuration for patterns, prefix routing, thresholds and column renames.
- `run` (batch) and `pair` (single day) CLI commands.
- Synthetic sample data and generator; 41 tests; GitHub Actions CI; ruff lint.

### Changed
- Amounts are compared as integer minor units instead of floats.
- Input is read as text: leading zeros survive, whitespace/case are normalised.
- Rows with unparseable timestamps/amounts are rejected and reported instead of silently coerced.

## [0.1.0]

### Added
- Initial generic ledger-to-ledger reconciliation prototype.
