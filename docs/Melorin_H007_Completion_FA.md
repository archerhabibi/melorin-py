# تکمیل H007: backup orchestration و restore evidence boundary

## نتیجه
H007 از یک اسکریپت منفرد به مسیر عملیاتی پروژه وصل شد. ARQ Worker اکنون هر روز ساعت ۰۲:۰۰ UTC `scripts/backup_secure.sh` را اجرا می‌کند، نتیجه موفق/ناموفق را در `backup_runs` ثبت می‌کند و Admin Web از endpoint عملیات backup آن را می‌خواند.

## کنترل‌های اجرایی
- backup با `PGPASSFILE` و بدون credential در argv اجرا می‌شود.
- artifact با age رمزنگاری و SHA-256 verify می‌شود.
- retention و off-host copy توسط اسکریپت انجام می‌شود.
- API Dockerfile اکنون scripts را داخل image کپی می‌کند؛ worker واقعاً به backup script دسترسی دارد.
- `scripts/backup_restore_verify.sh` checksum، decrypt و `pg_restore --list` را برای restore verification اجرا می‌کند.
- هر اجرای scheduled در `BackupRun` audit/status می‌گیرد.

## محدودیت evidence
در این محیط PostgreSQL، age، rclone، Docker و Redis/ARQ موجود نیستند؛ بنابراین backup/restore واقعی اجرا نشده است. H007 از نظر source، scheduling و audit integration انجام شد، اما production acceptance همچنان به backup واقعی، off-host copy و restore drill نیاز دارد.
