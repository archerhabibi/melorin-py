# Audit report — AI-03 Database & Finance

(Structure follows section 7 of the execution plan.)

## 1. Executive summary
- Status: first fix package pushed (DB-001..DB-003, all Low, no reachable money loss found). Ledger reconciliation, CHECK constraints and a real same-key order-creation concurrency test follow in this PR.
- Base: stacked on `audit/02-security` (`2ab7d15`). Date: 2026-11-23.

## 2. Reviewed
- `kernel/models/{wallet,vpn,orders,payments}.py`, `alembic/versions/0001_initial_baseline.py`, `core/uow.py`, `domain/{ledger,commission,debt,currency}.py`, `modules/wallet/service.py`, `modules/orders/service/refund.py`, `modules/payments/{service,provisional}.py` (refund + provisional revoke), `modules/catalog/service.py` (coupon quota), `modules/loyalty/earning.py` (reversal).
- The migrated PostgreSQL schema (83 tables) queried through `pg_catalog`.
- Out of scope: provider adapters (AI-04), worker jobs (AI-06).

## 3. Method
- `alembic upgrade head`, `alembic check`, `alembic downgrade base`, `alembic upgrade head` on an empty PostgreSQL 16 database.
- Previously skipped tests run for real: `tests/postgres/test_migration_baseline.py` (2 passed with `TEST_PG_ADMIN_URL`), `tests/service/test_wallet_properties_db.py` (hypothesis, 1 passed, 66 s).
- SQL survey of the schema: foreign keys without a leading index (43), money-like 32-bit integer columns (none), timestamp types (216 `timestamptz`, 0 naive), tables without a primary key (0), CHECK constraints (1).
- Usage scan: for each unindexed foreign key, how often the code filters or joins on it.
- Measurement: 400 000 `vpn_accounts` rows over 40 panels on PostgreSQL 16 (2 vCPU test server), query plan before and after the index.
- Limits: no production data; plans depend on data distribution; no real payment provider was contacted.

## 4. Findings
### DB-001 — Queried foreign keys without an index
- Severity: Low. Status: Fixed.
- File / symbol: `kernel/models/vpn.py: VpnAccount.panel_id`, `orders.py: Order.vpn_account_id`, `payments.py: Payment.receipt_file_id`.
- Evidence: 43 foreign-key columns have no index that starts with them. Most are audit columns that are never filtered on. Three are: `VpnAccount.panel_id` (23 call sites: allocation routing, worker overdue job, health, reconcile, panel operations), `Order.vpn_account_id` (renewals, returns) and `Payment.receipt_file_id` (bank-SMS matching, provisional receipts).
- Reproduction: per-panel list `WHERE panel_id = :p AND status IN (...) AND archived_at IS NULL` on 400 000 accounts / 40 panels: sequential scan, 124 ms; with `(panel_id, status)`: bitmap index scan, 5.1 ms.
- Impact: latency of panel sync/reconcile queries grows linearly with the number of accounts. No effect at today's size.
- Root cause: `index=True` was applied to the other `vpn_accounts` foreign keys (`user_id`, `store_id`, `order_id`, `server_id`) but not to `panel_id`.
- Fix: `ix_vpn_accounts_panel_id_status`, `ix_orders_vpn_account_id`, `ix_payments_receipt_file_id` in the models and the baseline.
- Regression test: `tests/contracts/test_db_guards_contract.py`; `alembic check` reports zero differences (`tests/postgres/test_migration_baseline.py`).
- Dependencies: none.

### DB-002 — Ledger append-only rule was only a convention
- Severity: Low. Status: Fixed.
- File / symbol: `alembic/versions/0001_initial_baseline.py: _APPEND_ONLY_TABLES`.
- Evidence: `wallet/service.py` documents an "append-only" ledger, but only `account_link_audits` had the database guard. No application code updates or deletes `ledger_entries` or `ledger_transactions` (searched `modules`, `worker`, `scripts`, `alembic`; retention purges only outbox and webhook rows).
- Impact: a manual SQL statement or a future code path could rewrite history and break `wallets.balance` against the ledger without any error.
- Fix: the existing append-only trigger (PostgreSQL and SQLite) now covers `ledger_entries` and `ledger_transactions`.
- Regression test: `tests/postgres/test_migration_baseline.py::test_ledger_history_cannot_be_rewritten_and_a_transaction_is_reversed_once` (UPDATE and DELETE are refused after a real `alembic upgrade head`).
- Dependencies: none.

### DB-003 — A ledger transaction could be reversed twice under different keys
- Severity: Low (no reachable path found today). Status: Fixed.
- File / symbol: `modules/wallet/service.py: reverse`, `kernel/models/wallet.py: LedgerTransaction.reverses_id`.
- Evidence: `reverse()` is idempotent only on the caller's key, and reversals post with `min_balance=None`. The same top-up transaction `payment:<id>` can be reversed by the gateway refund path (`finalize_refund`, key `_refund_key`) and by the provisional-receipt revoke (`payment:<id>:provisional_revoke`). Today the payment status checks keep the two apart; nothing in the database did.
- Reproduction: credit 1 000, `reverse(tx, key="a")`, `reverse(tx, key="b")`: the wallet ends at -1 000. The new tests fail on the old code (2 failed).
- Impact: double debit of a customer wallet or a negative balance if two paths ever race on one payment.
- Fix: `reverse()` returns the existing reversal when the transaction was already reversed, and a partial unique index `uq_ledger_transactions_reverses_id` enforces it under concurrency (the loser of a race returns the winner's reversal).
- Regression test: `tests/service/test_wallet_reversal_once.py` (3 tests), `tests/postgres/test_postgres_concurrency.py::test_parallel_reversals_of_one_transaction_under_different_keys_reverse_it_once`.
- Dependencies: AI-01 (`modules/orders`) and AI-04 (`modules/payments`) callers are unchanged.

### Checked and not a defect
- Money columns are `BigInteger`; no float arithmetic in `domain/{ledger,commission,pricing}.py` (`debt.state` uses a float ratio for a display state only).
- Every write to `Wallet.balance` goes through `wallet.post`, which locks wallets in a fixed order and applies the lowest-allowed-balance rule.
- Coupon quota is taken with `SELECT ... FOR UPDATE` on the coupon row; refunds release it under the same lock.
- Refund of a gateway payment is a durable three-step operation with a lease and a `manual_review` state; the ledger reversal is keyed.
- `alembic upgrade/check/downgrade/upgrade` and the two previously skipped suites pass.

## 5. Changes
- `kernel/models/{vpn,orders,payments,wallet}.py`, `alembic/versions/0001_initial_baseline.py` (single baseline edited, as allowed by the owner decision of 2026-11-22), `modules/wallet/service.py`.
- Tests: `tests/service/test_wallet_reversal_once.py`, `tests/contracts/test_db_guards_contract.py`, additions to `tests/postgres/test_postgres_concurrency.py` and `tests/postgres/test_migration_baseline.py`.

## 6. Test results
| Command | Result | Notes |
|---|---|---|
| `alembic upgrade head`, `alembic check`, `downgrade base`, `upgrade head` | PASS | zero differences; 83 tables |
| `pytest tests/service/test_wallet_reversal_once.py tests/postgres/test_postgres_concurrency.py tests/postgres/test_migration_baseline.py tests/contracts/test_finance_ledger_contract.py` (PostgreSQL) | PASS | 11 passed |
| same new tests on the code of `audit/02-security` | FAIL (expected) | 2 failed, 1 passed |
| `ruff check`, `ruff format --check`, `mypy` (391 files) | PASS | |
| `gen_docs --check`, `gen_api_client --check` | PASS | |
| CI `quality`, `postgres-lane`, `web-e2e` | see PR | |

## 7. Residual risks
- The reversal rule is enforced per ledger transaction; it does not decide whether a payment may be refunded after a provisional revoke (status checks in `modules/payments` remain the policy).
- Triggers are created by the migration only; the SQLite and `create_all` test schemas do not have them (same as `account_link_audits`).

## 8. Needs a human decision
- DB-003 changes `wallet.reverse` semantics: a second reversal of the same transaction now returns the first one instead of posting. Confirm that no flow needs two reversals of one transaction (none found).

## 9. Pull request
- Branch `audit/03-database-finance`, base `audit/02-security`.
