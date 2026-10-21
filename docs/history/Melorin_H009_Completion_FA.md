# تکمیل H009: صحت مالی و concurrency evidence

## نتیجه
H009 در source تکمیل شد: درج LedgerTransaction اکنون در savepoint انجام می‌شود و اگر دو درخواست همزمان با یک idempotency key به unique constraint برسند، بازنده transaction موجود را برمی‌گرداند و double posting رخ نمی‌دهد. این رفتار در کنار row lockهای Wallet و بررسی currency mismatch قرار دارد.

گزارش Admin نیز صریحاً Paymentهای موفق را بر اساس `Payment.currency` گروه می‌کند و پرچم `currency_safe` برمی‌گرداند؛ ارزهای مختلف با هم جمع نمی‌شوند.

## گیت integration اضافه‌شده
`scripts/postgres_concurrency_smoke.py` با PostgreSQL واقعی دو transaction همزمان را با یک idempotency key اجرا می‌کند و assert می‌کند فقط یک LedgerTransaction و فقط یک post ساخته شده است. اجرای آن:

```bash
MELORIN_DATABASE_URL=postgresql+asyncpg://... python scripts/postgres_concurrency_smoke.py
```

## شواهد این محیط
compileall، AST، shell syntax و finance contract checks موفق شدند. PostgreSQL، SQLAlchemy runtime و pytest در این sandbox در دسترس نیستند؛ بنابراین smoke concurrency واقعی اجرا نشده و باید در CI/staging اجرا شود.
