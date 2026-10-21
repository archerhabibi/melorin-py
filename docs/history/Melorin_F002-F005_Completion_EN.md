# Melorin F002-F005 Completion

F002-F005 are now wired to the real Store Web and Admin Web source trees. Both apps have Vite/React entrypoints, deterministic package manifests and lockfiles, production Dockerfiles, SPA fallback Nginx configuration, same-origin `/api` proxying, and optional `VITE_MELORIN_API_URL` for split-host development. Compose builds both Web services from the repository root and Caddy routes the public domain to Store Web, the admin domain to Admin Web, and `/api/*` to Core API. CI runs both npm builds and both Web Docker builds.

Verification: Python compile, JavaScript config syntax, manifest presence, Caddy routing assertions, and Compose text checks passed. npm, Docker, and live browser/API execution were unavailable in this environment, so the CI pipeline is the runtime verification gate.
