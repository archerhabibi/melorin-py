# تکمیل H008: provider/panel و DNS runtime boundaries

## نتیجه
H008 در source و test contract تکمیل شد. Webhook delivery اکنون URL را بلافاصله پیش از ارسال دوباره resolve می‌کند، IPهای خصوصی/loopback را رد می‌کند، تغییر resolution بین دو بررسی را با `WEBHOOK_DNS_CHANGED` متوقف می‌کند و redirectها را خاموش نگه می‌دارد.

Panel adapter runtime نیز در production/staging فقط HTTPS و TLS verification فعال را قبول می‌کند؛ این guard در registry هنگام ساخت adapter enforce می‌شود، نه فقط در Admin create/update. Unknown provider outcomes در provisioning read-back می‌شوند و HTTP client lifecycle بسته می‌شود.

## شواهد
compileall، AST، shell syntax و H008 source contract موفق شدند. اجرای واقعی provider sandbox، timeout/5xx/redirect، DNS race و PostgreSQL/Redis در این محیط ممکن نیست؛ این‌ها باید در staging با test server کنترل‌شده اجرا شوند.
