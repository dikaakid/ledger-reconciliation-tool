# Sample output

Everything below is produced from the **synthetic** data in `examples/dummy_data/` by:

    python -m ledger_recon.cli run --data-dir examples/dummy_data --output-dir output

Figures are for `2026-01-05`. The full workbook (`recon_2026-01-05.xlsx`) has seven sheets; the
tables here are excerpts from them.

## Summary sheet

| metric | value |
|---|---|
| total_rows | 70 |
| recon | 62 |
| unrecon | 8 |
| bank_only | 5 |
| ledger_only | 3 |
| ambiguous_rows | 4 |
| wrong_routing | 1 |
| weak_matches | 2 |
| rejected_rows | 3 |
| statement_placeholder_rows | 0 |

## Unreconciled rows (`Match?` = `Unrecon`)

Each row carries a `case` that says *why* it is open. The bank-only row for the 250000 group
shows pairing ambiguity (4 bank rows against 3 ledger rows); the 150000/155000 pair is an amount
mismatch, and its bank-side row received the username from same-day reference history.

| reference | amount | bank_txn_id | ledger_id | ledger_username | case |
|---|---|---|---|---|---|
| 8800183843883356 | 77000 | B0105-0063 |  |  | WAITING_LEDGER |
| 8800339765173374 | 250000 | B0105-0062 |  | merchant_3 | BANK 4x vs LEDGER 3x \| username auto-filled from same-day reference history |
| 8800375525167717 | 64000 |  | L0105-0063 | merchant_2 | LEDGER SUCCESS WITHOUT BANK CREDIT (ledger 1x, bank 0x) - MANUAL REVIEW |
| 8800378488948999 | 78000 | B0105-0064 |  |  | WAITING_LEDGER |
| 8800394101443622 | 91000 | B0105-0071 |  |  | WAITING_LEDGER |
| 8800410644026623 | 65000 |  | L0105-0064 | merchant_2 | LEDGER SUCCESS WITHOUT BANK CREDIT (ledger 1x, bank 0x) - MANUAL REVIEW |
| 8800439498116277 | 150000 | B0105-0065 |  | merchant_5 | WAITING_LEDGER \| username auto-filled from same-day reference history |
| 8800439498116277 | 155000 |  | L0105-0062 | merchant_5 | LEDGER SUCCESS WITHOUT BANK CREDIT (ledger 1x, bank 0x) - MANUAL REVIEW |

## Ambiguous group (every row in it is flagged, including the `Recon` ones)

| reference | amount | bank_txn_id | ledger_id | Match? |
|---|---|---|---|---|
| 8800339765173374 | 250000 | B0105-0059 | L0105-0059 | Recon |
| 8800339765173374 | 250000 | B0105-0060 | L0105-0060 | Recon |
| 8800339765173374 | 250000 | B0105-0061 | L0105-0061 | Recon |
| 8800339765173374 | 250000 | B0105-0062 |  | Unrecon |

## Weak time matches (matched, but 25 minutes apart)

| reference | amount | Time_Gap_Minutes | Match_Quality |
|---|---|---|---|
| 8800230553940031 | 33000 | 25 | Weak - MANUAL CHECK REQUIRED |
| 8800589548681103 | 34000 | 25 | Weak - MANUAL CHECK REQUIRED |

## Mis-routed payment

| reference | bank_account_no | Routing_Check |
|---|---|---|
| 8800175501038782 | 0100000003 | WRONG ROUTING (expected 0100000001) |

## Rejected rows (never silently coerced)

| source | reject_reason |
|---|---|
| statement | invalid amount |
| ledger | invalid created_at |
| ledger | invalid created_at |

## Tracker after the full run

Open items live in month sheets named `YYYY-MM`; a late-arriving ledger row closed the
cross-midnight payment (`Resolved`), and `Consumed_Ledger_IDs` stops one ledger row from
resolving two bank rows.

| sheet | rows |
|---|---|
| 2026-01 | 14 |
| Resolved | 2 |
| Consumed_Ledger_IDs | 125 |
