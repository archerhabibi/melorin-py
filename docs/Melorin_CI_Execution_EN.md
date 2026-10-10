# Melorin CI Execution

The requested local CI execution was attempted. This sandbox has Node.js 22, but does not have npm or Docker, so npm builds and Docker builds could not start. No build result is fabricated.

The CI defects found and fixed are:
- API Docker build now uses the root context with `-f apps/api/Dockerfile`.
- The previous GitHub Actions `working-directory: ../..` was invalid and removed.
- Store Web and Admin Web Docker builds now use the root context correctly.
- Web dependency installation uses `npm install --include=dev --no-audit --no-fund`, which repairs the initially minimal lockfile before building instead of failing at `npm ci`.
- Compose and Caddy service routing remain aligned with `store_web`, `admin_web`, and `api`.

Local gates that were available passed: Python compile, JavaScript config syntax, lockfile root consistency, shell syntax, and CI/Caddy assertions. The definitive runtime gate remains GitHub Actions because npm and Docker are unavailable here.
