# Audit report — AI-04 Integrations

(Structure follows section 7 of the execution plan.)

## 1. Executive summary
- Status: first pass over mail, storage, payment adapters, bank-SMS ingestion, receipt OCR and outgoing webhooks done. 2 findings confirmed and fixed (INT-001 and INT-002, both Medium). Panel adapters and the remaining bank-SMS code are still to review (follow-up commits on this branch).
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

### Checked and not a defect
- Every outbound call in scope goes through `outbound_client` (bounded timeout, redirects off, per-purpose metrics); no `verify=False` in the scope. The Pasarguard ops client reads `verify` from the panel config: reviewed with the panel adapters.
- Webhook SSRF: static URL rules, numeric host spellings, resolve once, every address checked (CGNAT, NAT64, 6to4, Teredo, IPv4-mapped), connection to the validated address with the real SNI and `Host`.
- Webhook signature: HMAC-SHA256 over `timestamp.body`, 300 s window, constant-time comparison. Rows left in `delivering` by a crashed worker are reclaimed by the lease in `worker/runner.py`.
- Bank SMS: token stored as a hash, constant-time comparison, one generic 401, idempotent on `(store, fingerprint)` with an `IntegrityError` fallback, other accounts' SMS ignored.
- Zarinpal: a callback without an `Authority` never reaches `verify.json`; the echoed amount is compared; code 101 (already verified) is accepted so a repeated callback is harmless.

## 5. Changes
- `core/email.py` (INT-001); new `tests/unit/test_email_tls.py`.
- `modules/webhooks/service.py` (INT-002); `tests/service/test_webhooks_service_db.py` (test double moved from `post` to `stream`, 2 new tests).

## 6. Test results
| Command | Result | Notes |
|---|---|---|
| `pytest tests/unit/test_email_tls.py` before the fix | FAIL | 4 failed, 2 passed (untrusted certificate and wrong host name accepted) |
| `pytest tests/unit/test_email_tls.py tests/unit/test_optional_integrations.py tests/http/test_admin_team_http.py` after the fix | PASS | 38 passed |
| `ruff check`, `ruff format --check` (671 files), `mypy` (391 files) | PASS | |
| `pytest tests/service/test_webhooks_service_db.py -k 'never_read or never_answers'` before the INT-002 fix | FAIL | 2 failed: 64 MiB pulled from the body; the delivery never returned |
| `pytest tests/service/test_webhooks_service_db.py tests/service/test_worker_runner_db.py tests/http -k 'webhook or deliver or runner'` after the fix | PASS | 51 passed |
| `ruff check`, `mypy` (391 files) after INT-002 | PASS | |
| CI `quality`, `postgres-lane`, `web-e2e` | see PR | |

## 7. Residual risks
- Provider contracts (Zarinpal refund endpoint, Sanaei, Pasarguard, Telethon flow) are checked against the code only, never against a live or sandbox peer.
- `ZarinpalAdapter.query_payment_status` returns the local status: a payment whose callback never arrives stays pending until someone acts. To be assessed in the next pass.
- Receipt OCR runs `tesseract` under a time limit but with no memory or pixel-count limit.
- `poll_tick` shares one 8-slot gate between outbox events and webhook deliveries and waits for the slowest of them. With INT-002 a slow receiver holds a slot for at most 20 s; separate pools would remove the coupling. For AI-06 to verify.

## 8. Needs a human decision
- Does any deployment use an SMTP server with a self-signed certificate? It will be refused from now on; the answer decides whether the operator documentation needs a trust-store recipe.

## 9. Pull request
- Branch `audit/04-integrations`, base `audit/03-database-finance`.
