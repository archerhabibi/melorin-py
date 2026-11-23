# Audit report — AI-04 Integrations

(Structure follows section 7 of the execution plan.)

## 1. Executive summary
- Status: first pass over mail, storage, payment adapters, bank-SMS ingestion, receipt OCR and outgoing webhooks done. 1 finding confirmed and fixed (INT-001, Medium). Panel adapters and the remaining bank-SMS code are still to review (follow-up commits on this branch).
- Base: stacked on `audit/03-database-finance` (`4537ca7`). Date: 2026-11-23.

## 2. Reviewed
- `core/{email,storage,http}.py`, `modules/payments/adapters/{zarinpal,manual_card,base,registry}.py`, `modules/payments/bank_sms/{authentication,ingestion}.py`, `modules/payments/receipt_ocr.py`, `modules/webhooks/service.py`, `domain/{webhook,netpolicy}.py`.
- Not reviewed yet: `modules/panel_integrations/**` (sanaei, pasarguard, upstream_bot), `bank_sms/{matching,review,reconciliation}`, `domain/bank_sms.py`.
- Out of scope: payment ledger and refund state (AI-03), worker scheduling (AI-06), secrets handling in CI (AI-07).

## 3. Method
- Pattern sweep of the integration paths: TLS verification switched off, redirects, subprocess/eval/pickle, non-constant-time secret comparisons, secrets in log calls. No hit except the item below.
- Source reading of the files listed in section 2.
- Reproduction of INT-001 on Python 3.12.3 (test server): `ssl._create_stdlib_context is ssl._create_unverified_context` is `True`; the context it returns has `verify_mode == CERT_NONE` and `check_hostname == False`; both `smtplib.SMTP.starttls` and `smtplib.SMTP_SSL.__init__` call it when they get no context.
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

### Checked and not a defect
- Every outbound call in scope goes through `outbound_client` (bounded timeout, redirects off, per-purpose metrics); no `verify=False` in the scope. The Pasarguard ops client reads `verify` from the panel config: reviewed with the panel adapters.
- Webhook SSRF: static URL rules, numeric host spellings, resolve once, every address checked (CGNAT, NAT64, 6to4, Teredo, IPv4-mapped), connection to the validated address with the real SNI and `Host`.
- Webhook signature: HMAC-SHA256 over `timestamp.body`, 300 s window, constant-time comparison. Rows left in `delivering` by a crashed worker are reclaimed by the lease in `worker/runner.py`.
- Bank SMS: token stored as a hash, constant-time comparison, one generic 401, idempotent on `(store, fingerprint)` with an `IntegrityError` fallback, other accounts' SMS ignored.
- Zarinpal: a callback without an `Authority` never reaches `verify.json`; the echoed amount is compared; code 101 (already verified) is accepted so a repeated callback is harmless.

## 5. Changes
- `core/email.py` (INT-001); new `tests/unit/test_email_tls.py`.

## 6. Test results
| Command | Result | Notes |
|---|---|---|
| `pytest tests/unit/test_email_tls.py` before the fix | FAIL | 4 failed, 2 passed (untrusted certificate and wrong host name accepted) |
| `pytest tests/unit/test_email_tls.py tests/unit/test_optional_integrations.py tests/http/test_admin_team_http.py` after the fix | PASS | 38 passed |
| `ruff check`, `ruff format --check` (671 files), `mypy` (391 files) | PASS | |
| CI `quality`, `postgres-lane`, `web-e2e` | see PR | |

## 7. Residual risks
- Provider contracts (Zarinpal refund endpoint, Sanaei, Pasarguard, Telethon flow) are checked against the code only, never against a live or sandbox peer.
- `ZarinpalAdapter.query_payment_status` returns the local status: a payment whose callback never arrives stays pending until someone acts. To be assessed in the next pass.
- Receipt OCR runs `tesseract` under a time limit but with no memory or pixel-count limit.

## 8. Needs a human decision
- Does any deployment use an SMTP server with a self-signed certificate? It will be refused from now on; the answer decides whether the operator documentation needs a trust-store recipe.

## 9. Pull request
- Branch `audit/04-integrations`, base `audit/03-database-finance`.
