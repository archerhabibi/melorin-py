# Melorin Release Evidence Matrix

This is the authoritative release-status document. Older phase/F finding reports are historical change records; they must not be read as production approval. A capability is only release-ready when all four evidence columns are green.

| Area | Implemented in source | Static-tested | Runtime-tested | Production-evidenced | Current decision |
|---|---:|---:|---:|---:|---|
| API/Core startup and dependencies | Yes | Yes | Yes (2026-10-10, local PG16/Redis7, full E2E) | No | Blocked |
| Explicit Alembic baseline and upgrade | Yes | Yes | Yes (fresh DB to the head of that day, `alembic check` clean; current head: `docs/STATUS.md`) | No | Blocked |
| Store/Admin Web routing and API contract | Yes | Yes | Yes (headless Chromium vs live API) | No | Blocked |
| Deterministic Web lockfiles/build | Yes | Yes | Yes (`npm ci` + build; Docker image build not run) | No | Blocked |
| Telegram Main/Reseller runners | Yes | Yes | No | No | Blocked |
| Payment refund adapter and wallet reversal | Yes | Yes | No | No | Blocked |
| Encrypted scheduled backup | Yes | Yes | Partial (manual backup + restore drill passed; schedule not run) | No | Blocked |
| Provider/TLS/DNS safeguards | Yes | Yes | No | No | Blocked |
| PostgreSQL finance concurrency | Yes | Yes | Partial (sequential wallet flow only) | No | Blocked |
| Metrics and Prometheus scrape config | Yes | Yes | Partial (`/metrics` served; Prometheus not run) | No | Blocked |

## Evidence rules

- **Implemented in source** means the behavior exists in the canonical repository and has a clear owner/boundary.
- **Static-tested** means compile, AST, source contract, shell, lockfile, or configuration checks passed.
- **Runtime-tested** means the relevant service actually started and the behavior was exercised against its real dependency.
- **Production-evidenced** means staging/production-like credentials, deployment, monitoring, recovery, and operational logs exist.

## Runtime evidence log

- 2026-10-10 (local, PostgreSQL 16, Redis 7, Python 3.13, Node 22): `alembic upgrade head` on an empty database, `alembic check`, `python -m melorin.cli bootstrap` (twice, idempotent), API + ARQ worker, `scripts/e2e_smoke.py` (top-up, approval, wallet purchase, mock provisioning, one VPN account, outbox drained, worker heartbeat, XFF-rotation brute force throttled), outbox replay without duplicate accounts, `npm ci` + build of both web apps, headless-browser login and dashboard, encrypted backup + `backup_restore_drill.sh` (47 tables restored).
- Not run: Docker image builds/Compose (no daemon), Telegram bots against the Bot API, Zarinpal sandbox, real Sanaei/PasarGuard panels, Prometheus.
- 2026-10-18 (M7.3): `scripts/runtime_evidence.py` added (see [Runtime evidence collector](#runtime-evidence-collector-m73)). It is fail-closed and was **not run against real systems** in that change; the items above are still not run and no matrix cell was changed.

## J01-J19 remediation status

This table tracks implementation and evidence separately. A completed code change does not make a row runtime-tested or production-evidenced.

| Finding | Remediation now in source | Static evidence | Runtime evidence | Production decision |
|---|---|---|---|---|
| J01 | Python pins upgraded; pip-audit CI gate; Dependabot enabled | Compile and config checks passed | CI package install/audit required | Blocked |
| J02 | CIDR-aware trusted proxy resolver; fixed Compose proxy subnet | Resolver and config checks passed | Through-Caddy staging test required | Blocked |
| J03 | Savepoint-protected order insert and winner recovery | Regression contract added | PostgreSQL concurrent order test required | Blocked |
| J04 | Closed environment enum; Fernet, CORS and public URL validation | Settings contract added | Startup matrix required | Blocked |
| J05 | Unit/integration/concurrency matrix; coverage XML and CI floor | Test strategy contracts passed | Full CI integration run required | Blocked |
| J06 | Staging evidence command; Compose healthchecks; provider probes | Shell/config checks passed | Staging bundle required | Blocked |
| J07 | Atomic Redis pipeline; bounded local degraded limiter | Redis policy regression added | Redis outage test required | Blocked |
| J08 | Readiness returns 503 unless DB, Redis and fresh worker heartbeat pass | Readiness and Compose checks passed | Failure-injection staging test required | Blocked |
| J09 | Metrics bearer token; terse public health; protected Prometheus scrape | Endpoint/config contracts passed | Authenticated scrape test required | Blocked |
| J10 | scrypt hashing moved off event loop with `asyncio.to_thread` | Async call-site contract passed | Load/latency test required | Blocked |
| J11 | Mandatory admin 2FA and persisted TOTP replay counter; role metadata migration | Security contracts passed | Login/replay integration test required | Blocked |
| J12 | Fixed HTTPS `MELORIN_PUBLIC_API_URL` for payment callbacks | Callback-origin contract passed | Gateway sandbox callback test required | Blocked |
| J13 | Build tooling moved to devDependencies; npm audit CI gate | Manifest/lockfile checks passed | npm audit/build CI required | Blocked |
| J14 | Reports and referral routers added; commission rules/history exposed | Route contracts passed | API integration test required | Blocked |
| J15 | Multi-store reseller bot config with isolated state; Core-only operations | Runner contract passed | Telegram Bot API multi-store test required | Blocked |
| J16 | Alert state for DB, Redis, worker, panels and outbox; Prometheus rules | Alert/config checks passed | Prometheus/Alertmanager test required | Blocked |
| J17 | Explicit CORS origin/method/header allowlists; wildcards rejected outside dev | CORS contract passed | Browser preflight staging test required | Blocked |
| J18 | HttpOnly refresh cookie; memory-only access token; reload recovery | Session contract passed | Browser cookie/refresh test required | Blocked |
| J19 | Ruff E/I/UP/B policy, format check, local/CI consistency guard | Quality config check passed | Full CI lint run required | Blocked |

**J01-J19 status:** source remediation is present and static evidence is recorded; no item is marked runtime-tested or production-evidenced by static checks alone.

## Current release decision

**RELEASE BLOCKED.** The repository has meaningful source and static evidence, but Docker/Compose, Telegram, payment providers, panel providers and any production-like environment have no runtime evidence yet.

## Required promotion path

1. Run `scripts/install_verify.sh` in a runner with package-registry access.
2. Run `scripts/migration_smoke.sh` against fresh and upgraded PostgreSQL.
3. Run `npm ci`, both Web builds, and all Docker image builds.
4. Start Compose with PostgreSQL, Redis/ARQ, API, Web, Telegram and Prometheus.
5. Execute payment/provider/Telegram/finance-concurrency smoke suites.
6. Execute encrypted backup, off-host copy, decrypt, restore and integrity checks.
7. Run `python scripts/runtime_evidence.py --allow-mutation` (Telegram, Zarinpal sandbox, panels, Docker, Caddy, Prometheus/Alertmanager); attach `var/evidence/m73-*/summary.json`.
8. Attach timestamped logs and update only the evidence columns that actually passed.

## Runtime evidence collector (M7.3)

`scripts/runtime_evidence.py` gathers the evidence that unit tests cannot provide and that
[`RELEASE-EVIDENCE-MATRIX.md`](RELEASE-EVIDENCE-MATRIX.md) requires before any "Runtime-tested" cell may turn green.

**It is fail-closed.** A check without its prerequisites is `skipped` (with the reason), never `passed`; any skipped
check makes the exit code non-zero (3) unless `--allow-skip` is given; a failure exits 1. Secrets are masked in
`summary.json`, `summary.md` and logs. Nothing in the repository claims these checks have already run.

```bash
python scripts/runtime_evidence.py --list
python scripts/runtime_evidence.py --only telegram_main,zarinpal_sandbox
python scripts/runtime_evidence.py --allow-mutation        # everything that is configured
make evidence                                                # same, via Makefile
```

The bundle is written to `var/evidence/m73-<UTC timestamp>/` (`summary.json`, `summary.md`, build/validate logs).
Attach it to the release record and flip only the matrix cells whose checks are `passed`.

| Check | Proves | Needs |
|---|---|---|
| `telegram_main` | Main bot token is valid (`getMe`) and no webhook blocks long polling | `MELORIN_TELEGRAM_TOKEN` |
| `telegram_reseller` | Same for a reseller bot | `MELORIN_TELEGRAM_RESELLER_BOT_TOKEN` |
| `zarinpal_sandbox` | `request.json` returns a sandbox StartPay URL; cancelled, unpaid and forged callbacks never verify | `MELORIN_ZARINPAL_SANDBOX_MERCHANT` (any sandbox merchant UUID) |
| `panel_roundtrip` | health, create, read, extend, suspend/resume, revoke and "gone" on each real panel (Sanaei, PasarGuard) | `MELORIN_EVIDENCE_PANELS` (JSON file path) and `--allow-mutation` |
| `docker_build` | `docker compose config` and all three image builds | docker CLI/daemon |
| `caddy_config` | `infra/Caddyfile` validates (including the on-demand TLS block) | `caddy` or docker |
| `tls_ask_gate` | `/api/v1/tls/ask` answers 200 for an active reseller domain and 404 for everything else | `MELORIN_EVIDENCE_API_URL`, `MELORIN_EVIDENCE_RESELLER_DOMAIN` |
| `prometheus_rules` | `infra/alerts.yml` passes `promtool check rules` | `promtool` or docker |
| `prometheus_scrape` | Prometheus scrapes `melorin-api` (`up == 1`) and loaded the `melorin-core` rule group | `MELORIN_PROMETHEUS_URL` |
| `alert_delivery` | A synthetic alert pushed to Alertmanager reaches the receiver | `MELORIN_ALERTMANAGER_URL`, `MELORIN_ALERT_RECEIVER_PROBE_URL` |

`MELORIN_EVIDENCE_PANELS` example (credentials stay in the file, never in the bundle):

```json
[{"name": "tehran-1", "kind": "pasarguard", "base_url": "https://panel.example.com",
  "credentials": {"username": "admin", "password": "..."}, "config": {"group_ids": [1]}}]
```

Not automatable here and therefore recorded by hand: a real card payment in the Zarinpal sandbox (needs a browser),
the first real certificate issued for a reseller domain (needs public DNS), and Telegram end-to-end conversations.
