# Architecture

## Problem

A bank statement and an internal ledger describe the same payments but share no unique identifier.
Discrepancies must be found by comparing what both sides *do* record: a payment reference, an
amount, and a timestamp.

## Pipeline

    statement_*.csv ─┐                                     ┌─> recon_YYYY-MM-DD.xlsx
                     ├─> loaders ─> core (match) ─> report ┤
    ledger_*.csv ────┘     │            │                 └─> tracker (open items, recheck)
                       rejected     guards/flags

| Module | Responsibility |
|---|---|
| `config.py` | All provider-specific knowledge (patterns, prefixes, thresholds, column maps) |
| `reference.py` | Extract and validate the payment reference from free text |
| `loaders.py` | Read as text, normalise, convert amounts, reject bad rows |
| `core.py` | Composite-key matching, labels, routing, ambiguity, confidence |
| `tracker.py` | Cumulative open-items workbook with safe writes and recheck |
| `report.py` | Excel assembly and styling |
| `pipeline.py` | File discovery, idempotent daily batch, guards |
| `cli.py` | `run` and `pair` commands |

## Key decisions

**1. Exact-length reference extraction.** Candidate lengths are tried one after another
(`16 → 15 → 14`), each as `\d{n}` with an exact `n`. A range such as `\d{14,20}` is greedy: when other
digits are glued directly behind a real reference, it consumes them and silently returns a wrong
reference. Exact lengths can never take more than `n` digits. Each candidate must also start with a
known prefix, otherwise it is logged as an anomaly and the row counts as "no reference" - so unrelated
digit runs are never reconciled as if they were payments.

**2. Composite key with occurrence index.** Rows are sorted by `(reference, amount, time)` and numbered
within each `(reference, amount)` group. Joining on `(reference, amount, occurrence)` pairs repeated
identical payments one-to-one in a reproducible way. Non-key columns are prefixed (`bank_*`,
`ledger_*`) **before** the merge, so generic column names such as `id` can never collide or be silently
overwritten.

**3. Ambiguity flags the whole group.** The index pairing is only trustworthy when both sides hold the
same number of rows for a group. When the counts differ and both sides are non-empty, the pairing can
shift by one position for *every* row in the group - including rows that came out as `Recon`. So the
flag is set on the entire group. (A group present on one side only is not ambiguous: it is simply
unmatched.)

**4. Same-day window.** Ledger rows are restricted to the target date (`ledger_window_days = 0`), and
ledger-only rows must belong to that date. This keeps the reconciliation auditable: a match never
silently spans days. Payments that cross midnight show up as open items and are closed later by the
recheck.

**5. Strict loading.** All columns are read as text (leading zeros survive), trimmed and
case-normalised; amounts become integer minor units (no float noise); rows with an unparseable
timestamp/amount/direction, missing or duplicate ids are *rejected and reported*, not coerced.

**6. Incomplete-statement guard.** If the ledger is active but the statement contains no referenced
credits (typical for an intraday or placeholder download), the day is skipped. Reconciling it would
create hundreds of false breaks that could end up in a dispute.

**7. Tracker safety.** The tracker is validated before any daily file is produced; every write goes to a
temp file, is validated, the previous tracker is backed up, and the swap is atomic. Re-running a date is
idempotent. Sheets are named `YYYY-MM`. A registry of consumed ledger ids prevents one ledger row from
resolving two bank rows.

**8. Bounded recheck.** A pending bank row may only resolve against a ledger row dated 0 to
`recheck_max_days` later. Without the bound, a January item could be "resolved" by an unrelated March
row that happens to share reference and amount. When a pair is resolved, the ledger-only twin row is
closed in the same pass so one transaction is never left half-open.

## Confidence

For `Recon` rows the absolute time gap between the paired rows is labelled `Strong` (≤ 1 min),
`Moderate` (≤ 10 min) or `Weak` (> 10 min). Weak pairs stay matched but are counted in the summary so
a reviewer can prioritise them.
