# تکمیل بخش وبسایت Melorin

Store Web از یک landing page صرف به storefront متصل به Core تبدیل شد. catalog از Store اصلی دریافت می‌شود، کاربر با email code وارد می‌شود، refresh token در درخواست‌های 401 rotate می‌شود، quote واقعی checkout با currency و wallet balance نمایش داده می‌شود، و خرید wallet-only با Idempotency-Key به Core ارسال می‌شود.

حساب کاربر نیز به `/me`، wallet و orders متصل شده و وضعیت اتصال Core در UI نمایش داده می‌شود. تجربه اصلی همچنان responsive و فارسی است: hero، catalog، پیش‌فاکتور، حساب کاربر، وضعیت کیف پول و fallback catalog برای زمانی که Core در دسترس نیست.

بررسی lockfile، compile API و website integration contract موفق شد. اجرای واقعی npm/Vite، مرورگر، Core API و PostgreSQL در این محیط ممکن نیست و باید در CI/staging اجرا شود.
