# AI-05 — Frontend audit (in progress)

Base: audit/04-integrations at 6e5f745f61d09915f9528ccd0e967cd5ff544222.
Scope so far: browser-facing headers, storefront recovery, wallet and customer order retries.

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

## FE-006 — uncertain orders become inaccessible when the customer state changes

Severity: Medium. Status: Fixed. Parent: `audit/05-frontend-fe001` at `b2b00991`.

The durable key added in FE-004 is not enough when the customer cannot reach the retry action. After a lost response, the original payment may leave the wallet without enough funds for a new quote, or a renewal may make the account ineligible for another renewal. The checkout and renewal screens then hide or disable the only retry, leaving the earlier outcome unresolved.

The orders screen now lists pending purchases for the current store and account. Pending renewals remain visible even if the account is no longer eligible. Each recovery action submits the original payload and key without requiring a fresh quote; a stale action is refused if another tab has already resolved it. The Core still decides whether an uncommitted order can be created and its current price.

Regression evidence: the recovery tests failed on the parent when the retry buttons were absent. The new unit tests cover account and store isolation and stale actions; browser tests cover both changed-balance purchase and ineligible-renewal recovery after reload.

## Customer order retry invariants

For a store, signed-in customer and exact request payload, every unresolved retry uses the same key. A late response must not erase a newer key, and a stale recovery action must never start a new order. If coordination or storage fails, no order is sent. Purchase and renewal recovery remains reachable without relying on a fresh quote.

The order request helper alone creates and conditionally clears the stored key; browser transactions serialize changes across tabs. Recovery views only read the attempt and submit its expected key. Reseller, loyalty and wallet-topup paths are outside this invariant and remain under review.

| Event | No pending key | Pending key | Confirmed or stale recovery |
|---|---|---|---|
| Start or retry same payload | Create a key before sending | Reuse that key | A fresh intentional order creates a new key |
| Different payload | Create its own key | Keep the existing key and scope the other payload separately | A stale recovery cannot create a new key |
| Network loss, non-2xx, invalid success body | No request if storage failed | Retain the key for the same customer and payload | Never clear a newer key |
| Valid success | No change unless it matches the sent key | Clear only the matching key | A delayed response cannot clear another attempt |
| Storage or coordination unavailable | Refuse to send | Refuse to send | Refuse to send |

## Verification

- FE-001: five policy and real Nginx response tests passed.
- FE-002: all 89 storefront tests passed before FE-003, including the recovery action and application entry point; lint, typecheck, format check and build also passed.
- FE-003: all 12 wallet/ticket tests passed; storefront lint, typecheck and format check passed.
- FE-004: six order/renewal unit tests, all 98 storefront tests, lint, typecheck and build passed. The browser suite passed 25 tests, including retry after reload; two staging-only tests were skipped.
- FE-005: all 100 storefront tests, lint, typecheck, format check and build passed. The full browser suite passed 26 tests including real two-tab coordination; two staging-only tests were skipped.
- FE-006: 104 storefront tests, lint, typecheck, format check and build passed. Three browser scenarios passed, including both recovery cases and overlapping tabs.
- Admin web: 361 tests, lint, typecheck, format check and build passed.
- Before FE-004: Playwright browser suite passed 24 tests; two staging-only tests were skipped.

Backend make lint and make test passed on the FE-001 tree: 2,921 tests passed and 19 were skipped. FE-002 through FE-006 only change frontend code and audit documentation. A fresh backend make lint and make test also passed on the FE-006 tree: 2,921 tests passed and 19 were skipped. The frontend audit continues separately; no claim is made here that all frontend paths have been reviewed.
