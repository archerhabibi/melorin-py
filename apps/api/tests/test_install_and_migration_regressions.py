from pathlib import Path

from _source import read_source

ROOT = Path(__file__).resolve().parents[1]


def test_migration_and_worker_blockers_are_fixed():
    env = read_source(ROOT / "alembic/env.py")
    baseline = read_source(ROOT / "alembic/versions/0001_initial.py")
    runner = read_source(ROOT / "melorin/worker/runner.py")
    arq = read_source(ROOT / "melorin/worker/arq_app.py")
    assert "await c.commit()" in env
    assert "async with connectable.begin()" not in env
    assert "await c.run_sync(lambda conn: context.run_migrations())" in env
    assert "BASELINE_DDL" in baseline
    assert "conn.exec_driver_sql(statement)" in baseline
    assert "CreateTable" not in baseline
    assert "MODEL_SOURCE_FINGERPRINT" in baseline
    assert "from melorin import models" in runner
    assert "melorin.modules.vpn.adapters.registry import" in runner and "build_adapter" in runner
    assert "register all SQLAlchemy mappers before worker sessions" in runner
    assert "session.get(OutboxEvent, event_id, with_for_update=True)" in runner
    assert "with_for_update=True" in runner
    assert "failed = await session.get(OutboxEvent, event_id" in runner
    assert "cron(poll_tick" in arq
    assert "enqueue_job" not in arq


def test_store_scoped_reseller_migration_skips_legacy_index_on_current_schema():
    migration = read_source(ROOT / "alembic/versions/0004_f027_f030.py")
    assert 'if "target_store_id" in app_columns:' in migration
    assert "uq_reseller_application_pending_user" in migration


def test_installer_supports_external_proxy_and_bootstraps_admin():
    root = ROOT.parent.parent
    installer = (root / "scripts/install_server.sh").read_text()
    external = (root / "docker-compose.external.yml").read_text()
    compose = (root / "docker-compose.yml").read_text()
    assert 'EXTERNAL_PROXY="${EXTERNAL_PROXY:-false}"' in installer
    assert "docker-compose.external.yml" in installer
    assert "python -m melorin.cli bootstrap" in installer
    assert "127.0.0.1:18000:8000" in external
    assert "127.0.0.1:18080:80" in external
    assert "127.0.0.1:18081:80" in external
    assert "profiles: [local-proxy]" in compose


def test_bootstrap_cli_and_ci_use_real_entrypoints():
    assert (ROOT / "melorin/cli.py").exists()
    cli = read_source(ROOT / "melorin/cli.py")
    assert "settings_store.DEFAULTS" in cli
    assert "seed_demo_data" in cli
    assert 'where(Product.code == "TEST")' in cli
    assert "python -m melorin.cli bootstrap" in (ROOT.parent.parent / "scripts/bootstrap.sh").read_text()
    ci = (ROOT.parent.parent / ".github/workflows/ci.yml").read_text()
    assert "run_quality_gate.sh" in ci


def test_web_lockfile_gate_rejects_missing_or_hollow_graphs():
    checker = read_source(ROOT.parent.parent / "scripts/check_web_lockfiles.py")
    assert "assert lock_path.exists()" in checker
    assert "resolved" in checker and "integrity" in checker


def test_quality_gate_has_no_broken_script_reference_and_ssrf_guard_is_live():
    ci = (ROOT.parent.parent / ".github/workflows/ci.yml").read_text()
    gate = (ROOT.parent.parent / "scripts/run_quality_gate.sh").read_text()
    webhook = read_source(ROOT / "melorin/domain/webhook.py")
    assert "run_quality_gate.py" not in ci
    assert "run_quality_gate.sh" in ci
    assert "check_web_lockfiles.py" not in gate
    assert "parsed_ip = None" in webhook
    assert "if parsed_ip is not None and _blocked_ip(parsed_ip)" in webhook


def test_rate_limit_does_not_trust_untrusted_forwarded_headers():
    ratelimit = read_source(ROOT / "melorin/core/ratelimit.py")
    middleware = read_source(ROOT / "melorin/core/middleware.py")
    identity = read_source(ROOT / "melorin/modules/identity/router.py")
    assert "trusted_proxy_ips" in ratelimit
    assert "resolve_client_ip" in ratelimit
    assert "auth-account:" in identity
    assert "resolve_client_ip" in middleware


def test_operational_endpoints_are_not_public():
    app = read_source(ROOT / "melorin/app.py")
    caddy = (ROOT.parent.parent / "infra/Caddyfile").read_text()
    assert 'docs_url="/docs" if s.is_dev else None' in app
    assert 'openapi_url="/openapi.json" if s.is_dev else None' in app
    assert "@blocked_ops path /metrics /docs /redoc /openapi.json" in caddy
    assert "@api path /api/* /health/* /health /healthz" in caddy
    assert " /metrics" not in caddy.split("@api path", 1)[1].split("handle", 1)[0]


def test_async_test_tooling_is_pinned():
    requirements = (ROOT / "requirements.txt").read_text()
    assert "pytest-asyncio==" in requirements
    assert "pytest-cov==" in requirements


def test_store_frontend_does_not_fallback_to_demo_plans():
    source = (ROOT.parent.parent / "apps/store-web/src/App.jsx").read_text()
    assert "const demoPlans" not in source
    assert "catalog.length ?" in source
    assert "catalog.length ? catalog : demoPlans" not in source


def test_web_tokens_are_not_persisted_in_local_storage():
    for path in (
        ROOT.parent.parent / "apps/store-web/src/App.jsx",
        ROOT.parent.parent / "apps/admin-web/src/AdminAuth.jsx",
        ROOT.parent.parent / "apps/admin-web/src/AdminExtra.jsx",
        ROOT.parent.parent / "apps/admin-web/src/AdminSections.jsx",
    ):
        source = path.read_text()
        assert "localStorage.setItem" not in source
        assert "localStorage.getItem('melorin" not in source
        assert 'localStorage.getItem("melorin' not in source


def test_readiness_checks_dependencies_and_worker_signals():
    app = read_source(ROOT / "melorin/app.py")
    worker = read_source(ROOT / "melorin/worker/arq_app.py")
    assert "redis.ping()" in app
    assert "OutboxEvent" in app and "Panel" in app
    assert "melorin_outbox_pending" in app
    assert "melorin_worker_last_tick" in worker
    assert "melorin:worker:last_tick" in worker
    assert "worker_last_tick" in app


def test_redis_and_bootstrap_admin_have_bounded_operational_paths():
    redis = read_source(ROOT / "melorin/core/redis.py")
    app = read_source(ROOT / "melorin/app.py")
    config = read_source(ROOT / "melorin/core/config.py")
    cli = read_source(ROOT / "melorin/cli.py")
    installer = (ROOT.parent.parent / "scripts/install_server.sh").read_text()
    assert "socket_connect_timeout=1.5" in redis
    assert "socket_timeout=2.0" in redis
    assert "asyncio.wait_for(redis.ping(), timeout=REDIS_TIMEOUT_SECONDS)" in app
    assert "bootstrap_admin_totp_secret" in config
    assert "user.totp_enabled = True" in cli
    assert "MELORIN_BOOTSTRAP_ADMIN_TOTP_SECRET" in installer


def test_k11_to_k20_operational_controls_are_present():
    root = ROOT.parent.parent
    compose = (root / "docker-compose.yml").read_text()
    installer = (root / "scripts/install_server.sh").read_text()
    arq = read_source(ROOT / "melorin/worker/arq_app.py")
    alerts = (root / "infra/alerts.yml").read_text()
    registry = read_source(ROOT / "melorin/modules/vpn/adapters/registry.py")
    orders = read_source(ROOT / "melorin/modules/orders/service.py")
    vpn = read_source(ROOT / "melorin/modules/orders/provisioning.py")
    assert "secrets/metrics-token" in compose and "tmp_metrics" in installer
    assert "recipients.txt:/run/melorin-backup/recipients.txt:ro" in compose
    for marker in ("panel_health_job", "expiry_job", "near_expiry_job", "reconciliation_job"):
        assert marker in arq
    assert "timeout=900" in arq
    assert 'state="firing"} > 0' in alerts and "for: 5m" in alerts
    assert "_public_panel_url" in registry and ".is_private" in registry
    assert "order_paid_retry:" in orders and "already_claimed" in vpn


def test_k21_to_k27_hardening_is_wired():
    root = ROOT.parent.parent
    limiter = read_source(ROOT / "melorin/core/ratelimit.py")
    identity = read_source(ROOT / "melorin/modules/identity/service.py")
    config = read_source(ROOT / "melorin/core/config.py")
    compose = (root / "docker-compose.yml").read_text()
    store_auth = (root / "apps/store-web/src/App.jsx").read_text()
    quality = (root / "scripts/run_quality_gate.sh").read_text()
    assert "return False" in limiter and "if not user.is_active" in identity
    assert "backup_offsite_uri" in config
    assert "mem_limit:" in compose and "cpus:" in compose
    assert 'credentials:"include"' in store_auth and "/api/v1/auth/refresh" in store_auth
    assert "npm audit --include=dev" in quality


def test_full_project_regressions_are_wired():
    root = ROOT.parent.parent
    product_schema = read_source(ROOT / "melorin/modules/admin/schemas.py")
    product_router = read_source(ROOT / "melorin/modules/admin/router.py")
    payment_router = read_source(ROOT / "melorin/modules/reseller/router.py")
    referral_model = read_source(ROOT / "melorin/kernel/models/referral.py")
    migration = read_source(ROOT / "alembic/versions/0009_referral_first_reward_guard.py")
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "class ProductPatch" in product_schema and "body: ProductPatch" in product_router
    assert "PAYMENT_REVIEW_FORBIDDEN" in payment_router
    assert "referred_user_id" in referral_model and "0009_referral_first_reward_guard" in migration
    assert "postgresql-client-16" in dockerfile and "apt.postgresql.org" in dockerfile
    telegram = read_source(root / "apps/telegram-main/runner.py")
    assert "MELORIN_MAX_UPLOAD_BYTES" in telegram and "file_size" in telegram


def test_worker_has_one_runtime_entrypoint():
    runner = read_source(ROOT / "melorin/worker/runner.py")
    read_source(ROOT / "melorin/worker/arq_app.py")  # must exist and be readable
    makefile = (ROOT.parent.parent / "Makefile").read_text()
    compose = (ROOT.parent.parent / "docker-compose.yml").read_text()
    assert "def worker_loop" not in runner
    assert "python -m melorin.worker.runner" not in makefile
    assert "arq melorin.worker.arq_app.WorkerSettings" in makefile
    assert "arq melorin.worker.arq_app.WorkerSettings" in compose


def test_lint_gate_uses_correctness_focused_policy():
    config = (ROOT / "pyproject.toml").read_text()
    assert "[tool.ruff.lint]" in config
    assert 'select = ["E4", "E9", "F"]' in config
    assert 'ignore = ["F403", "F405"]' in config


def test_release_matrix_is_the_single_current_status_source():
    matrix = (ROOT.parent.parent / "docs/RELEASE-EVIDENCE-MATRIX.md").read_text()
    checker = read_source(ROOT.parent.parent / "scripts/check_release_matrix.py")
    policy = (ROOT.parent.parent / "docs/history/I33_DOCUMENTATION_STATUS.md").read_text()
    assert "I33" in checker
    assert "historical" in matrix.lower() and "historical" in policy.lower()


def test_i34_smoke_gate_is_explicit_and_preflight_matches_current_repo():
    preflight = read_source(ROOT.parent.parent / "scripts/preflight.py")
    smoke = (ROOT.parent.parent / "scripts/integration_smoke.sh").read_text()
    assert "apps/store-web/package.json" in preflight
    assert "package-lock.json" not in preflight
    assert "MELORIN_DATABASE_URL" in smoke
    assert "MELORIN_REDIS_URL" in smoke
    assert "MELORIN_RUN_EXTERNAL_PROVIDERS" in smoke


def test_i35_test_matrix_exposes_integration_boundary():
    matrix = read_source(ROOT.parent.parent / "scripts/test_matrix.py")
    assert '"unit"' in matrix and '"integration"' in matrix and '"all"' in matrix
    assert "pytest" in matrix
    assert "MELORIN_COVERAGE" in matrix


def test_i36_cli_has_explicit_operational_commands():
    cli = read_source(ROOT / "melorin/cli.py")
    assert '"outbox-replay"' in cli
    assert '"rotate-encryption-key"' in cli
    assert "OutboxEvent" in cli
    assert "new_fernet.encrypt" in cli


def test_i37_privacy_retention_preserves_financial_and_audit_tables():
    jobs = read_source(ROOT / "melorin/worker/jobs.py")
    arq = read_source(ROOT / "melorin/worker/arq_app.py")
    settings = read_source(ROOT / "melorin/core/settings_store.py")
    assert "privacy_retention_job" in jobs
    assert "VerificationCode" in jobs
    assert "privacy.verification_code_retention_days" in settings
    assert "cron(privacy_retention_job" in arq
    assert "AuditEvent" not in jobs and "Ledger" not in jobs


def test_i38_pgclock_destinations_and_irt_default():
    config = read_source(ROOT / "melorin/core/config.py")
    catalog = read_source(ROOT / "melorin/modules/payments/gateway_catalog.py")
    currency = read_source(ROOT / "melorin/domain/currency.py")
    assert 'default_currency: str = "IRT"' in config
    for provider in ("manual_card", "external_gateway", "crypto", "telegram_stars"):
        assert f'"{provider}"' in catalog
    assert '"XTR"' in currency
    registry = read_source(ROOT / "melorin/modules/payments/adapters/registry.py")
    assert "DestinationAdapter" in registry
    assert '"crypto"' in registry and '"telegram_stars"' in registry


def test_i39_irt_irr_boundaries_are_explicit():
    migration = read_source(ROOT / "alembic/versions/0002_v11.py")
    smoke = read_source(ROOT.parent.parent / "scripts/postgres_concurrency_smoke.py")
    zarinpal = read_source(ROOT / "melorin/modules/payments/adapters/zarinpal.py")
    audit = (ROOT.parent.parent / "docs/history/I39_IRT_IRR_AUDIT.md").read_text()
    assert "default=\"'IRT'\"" in migration
    assert 'currency="IRT"' in smoke
    assert "_gateway_amount" in zarinpal
    assert "payment.amount * 10" in zarinpal
    assert "IRT" in audit and "IRR" in audit


def test_i40_currency_payment_contract_exists():
    test = read_source(ROOT / "tests/test_payment_currency_contract.py")
    doc = (ROOT.parent.parent / "docs/history/I40_CURRENCY_PAYMENT_CONTRACT.md").read_text()
    assert "_gateway_amount" in test
    assert "destination/currency mismatch" in doc


def test_i41_restore_drill_is_real_and_isolated():
    script = (ROOT.parent.parent / "scripts/backup_restore_drill.sh").read_text()
    doc = (ROOT.parent.parent / "docs/history/I41_BACKUP_RESTORE_DRILL.md").read_text()
    assert "createdb" in script and "pg_restore" in script and "dropdb" in script
    assert "restore_drill" in script
    assert "RPO" in doc and "RTO" in doc
