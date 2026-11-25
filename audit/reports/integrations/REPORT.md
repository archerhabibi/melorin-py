# Audit report — AI-04 Integrations

(Structure follows section 7 of the execution plan.)

## 1. Executive summary
- Status: first pass over mail, storage, payment adapters, bank-SMS ingestion, receipt OCR and outgoing webhooks done. INT-001..INT-008 fixed, including receipt cleanup, OCR cancellation, upstream-bot purchase retries and lock handling. Remaining panel adapter paths and bank-SMS code are still to review (follow-up commits on this branch).
- Base: stacked on `audit/03-database-finance` (`4537ca7`). Date: 2026-11-23.

## 2. Reviewed
- `core/{email,storage,http}.py`, `modules/payments/adapters/{zarinpal,manual_card,base,registry}.py`, `modules/payments/bank_sms/{authentication,ingestion}.py`, `modules/payments/receipt_ocr.py`, `modules/webhooks/service.py`, `domain/{webhook,netpolicy}.py`.
- Not reviewed yet: `modules/panel_integrations/**` (sanaei, pasarguard, upstream_bot), `bank_sms/{matching,review,reconciliation}`, `domain/bank_sms.py`.
- Out of scope: payment ledger and refund state (AI-03), worker scheduling (AI-06), secrets handling in CI (AI-07).

## 3. Method
- Pattern sweep of the integration paths: TLS verification switched off, redirects, subprocess/eval/pickle, non-constant-time secret comparisons, secrets in log calls. No hit except the item below.
- Source reading of the files listed in section 2.
- Reproduction of INT-001 on Python 3.12.3 (test server): `ssl._create_stdlib_context is ssl._create_unverified_context` is `True`; the context it returns has `verify_mode == CERT_NONE` and `check_hostname == False`; both `smtplib.SMTP.starttls` and `smtplib.SMTP_SSL.__init__` call it when they get no context.
- Reproduction of INT-002 on the test server (`/work/audit-scan/webhook_body_probe.py`: a local peer that answers `200` and never finishes the body, driven through `outbound_client(..., timeout=10).post()`): a 200 MB body was buffered completely (no cap); a body that drips one byte every 2 s was still being waited for after 25 s although `timeout=10`, because that timeout restarts with every received byte.
- Limits: no real SMTP server, payment gateway, panel, S3 or Telegram was contacted (OBS-008); everything runs against local fakes.

## 4. Findings
### INT-001 — SMTP over TLS does not verify the server
- Severity: Medium. Status: Fixed.
- File / symbol: `core/email.py: _smtp_send` (`SMTP_SSL(...)` and `starttls()` without a context).
- Evidence: see section 3. A real TLS listener with a self-signed certificate was accepted by both modes, and so was a certificate that did not name the host that was dialled.
- Impact: anyone able to intercept the connection between the API and the SMTP host reads the SMTP user name and password (sent after the TLS step) and every message, including sign-in codes and links, and can alter them.
- Root cause: the stdlib default for a missing context is an unverified one; the code never passed one.
- Fix: `ssl.create_default_context()` is passed to `SMTP_SSL` and `starttls`. No new setting: a switch that turns verification off would bring the weakness back as a one-click option. A server with a private CA needs that CA in the system trust store of the API image (`SSL_CERT_FILE`).
- Regression test: `tests/unit/test_email_tls.py` (6 tests, real TLS sockets): an untrusted certificate is refused and nothing is sent; a trusted certificate for the right host delivers; a trusted certificate for another host name is refused. Run before the fix, 4 of the 6 failed with `DID NOT RAISE`.
- Dependencies: none.

### INT-002 — A webhook receiver can make the worker buffer its answer forever and hold a delivery slot
- Severity: Medium. Status: Fixed.
- File / symbol: `modules/webhooks/service.py: deliver_one` (`c.post(...)` on the tenant's URL), driven by `worker/arq_app.py: poll_tick`.
- Evidence: see section 3. `poll_tick` runs every 2 s and `gather`s the claimed outbox events together with up to 20 webhook deliveries behind one 8-slot gate; the job timeout is 120 s. The domain-verification fetch (`reseller/auto_verify.py: check_http`) already streams and caps its body for exactly this reason; the webhook path did not.
- Impact: a store owner who registers a URL on a server they control can make the shared worker allocate memory as fast as they can send (an out-of-memory kill takes every background job of every tenant with it), or keep deliveries, and the poll tick that waits for them, busy until the job timeout. Rows are leased and re-claimed, so nothing is lost, but it can be repeated with every retry and every test event.
- Root cause: `httpx` reads the whole body of `post()`, and its `timeout` bounds each read, not the exchange.
- Fix: the request is streamed and the body is never read (only the status decides the outcome); one `asyncio.timeout(DELIVERY_DEADLINE_SECONDS = 20)` covers the whole exchange and a timeout is an ordinary failed attempt with backoff (`no complete response within 20s`).
- After the fix (same probe, real sockets): a dripping body and a 200 MB flood both return `200` in 0.1 s with +3 MB / +5 MB peak memory; a peer that drips the response headers fails the attempt at 20.0 s.
- Regression tests: `tests/service/test_webhooks_service_db.py::test_the_response_body_of_a_receiver_is_never_read` (before the fix the client pulled all 64 MiB: `assert 67108864 == 0`) and `::test_a_receiver_that_never_answers_fails_the_attempt_within_the_deadline` (before the fix the delivery never returned). The test double `FakeClient` now offers `stream()` instead of `post()`; every existing assertion is unchanged.
- Dependencies: AI-06 owns `poll_tick` (section 7).

### INT-003 — OCR endpoint validation and connection could use different addresses
- Severity: Medium. Status: Fixed. Base: PR #185 at 30bafbb2702ef54125d2a13b888d442820eb98c3.
- File / symbol: `modules/payments/receipt_ocr.py`, `assert_public_endpoint` and `post_vision`.
- Evidence: the policy validated the DNS answer but the HTTP client subsequently received the hostname and performed its own lookup. Four new connection and TLS regressions failed on the parent; a mixed public/private DNS answer was already refused.
- Impact: a DNS change between validation and connection could evade the outbound address policy. Requests include the OCR provider credential and receipt image; normal TLS certificate verification still applies.
- Fix: validate every returned address, connect to a checked IPv4 or IPv6 address and preserve the provider hostname for HTTP Host, TLS SNI and certificate verification. Both the receipt reader and the admin connection test use this path.
- Regression: `tests/unit/test_receipt_ocr_pinning.py` checks IPv4, IPv6, mixed DNS answers and a real local TLS listener. A matching certificate succeeds; a certificate for another name is refused before any request is sent.
- Compatibility: if the selected validated address is unreachable, this OCR request fails instead of retrying another address; the existing manual-review fallback applies.

### INT-004 — PasarGuard reused sessions for different credentials
- Severity: Medium. Status: Fixed. Base: PR #187 at 4fe2e67117a05cd813a80733b91ac463e72c0897.
- File / symbol: `modules/panel_integrations/adapters/pasarguard/core.py`, password token cache.
- Evidence: with a cached session, two regression cases using changed or missing passwords did not fail; a static access-token request used a different cached token. All three failed on the parent and passed after the fix.
- Impact: a panel connection or a credential check could operate with a previous session's privileges rather than the supplied credentials.
- Fix: cache hits require a process-keyed fingerprint of the normalized password. A static access token bypasses the password cache. Cache entries contain neither the password nor an unsalted password hash; there remains at most one cached session per panel and username.
- Regression: `tests/adapters/test_pasarguard_adapter_contract.py` covers changed and missing passwords, the static-token collision and reuse of a matching password session across adapters.
- Compatibility: no API or schema change; a changed password requires a new panel login.

### INT-005 — Rejected receipt uploads leave stored files behind
- Severity: Medium. Status: Fixed. Base: PR #190 at `461f9f0d09aa52ff247fa36b8f7f78fe852924fb`.
- File / symbol: `modules/payments/router.py: upload_receipt`; `core/storage.py: LocalStorage`.
- Evidence: a receipt uploaded after its payment succeeds returns 409 but leaves an extra file; a failure before fingerprint persistence also leaves a file. Both HTTP regressions fail on the parent; a third safety test confirms there was no deletion API.
- Impact: repeated rejected uploads consume disk space without a database record or a normal way to locate the orphaned files.
- Root cause: receipt bytes are written before the database state is checked and there is no cleanup when the operation is rejected before commit.
- Fix: delete newly written objects for pre-commit preparation failures or explicit pre-commit payment-state rejection. Deletion cannot leave the storage root and is idempotent.
- Regression: HTTP tests exercise completed payments and fingerprint persistence errors; a storage test checks missing-file and path-traversal handling.
- Compatibility: storage implementations must provide `delete(key)`; no public API or schema change.

### INT-006 — Cancelled receipt OCR can leave a child process running
- Severity: Medium. Status: Fixed. Base: PR #191 at `6cf10635e165be2428b98172f68f2594da5fe526`.
- File / symbol: `modules/payments/receipt_ocr.py: _tesseract`.
- Evidence: with a real sleeping child, cancelling the OCR task left the process alive; the timeout path killed it but returned before it had been reaped. Both regression cases fail on the parent.
- Impact: cancellation releases the OCR concurrency slot while the Tesseract process can continue consuming resources; repeated cancellations can accumulate children.
- Root cause: only timeout was handled and the child was not awaited after termination.
- Fix: on cancellation, timeout or another error, terminate a still-running child, drain its pipes and await its exit before propagating the original error.
- Regression: `tests/unit/test_receipt_ocr_process.py` exercises cancellation and timeout using real local child processes, without a provider or Tesseract installation.
- Dependencies: AI-06 worker cancellation and AI-08 process tests; no API or schema change.

### INT-007 — An unanswered or concurrent upstream-bot purchase can be paid twice
- Severity: High. Status: Fixed on this branch. Base: PR #192 at `8eb1a4f5d0a33db1beee2c9bcacfe53b187b545a`.
- File / symbol: `modules/panel_integrations/adapters/upstream_bot/adapter.py: create_account, get_account, _recover`.
- Evidence: fake-provider regressions reproduce a second confirmation after a lost reply and after two overlapping attempts. Two more cases reproduce a missing account after waiting for a completed purchase and a charged confirmation timeout misclassified as transient.
- Impact: the upstream wallet may be charged twice for one Melorin account; a timed-out purchase can be provisioned with missing plan limits or an incorrect failure outcome.
- Root cause: a pending purchase with no delivery was treated as permission for a new purchase; the completed state was not rechecked after acquiring the chat lock. The pending record did not preserve plan metadata.
- Fix: recheck the state under the lock, recover a pending delivery or return UNKNOWN without another purchase, and preserve expiry and traffic. A failure after confirmation is UNKNOWN; account reads recheck state after waiting for the lock.
- Regression: `tests/adapters/test_upstream_bot_adapter.py` covers concurrent attempts, a charged but unanswered purchase, eventual delivery, a waiting account read and a confirmation timeout. The existing fake-provider suite remains green.
- Compatibility: an unconfirmed delivery blocks automatic repurchase until recovered or reconciled; no API or schema change. Redis failures and lock expiry remain separate risks to address.

### INT-008 — Upstream-bot chat locks can be bypassed, leaked or released for another owner
- Severity: High. Status: Fixed on this branch. Base: PR #193 at `c3c5abb0f61e224cd644a03a4e938a81b692179a`.
- File / symbol: `modules/panel_integrations/adapters/upstream_bot/state.py: _redis, _ChatLock`.
- Evidence: six tests failed before the fix: Redis-client or acquire failures allowed entry, cancellation leaked the local mutex, local contention raised an unclassified timeout, and GET/DEL could delete a replacement owner's lock.
- Impact: separate workers can interleave a paid bot conversation, or a cancelled request can block that worker indefinitely.
- Fix: Redis failures prevent entry when Redis is configured; acquisition and release clean up the local mutex on cancellation. A single Redis compare-and-delete script releases only the owner token. Busy local and Redis locks return retryable panel errors.
- Regression: `tests/unit/test_upstream_bot_lock.py` and the existing upstream-bot suite pass; a real isolated Redis test checked contention, replacement ownership and normal release.
- Compatibility: Redis outages now stop bot flows rather than silently falling back to an uncoordinated local lock. A development configuration with no Redis can still use a process-local mutex; hosted environments require Redis.
- Remaining work: the lease can expire during a long flow, and mapping writes can still fall back to process memory; these need separate fixes.

### Checked and not a defect
- Every outbound call in scope goes through `outbound_client` (bounded timeout, redirects off, per-purpose metrics); no `verify=False` in the scope. The Pasarguard ops client reads `verify` from the panel config: reviewed with the panel adapters.
- Webhook SSRF: static URL rules, numeric host spellings, resolve once, every address checked (CGNAT, NAT64, 6to4, Teredo, IPv4-mapped), connection to the validated address with the real SNI and `Host`.
- Webhook signature: HMAC-SHA256 over `timestamp.body`, 300 s window, constant-time comparison. Rows left in `delivering` by a crashed worker are reclaimed by the lease in `worker/runner.py`.
- Bank SMS: token stored as a hash, constant-time comparison, one generic 401, idempotent on `(store, fingerprint)` with an `IntegrityError` fallback, other accounts' SMS ignored.
- Zarinpal: a callback without an `Authority` never reaches `verify.json`; the echoed amount is compared; code 101 (already verified) is accepted so a repeated callback is harmless.

## 5. Changes
- `core/email.py` (INT-001); new `tests/unit/test_email_tls.py`.
- `modules/webhooks/service.py` (INT-002); `tests/service/test_webhooks_service_db.py` (test double moved from `post` to `stream`, 2 new tests).

- `modules/payments/receipt_ocr.py` and `tests/unit/test_receipt_ocr_pinning.py` (INT-003).
- `modules/panel_integrations/adapters/pasarguard/core.py` and `tests/adapters/test_pasarguard_adapter_contract.py` (INT-004).
- `core/storage.py`, `modules/payments/router.py`, receipt HTTP and storage tests (INT-005).
- `modules/payments/receipt_ocr.py` and `tests/unit/test_receipt_ocr_process.py` (INT-006).
- `modules/panel_integrations/adapters/upstream_bot/adapter.py` and adapter tests (INT-007).
- `modules/panel_integrations/adapters/upstream_bot/state.py` and lock tests (INT-008).

## 6. Test results
| Command | Result | Notes |
|---|---|---|
| `pytest tests/unit/test_email_tls.py` before the fix | FAIL | 4 failed, 2 passed (untrusted certificate and wrong host name accepted) |
| `pytest tests/unit/test_email_tls.py tests/unit/test_optional_integrations.py tests/http/test_admin_team_http.py` after the fix | PASS | 38 passed |
| `ruff check`, `ruff format --check` (671 files), `mypy` (391 files) | PASS | |
| `pytest tests/service/test_webhooks_service_db.py -k 'never_read or never_answers'` before the INT-002 fix | FAIL | 2 failed: 64 MiB pulled from the body; the delivery never returned |
| `pytest tests/service/test_webhooks_service_db.py tests/service/test_worker_runner_db.py tests/http -k 'webhook or deliver or runner'` after the fix | PASS | 51 passed |
| `ruff check`, `mypy` (391 files) after INT-002 | PASS | |
| INT-003 focused OCR, endpoint-policy and TLS regressions | PASS | 44 passed; 4 of the new cases failed before the fix |
| INT-003 make lint and mypy | PASS | 8 import contracts; 391 source files type-checked |
| INT-004 focused adapter, capabilities, contract and service tests | PASS | 144 passed, 1 skipped; three new regression cases failed before the fix |
| INT-004 `make lint` | PASS | 8 import contracts; formatting and lint passed |
| INT-004 `make test` | PASS | 2,978 passed, 48 skipped |
| INT-005 regressions on parent | FAIL (expected) | two orphaned uploads; deletion API missing |
| INT-005 focused tests | PASS | 54 passed; 3 new regression cases passed |
| INT-005 lint | PASS | import contracts, Ruff and format |
| INT-005 mypy | PASS | 391 source files |
| INT-005 full suite before cleanup-error fix | FAIL | 1 hygiene failure, 2,987 passed, 54 skipped: the new broad exception exceeded the limit |
| INT-005 cleanup-error and hygiene regression | PASS | 5 passed; expected filesystem errors are logged and unexpected programming errors are not swallowed |
| INT-005 full suite after cleanup-error fix | PASS | 2,991 passed, 54 skipped |
| INT-006 cancellation and timeout regressions | PASS | 2 failed on the parent and pass on the fix |
| INT-006 `make lint` | PASS | import contracts, Ruff and format |
| INT-006 focused suite | PASS | 28 passed |
| INT-006 mypy | PASS | 391 source files |
| INT-006 full suite before base fix | FAIL | 1 inherited hygiene failure, 2,989 passed, 54 skipped |
| INT-006 full suite after base fix | RUNNING | see PR #192 |
| INT-007 fake-provider adapter suite | PASS | 33 passed; four new concurrency and failure regressions were reproduced before their respective fixes |
| INT-007 full suite | QUEUED | follows INT-006 full rerun |
| INT-008 lock and upstream-bot tests | PASS | 39 passed; all 6 new lock tests failed before the fix |
| INT-008 real Redis contention and release | PASS | isolated local Redis 7 container |
| INT-008 full suite | QUEUED | follows INT-007 full run |
| CI `quality`, `postgres-lane`, `web-e2e` | see PR | |

## 7. Residual risks
- Upstream-bot mapping writes can still fall back to process memory, and a chat lease can expire during a long flow; these paths need separate fixes.
- Cleanup failure is logged. Objects are retained when the database commit outcome is uncertain to avoid deleting a referenced file; a later orphan sweep remains useful.
- INT-003 connects to the first validated address; a provider with an unreachable first address can require manual review until a later attempt resolves differently.
- PasarGuard password sessions remain cached for up to 50 minutes. An external password change may need upstream token revocation or a process restart; upstream bearer-token validity depends on the panel.
- Provider contracts (Zarinpal refund endpoint, Sanaei, Pasarguard, Telethon flow) are checked against the code only, never against a live or sandbox peer.
- `ZarinpalAdapter.query_payment_status` returns the local status: a payment whose callback never arrives stays pending until someone acts. To be assessed in the next pass.
- Receipt OCR runs `tesseract` under a time limit but with no memory or pixel-count limit.
- `poll_tick` shares one 8-slot gate between outbox events and webhook deliveries and waits for the slowest of them. With INT-002 a slow receiver holds a slot for at most 20 s; separate pools would remove the coupling. For AI-06 to verify.

## 8. Needs a human decision
- Does any deployment use an SMTP server with a self-signed certificate? It will be refused from now on; the answer decides whether the operator documentation needs a trust-store recipe.

## 9. Pull request
- Branch `audit/04-integrations`, base `audit/03-database-finance`.
- INT-003 follow-up: branch `audit/20-ocr-endpoint-089a80a5`; parent PR #185.
- INT-004 follow-up: branch `audit/22-panel-integrations-089a80a5`; parent PR #187.
- INT-005 follow-up: branch `audit/25-receipt-cleanup-18ef6bf0`; parent PR #190.
- INT-006 follow-up: branch `audit/26-ocr-cancellation-18ef6bf0`; parent PR #191.
- INT-007 follow-up: branch `audit/27-upstream-purchase-18ef6bf0`; parent PR #192.
- INT-008 follow-up: branch `audit/28-upstream-lock-18ef6bf0`; parent PR #193.
