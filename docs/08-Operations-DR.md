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
