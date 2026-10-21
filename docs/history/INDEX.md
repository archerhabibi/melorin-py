# History index

Evidence of what was done and why. **None of these files is current status or release approval** - see
`docs/STATUS.md` (measurements) and `docs/RELEASE-EVIDENCE-MATRIX.md` (release status).

88 files. Files were moved here with `git mv`, so `git log --follow` still shows their full history.

## I - infrastructure / hardening passes (I17-I66) (49)

| File | Title |
|---|---|
| [`I17_BOOTSTRAP.md`](I17_BOOTSTRAP.md) | I17: first-install bootstrap |
| [`I18_WORKER_MODEL_REGISTRATION.md`](I18_WORKER_MODEL_REGISTRATION.md) | I18: worker model registration |
| [`I19_OUTBOX_SESSION_SAFETY.md`](I19_OUTBOX_SESSION_SAFETY.md) | I19: outbox session safety and replay protection |
| [`I20_ARQ_SCHEDULER.md`](I20_ARQ_SCHEDULER.md) | I20: reliable ARQ polling |
| [`I21_WEB_LOCKFILES.md`](I21_WEB_LOCKFILES.md) | I21: Web dependency lockfiles |
| [`I22_CI_QUALITY_GATE.md`](I22_CI_QUALITY_GATE.md) | I22: CI quality gate |
| [`I23_WORKER_ADAPTER_IMPORT.md`](I23_WORKER_ADAPTER_IMPORT.md) | I23: worker adapter registry import |
| [`I24_SSRF_GUARD.md`](I24_SSRF_GUARD.md) | I24: webhook SSRF guard |
| [`I25_RATE_LIMIT_HARDENING.md`](I25_RATE_LIMIT_HARDENING.md) | I25: rate-limit and login throttling |
| [`I26_OPERATIONAL_ENDPOINTS.md`](I26_OPERATIONAL_ENDPOINTS.md) | I26: operational endpoint exposure |
| [`I27_ASYNC_INTEGRATION_TESTS.md`](I27_ASYNC_INTEGRATION_TESTS.md) | I27: async and integration test depth |
| [`I28_LINT_GATE.md`](I28_LINT_GATE.md) | I28: lint gate cleanup |
| [`I29_FRONTEND_RUNTIME_DATA.md`](I29_FRONTEND_RUNTIME_DATA.md) | I29: frontend runtime data |
| [`I30_TOKEN_STORAGE.md`](I30_TOKEN_STORAGE.md) | I30: browser token storage |
| [`I31_READINESS_OBSERVABILITY.md`](I31_READINESS_OBSERVABILITY.md) | I31: readiness and worker observability |
| [`I32_SINGLE_WORKER_ENTRYPOINT.md`](I32_SINGLE_WORKER_ENTRYPOINT.md) | I32: single worker entrypoint |
| [`I33_DOCUMENTATION_STATUS.md`](I33_DOCUMENTATION_STATUS.md) | I33: documentation status policy |
| [`I34_EXTERNAL_INTEGRATIONS.md`](I34_EXTERNAL_INTEGRATIONS.md) | I34: external integration smoke gate |
| [`I35_TEST_MATRIX.md`](I35_TEST_MATRIX.md) | I35: test matrix and runtime evidence |
| [`I36_OPERATIONS_CLI.md`](I36_OPERATIONS_CLI.md) | I36: operations CLI |
| [`I37_PRIVACY_RETENTION.md`](I37_PRIVACY_RETENTION.md) | I37: privacy retention job |
| [`I38_PGCLOCK_GATEWAYS_IRT.md`](I38_PGCLOCK_GATEWAYS_IRT.md) | PGClockBot payment destination integration |
| [`I39_IRT_IRR_AUDIT.md`](I39_IRT_IRR_AUDIT.md) | I39: IRT/IRR compatibility audit |
| [`I40_CURRENCY_PAYMENT_CONTRACT.md`](I40_CURRENCY_PAYMENT_CONTRACT.md) | I40: currency/payment contract |
| [`I41_BACKUP_RESTORE_DRILL.md`](I41_BACKUP_RESTORE_DRILL.md) | I41: backup and restore drill |
| [`I42_ADMIN_FRONTEND_AUTH.md`](I42_ADMIN_FRONTEND_AUTH.md) | I42 — Admin frontend auth/runtime fix |
| [`I43_SANAEI_3XUI_ADAPTER.md`](I43_SANAEI_3XUI_ADAPTER.md) | I43 — تکمیل Adapter پنل سنایی (3x-ui) |
| [`I45_J01_DEPENDENCY_HARDENING.md`](I45_J01_DEPENDENCY_HARDENING.md) | I45: J01 Dependency Hardening |
| [`I46_J02_TRUSTED_PROXY_CIDR.md`](I46_J02_TRUSTED_PROXY_CIDR.md) | I46: J02 Trusted Proxy CIDR Handling |
| [`I47_J03_IDEMPOTENCY_RACE.md`](I47_J03_IDEMPOTENCY_RACE.md) | I47: J03 Concurrent Idempotency-Key Requests |
| [`I48_STORE_SCOPED_RESELLERS.md`](I48_STORE_SCOPED_RESELLERS.md) | I48: Store-Scoped Reseller Model |
| [`I49_J04_ENVIRONMENT_SAFETY.md`](I49_J04_ENVIRONMENT_SAFETY.md) | I49: J04 Environment Safety |
| [`I50_J05_TEST_STRATEGY.md`](I50_J05_TEST_STRATEGY.md) | I50: J05 Test Strategy and Coverage Gate |
| [`I51_J06_STAGING_EVIDENCE.md`](I51_J06_STAGING_EVIDENCE.md) | I51: J06 Staging Evidence Gate |
| [`I52_J07_REDIS_RATE_LIMIT_POLICY.md`](I52_J07_REDIS_RATE_LIMIT_POLICY.md) | I52: J07 Redis Outage Rate-Limit Policy |
| [`I53_J08_READINESS_HEALTHCHECKS.md`](I53_J08_READINESS_HEALTHCHECKS.md) | I53: J08 Readiness Semantics and Healthchecks |
| [`I54_J09_OPERATIONAL_ENDPOINT_AUTH.md`](I54_J09_OPERATIONAL_ENDPOINT_AUTH.md) | I54: J09 Operational Endpoint Authentication |
| [`I55_J10_ASYNC_PASSWORD_KDF.md`](I55_J10_ASYNC_PASSWORD_KDF.md) | I55: J10 Async Password KDF |
| [`I56_J11_ADMIN_SECURITY.md`](I56_J11_ADMIN_SECURITY.md) | I56: J11 Admin Security |
| [`I57_J12_FIXED_PAYMENT_CALLBACK_ORIGIN.md`](I57_J12_FIXED_PAYMENT_CALLBACK_ORIGIN.md) | I57: J12 Fixed Payment Callback Origin |
| [`I58_J13_FRONTEND_DEPENDENCY_HARDENING.md`](I58_J13_FRONTEND_DEPENDENCY_HARDENING.md) | I58: J13 Frontend Dependency Hardening |
| [`I59_J14_REPORTS_REFERRALS.md`](I59_J14_REPORTS_REFERRALS.md) | I59: Reports and Referral Modules |
| [`I60_J15_MULTI_STORE_RESELLER_BOTS.md`](I60_J15_MULTI_STORE_RESELLER_BOTS.md) | I60: J15 Multi-Store Reseller Bots |
| [`I61_BOT_STORE_OWNER_MAPPING.md`](I61_BOT_STORE_OWNER_MAPPING.md) | I61: Bot, Store, Owner Mapping |
| [`I62_J16_OBSERVABILITY_ALERTING.md`](I62_J16_OBSERVABILITY_ALERTING.md) | I62: Observability and Alerting |
| [`I63_J17_EXPLICIT_CORS_POLICY.md`](I63_J17_EXPLICIT_CORS_POLICY.md) | I63: J17 Explicit CORS Policy |
| [`I64_J18_HTTPONLY_ADMIN_SESSION.md`](I64_J18_HTTPONLY_ADMIN_SESSION.md) | I64: J18 HttpOnly Admin Session |
| [`I65_J19_QUALITY_GATE_HARDENING.md`](I65_J19_QUALITY_GATE_HARDENING.md) | I65: J19 Quality Gate Hardening |
| [`I66_J20_DOCUMENTATION_CONSOLIDATION.md`](I66_J20_DOCUMENTATION_CONSOLIDATION.md) | I66: J20 Documentation Consolidation |

## F / H / CI - finding and completion reports (37)

| File | Title |
|---|---|
| [`Melorin_Admin_Web_Completion_FA.md`](Melorin_Admin_Web_Completion_FA.md) | تکمیل اجزای پنل Admin Web |
| [`Melorin_CI_Execution_EN.md`](Melorin_CI_Execution_EN.md) | Melorin CI Execution |
| [`Melorin_CI_Execution_FA.md`](Melorin_CI_Execution_FA.md) | اجرای CI ملورین |
| [`Melorin_F001-F005_Refresh_FA.md`](Melorin_F001-F005_Refresh_FA.md) | بازبینی نهایی F001 تا F005 |
| [`Melorin_F001-F010_Completion_EN.md`](Melorin_F001-F010_Completion_EN.md) | Melorin F001-F010 Completion |
| [`Melorin_F001-F010_Completion_FA.md`](Melorin_F001-F010_Completion_FA.md) | تکمیل F001 تا F010 ملورین |
| [`Melorin_F001-F010_Final_EN.md`](Melorin_F001-F010_Final_EN.md) | Melorin F001-F010 Final Completion |
| [`Melorin_F001-F010_Final_FA.md`](Melorin_F001-F010_Final_FA.md) | تکمیل نهایی F001 تا F010 ملورین |
| [`Melorin_F002-F005_Completion_EN.md`](Melorin_F002-F005_Completion_EN.md) | Melorin F002-F005 Completion |
| [`Melorin_F002-F005_Completion_FA.md`](Melorin_F002-F005_Completion_FA.md) | تکمیل F002 تا F005 ملورین |
| [`Melorin_F005-F008_Completion_FA.md`](Melorin_F005-F008_Completion_FA.md) | تکمیل F005 تا F008 ملورین |
| [`Melorin_F007-F010_Completion_FA.md`](Melorin_F007-F010_Completion_FA.md) | تکمیل F007 تا F010 ملورین |
| [`Melorin_F010-F013_Completion_FA.md`](Melorin_F010-F013_Completion_FA.md) | تکمیل F010 تا F013 ملورین |
| [`Melorin_F010-F015_Completion_EN.md`](Melorin_F010-F015_Completion_EN.md) | Melorin F010-F015 Completion |
| [`Melorin_F010-F015_Completion_FA.md`](Melorin_F010-F015_Completion_FA.md) | تکمیل F010 تا F015 ملورین |
| [`Melorin_F015-F018_Completion_FA.md`](Melorin_F015-F018_Completion_FA.md) | تکمیل F015 تا F018 ملورین |
| [`Melorin_F015-F038_Final_Completion_FA.md`](Melorin_F015-F038_Final_Completion_FA.md) | Melorin F015-F038 Final Completion |
| [`Melorin_F019-F021_Completion_FA.md`](Melorin_F019-F021_Completion_FA.md) | تکمیل F019 تا F021 ملورین |
| [`Melorin_F021-F023_Completion_FA.md`](Melorin_F021-F023_Completion_FA.md) | تکمیل F021 تا F023 ملورین |
| [`Melorin_F024-F026_Completion_FA.md`](Melorin_F024-F026_Completion_FA.md) | تکمیل F024 تا F026 ملورین |
| [`Melorin_F026-F032_Completion_FA.md`](Melorin_F026-F032_Completion_FA.md) | تکمیل F026 تا F032 ملورین |
| [`Melorin_F027-F030_Completion_FA.md`](Melorin_F027-F030_Completion_FA.md) | تکمیل F027 تا F030 ملورین |
| [`Melorin_F031-F033_Completion_FA.md`](Melorin_F031-F033_Completion_FA.md) | تکمیل F031 تا F033 ملورین |
| [`Melorin_F033-F038_Completion_FA.md`](Melorin_F033-F038_Completion_FA.md) | تکمیل F033 تا F038 ملورین |
| [`Melorin_H001_Completion_FA.md`](Melorin_H001_Completion_FA.md) | تکمیل H001: نصب و پیش‌نیازهای اجرای واقعی |
| [`Melorin_H002_Completion_FA.md`](Melorin_H002_Completion_FA.md) | تکمیل H002: explicit Alembic baseline |
| [`Melorin_H003_Completion_FA.md`](Melorin_H003_Completion_FA.md) | تکمیل H003: اتصال واقعی وضعیت Backup به Admin Web |
| [`Melorin_H004_Completion_FA.md`](Melorin_H004_Completion_FA.md) | تکمیل H004: reproducible Web dependencies |
| [`Melorin_H005_Completion_FA.md`](Melorin_H005_Completion_FA.md) | تکمیل نهایی H005: Telegram runner واقعی |
| [`Melorin_H006_Completion_FA.md`](Melorin_H006_Completion_FA.md) | تکمیل H006: refund واقعی پرداخت |
| [`Melorin_H007_Completion_FA.md`](Melorin_H007_Completion_FA.md) | تکمیل H007: backup orchestration و restore evidence boundary |
| [`Melorin_H008_Completion_FA.md`](Melorin_H008_Completion_FA.md) | تکمیل H008: provider/panel و DNS runtime boundaries |
| [`Melorin_H009_Completion_FA.md`](Melorin_H009_Completion_FA.md) | تکمیل H009: صحت مالی و concurrency evidence |
| [`Melorin_H010_Completion_FA.md`](Melorin_H010_Completion_FA.md) | تکمیل H010: Observability عملیاتی |
| [`Melorin_H011_Completion_FA.md`](Melorin_H011_Completion_FA.md) | تکمیل H011: release evidence matrix و یکپارچه‌سازی مستندات |
| [`Melorin_H012_Completion_FA.md`](Melorin_H012_Completion_FA.md) | تکمیل H012: quality gate و test/contract suite |
| [`Melorin_Website_Completion_FA.md`](Melorin_Website_Completion_FA.md) | تکمیل بخش وبسایت Melorin |

## Audits and reviews (2)

| File | Title |
|---|---|
| [`FINAL_IMPLEMENTATION_REPORT.md`](FINAL_IMPLEMENTATION_REPORT.md) | Melorin Comprehensive Implementation Report |
| [`REVIEW_CHANGES_2026-10-12.md`](REVIEW_CHANGES_2026-10-12.md) | Comprehensive review changes - 2026-10-12 |
