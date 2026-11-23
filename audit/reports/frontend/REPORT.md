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

## Verification

- FE-001: five policy and real Nginx response tests passed.
- FE-002: all 89 storefront tests passed, including the recovery action and application entry point; lint, typecheck, format check and build also passed.

The backend make lint passed; make test is running and its result will be recorded after it finishes. The frontend audit continues separately; no claim is made here that all frontend paths have been reviewed.
