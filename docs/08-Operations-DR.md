# استقرار، مانیتورینگ و بازیابی
## محیط‌ها و استقرار
Development، Staging، Production جدا. Production ابتدا روی VPS ممکن است. Ubuntu LTS، Docker Compose، شبکه خصوصی برای DB/Redis، CI/CD و migration checks. Zero-downtime در V1 الزامی نیست؛ چند Instance آینده باید ممکن باشد.
## Health
Liveness یعنی process زنده؛ Readiness یعنی آماده دریافت ترافیک؛ Dependency Health وضعیت PostgreSQL، Redis، worker، Panel و Gateway. خرابی Panel نباید بی‌دلیل کل Core را unready کند.
## Observability
Structured logs، CPU/RAM، API latency/error rate، ARQ/Redis queue depth/age، DB pool، Panel health و شاخص‌های مالی/عملیاتی. Correlation ID از Request تا Payment/Order/Provisioning/Notification. Prometheus/Grafana و Sentry گزینه‌های پیشنهادی قابل تعویض. Secret و داده شخصی در log ماسک شود. Alert دارای threshold، deduplication، retry و recovery notification.
## Backup
یک تا دو بار روزانه قابل تنظیم؛ Retention پیش‌فرض 30 روز. نسخه محلی و خارج از سرور، encryption-at-rest، Restore Test دوره‌ای. Telegram فقط وضعیت Backup را اعلام کند، نه فایل Backup.
## Recovery
Runbook برای خرابی VPS، PostgreSQL، Redis، Panel، Gateway، deploy و data corruption. هدف بازیابی مصوب: RPO حداکثر 24 ساعت و RTO حداکثر 8 ساعت. این اهداف باید با زمان‌بندی Backup، آزمون Restore و تمرین دوره‌ای سنجیده شوند؛ Backup بدون Restore Test کافی نیست.
## Emergency & Maintenance
Admin بتواند خرید، پرداخت، Reseller، Product، Panel، API، Bot و Provisioning را متوقف کند. Maintenance در سطح سیستم، Channel، Store یا Feature. همه تغییرات Audit شوند.
## Storage/Retention
Storage abstraction برای Local یا S3-compatible. فایل Ticket/Receipt خصوصی و فقط از مسیر Authorization قابل دسترسی. Cleanup نباید سوابق مالی/Audit را حذف کند.

## M7.6 — Alerts and metrics

`/metrics` (bearer token) now exposes, besides the existing counters: `melorin_http_request_duration_seconds` (histogram, bounded `path` label), and database-derived gauges refreshed on every scrape: `melorin_payments_recent_{total,failed,failure_ratio}` (15 min), `melorin_orders_provisioning_failed_recent` (1 h), `melorin_orders_needs_review`, `melorin_reseller_bots_unhealthy`, `melorin_backup_age_seconds`.

| Alert | Fires when |
|---|---|
| MelorinHttpErrorRateHigh | 5xx ratio > 5% for 5 min |
| MelorinHttpLatencyHigh | p95 latency > 2.5 s for 10 min |
| MelorinPaymentFailureRateHigh | > 50% of ≥ 5 recent payments failed |
| MelorinProvisioningFailures | any order failed provisioning in the last hour |
| MelorinResellerBotUnhealthy | a reseller bot is offline (stale heartbeat) or in error |
| MelorinBackupStale | no successful backup for 36 h (or ever) |

`tests/test_observability_metrics.py` checks that every alert expression only references metrics the code really emits.

## Backup implementation

Backup source is implemented by `scripts/backup_secure.sh`. It uses `PGPASSFILE`, age recipient encryption, SHA-256 verification, retention cleanup, and optional rclone off-host copy. Restore evidence is checked by `scripts/backup_restore_verify.sh`, which verifies the checksum, decrypts the archive, and runs `pg_restore --list`.

These scripts are integration boundaries, not proof of a completed production restore. A release still requires PostgreSQL, age, off-host storage, and a real restore drill.
