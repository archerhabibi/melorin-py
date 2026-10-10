# تکمیل H010: Observability عملیاتی

H010 اصلاح و به پروژه اضافه شد: metrics اکنون counters و gauges مستقل دارد، خروجی با content-type استاندارد Prometheus ارائه می‌شود، labelهای مسیر API bounded شده‌اند تا cardinality انفجاری ایجاد نشود، و خطای قبلی که event موفق outbox را با نتیجه retry ثبت می‌کرد اصلاح شد.

Prometheus با image pin‌شده `v2.55.1`، scrape interval پانزده‌ثانیه‌ای و scrape target واقعی `/metrics` به Compose اضافه شد. تست contract نیز wiring metrics، bounded route labels و Prometheus config را بررسی می‌کند.

compile/AST، shell syntax و config checks موفق شدند؛ اجرای Docker/Prometheus و scrape واقعی در این محیط ممکن نیست.
