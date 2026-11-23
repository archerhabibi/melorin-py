# AI-05 — Frontend audit (in progress)

Base: audit/04-integrations at 6e5f745f61d09915f9528ccd0e967cd5ff544222.
Scope so far: browser-facing headers in the store and admin Nginx configurations, the bundled Caddy proxy, and the external-proxy deployment.

## FE-001 — browser protections depend on which proxy is used

Severity: Medium. Status: Fixed; further frontend audit in progress.

When an operator uses the external-proxy deployment, the two web containers did not supply the Content-Security-Policy or Cross-Origin-Opener-Policy provided by the bundled Caddy proxy. Separately, an Nginx add_header inside /assets/ suppressed inheritance of the server-level security headers for asset responses.

Both web servers now emit the same CSP and opener policy as Caddy. Asset caching is configured without suppressing inherited security headers. Regression checks compare the policies and exercise real Nginx responses for pages, assets, and error paths when MELORIN_TEST_NGINX_IMAGE is set.

## FE-002 — storefront can become blank after a rendering exception

Severity: Medium. Status: Fixed.

A rendering error could unmount the entire storefront with no way for the customer to recover. The application now has a top-level error boundary with an accessible reload action. The message asks the customer to check payment status without claiming that every in-flight operation is automatically preserved. The boundary does not handle event-handler or asynchronous exceptions.

## FE-003 — wallet retry state is shared by different customers in the same browser

Severity: High. Status: Fixed.

The frontend stored a topup attempt using only the store ID, while the backend identifies an idempotent payment by both user and store. A second customer using the same browser could be blocked by, or overwrite, another customer's unresolved attempt. That can prevent safe recovery of the original request.

The storage key now includes the signed-in account ID and store ID. The action is disabled until a valid account identity is available, and the wallet view remounts if the account changes. Tests reproduce the original cross-account failure, check independent retry keys, and exercise the dashboard wiring.

Legacy per-store-only browser entries cannot be reliably assigned to an account and are not reused; any test payment already in flight under the old key must be reconciled before retrying.

## FE-004 — purchases and renewals use a fresh key after an uncertain response

Severity: High. Status: Fixed.

Purchase and renewal requests generated a new idempotency key on every click. If Core committed an order but the response was lost, retrying after a reload could create a second order and wallet debit. A browser test reproduced the key change on the original code.

The frontend now persists the request key before sending, scoped to the signed-in account, store, and exact order payload, and keeps it through ambiguous outcomes. A confirmed order clears the key so a later intentional purchase can proceed. If identity or safe browser storage is unavailable, no order is sent. The same mechanism covers the customer purchase and renewal flows.

Orders already submitted by the old frontend had no durable key; check order history before retrying an unresolved pre-fix purchase or renewal. Reseller and loyalty retry paths remain under review.

## FE-005 — concurrent tabs can duplicate an order or lose a newer retry key

Severity: High. Status: Fixed for customer purchase and renewal requests.

Two tabs could both see no pending order key and create different keys; a late response could also delete a newer attempt's key. Browser localStorage operations alone do not make the read-modify-write sequence atomic.

A short IndexedDB transaction now serializes key creation and conditional removal across tabs. A delayed success only clears the key it actually used. If browser storage or cross-tab coordination is unavailable, the request is not sent. Existing pending localStorage keys remain usable. Reseller, loyalty and wallet topup flows still need their own concurrency review.

## Verification

- FE-001: five policy and real Nginx response tests passed.
- FE-002: all 89 storefront tests passed before FE-003, including the recovery action and application entry point; lint, typecheck, format check and build also passed.
- FE-003: all 12 wallet/ticket tests passed; storefront lint, typecheck and format check passed.
- FE-004: six order/renewal unit tests, all 98 storefront tests, lint, typecheck and build passed. The browser suite passed 25 tests, including retry after reload; two staging-only tests were skipped.
- FE-005: all 100 storefront tests, a real-browser two-tab coordination test, lint, typecheck, format check and build passed. The full browser suite is running.
- Admin web: 361 tests, lint, typecheck, format check and build passed.
- Before FE-004: Playwright browser suite passed 24 tests; two staging-only tests were skipped.

Backend make lint and make test passed on the FE-001 tree: 2,921 tests passed and 19 were skipped. FE-002 through FE-005 only change frontend code and audit documentation. The frontend audit continues separately; no claim is made here that all frontend paths have been reviewed.
