# AI-05 — Frontend audit (in progress)

Base: audit/04-integrations at 6e5f745f61d09915f9528ccd0e967cd5ff544222.
Scope so far: browser security headers, storefront recovery, wallet topups, loyalty reward retries, and purchase and renewal retries. Reseller and remaining loyalty flows remain under review.

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

Orders already submitted by the old frontend had no durable key; check order history before retrying an unresolved pre-fix purchase or renewal. Reseller retry paths remain under review; loyalty reward retries are addressed by FE-008.

## FE-005 — concurrent tabs can duplicate an order or lose a newer retry key

Severity: High. Status: Fixed for customer purchase and renewal requests.

Two tabs could both see no pending order key and create different keys; a late response could also delete a newer attempt's key. Browser localStorage operations alone do not make the read-modify-write sequence atomic.

The earlier IndexedDB lock still read and wrote localStorage; repeated browser tests showed that different tabs could observe stale localStorage values despite the lock. Order keys now live in the IndexedDB transaction itself. A delayed success only clears the key it actually used, and pending-order views receive cross-tab change notifications. Legacy attempts are migrated once; the upgraded database prevents older order flows from opening the old storage version. If safe storage is unavailable, the request is not sent. Wallet topups and loyalty rewards use the same atomic store (FE-007 and FE-008); reseller and other loyalty flows remain under review.

## FE-006 — an unresolved order can become impossible to retry

Severity: High. Status: Fixed.

At b2b0099 the frontend retained the original idempotency key but did not expose it if a fresh purchase quote showed insufficient funds, or if a VPN account was no longer eligible for renewal. A lost response after the order was committed could therefore leave the customer unable to recover its result. The renewal unit regression and purchase browser regression both failed against the previous frontend because the recovery action was absent.

The order and VPN views now expose unresolved attempts for the current customer and store, even when a fresh quote is unavailable. Recovery submits the original payload and key; an action whose key has already been cleared cannot start a new order. The UI explains that an order not previously registered is retried at the current price. This relies on the existing backend idempotency contract and makes no API or schema changes.

## FE-008 — loyalty redemptions lose their retry key after errors or reloads

Severity: High. Status: Fixed.

At 369a5eb the reward key lived only in component memory and was deleted on any non-success response. The server commits the points debit and wallet credit before completing the response, so a 500 or lost response followed by another click or reload could redeem twice. Three regression cases failed on that base, including a retry with a different key and an inaccessible reward after reload.

Reward attempts persist per store, customer and reward in the same IndexedDB transactions as orders and topups. Legacy localStorage rewards are migrated and pending views receive cross-tab notifications. Ambiguous responses retain the key; recovery remains available even if the reward no longer appears in the club. A valid success clears only its own key, so a late response cannot erase a newer attempt. Redemption requires the signed-in identity, localStorage and IndexedDB. The API and database are unchanged. A definitive error can leave an attempt pending for support to reconcile, and pre-fix in-flight redemptions had no durable key.

## FE-007 — overlapping wallet topups can lose their retry key

Severity: High. Status: Fixed. Parent: PR #166 at `d8ee272`.

Each tab previously chose and saved a key with separate localStorage operations. A delayed rejection, success, terminal payment response or receipt from an older tab could also delete or overwrite a newer unresolved attempt. The next retry could use a fresh key and create a second payment intent.

Topups now choose and persist keys in a single IndexedDB transaction. Responses and receipt completion update or remove only the matching key. A non-success response retains its key because another request with that key may still be in flight; a malformed success also remains unresolved. If browser storage or coordination is unavailable, no request is sent.

Compatibility: after an HTTP error, the customer must retry the same amount or contact support until the prior attempt is resolved. Terminal failed or cancelled payments can be cleared. IndexedDB and localStorage are required. A localStorage guard refuses new attempts if initialized IndexedDB alone is deleted; clearing all browser storage cannot be detected, and recovery on another device is outside this browser-only protection. An already-open pre-upgrade wallet tab uses localStorage without IndexedDB and must be closed or reloaded at deployment; the project has no released users.

Regression evidence: tests cover stale responses, receipt completion, legacy migration, database loss and unavailable coordination. Chromium tests hold a real IndexedDB transaction while two tabs submit orders or topups; both wait and use the same key. A reload test verifies that migrated keys remain authoritative even when legacy localStorage changes.

## Customer order retry invariants

For a store, signed-in customer and exact request payload, every unresolved retry uses the same key. A late response must not erase a newer key, and a stale recovery action must never start a new order. If coordination or storage fails, no order is sent. Purchase and renewal recovery remains reachable without relying on a fresh quote.

The order request helper alone creates and conditionally clears the stored key; browser transactions serialize changes across tabs. Recovery views only read the attempt and submit its expected key. Wallet topups and loyalty rewards have their own retry policies (FE-007 and FE-008); other reseller and loyalty paths remain under review.

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
- FE-007 and the FE-005 storage correction: all 118 storefront tests, lint, typecheck, build and changed-file Prettier checks passed. Fifteen Chromium runs passed across five repetitions of both two-tab paths and legacy migration with mocked APIs. The full Windows checkout needs line-ending autodetection because its unchanged CRLF files fail the repository's LF-only format check.
- FE-008: 14 focused loyalty tests, lint and typecheck passed before the storage consolidation; two-tab browser coverage was added.
- Reconciled FE-005..FE-008: all 134 storefront tests, lint, typecheck, format check and production build passed. The account dashboard now loads on demand and first-load storefront JavaScript is 222.2 kB against the existing 274 kB budget.
- The complete Chromium suite on the reconciled frontend passed 32 tests; two scenarios requiring a seeded staging stack were skipped. It includes concurrent order, wallet and reward retries and recovery after reload.
- Admin web: 361 tests, lint, typecheck, format check and build passed.
- Before FE-004: Playwright browser suite passed 24 tests; two staging-only tests were skipped.

Backend make lint and make test passed on the FE-001 tree: 2,921 tests passed and 19 were skipped. FE-002 through FE-007 only change frontend code and audit documentation. A fresh backend make lint and make test also passed on the FE-006 tree: 2,921 tests passed and 19 were skipped; FE-007 does not change the backend. The frontend audit continues separately; no claim is made here that all frontend paths have been reviewed.
