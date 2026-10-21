# تکمیل نهایی H005: Telegram runner واقعی

H005 در baseline فعلی تکمیل و دوباره سخت‌سازی شد. Main و Reseller runner واقعی long-poll دارند، offset را روی volume مستقل به‌صورت atomic ذخیره می‌کنند، update را قبل از عملیات به Core احراز می‌کنند، commandهای پایه و callback query را handle می‌کنند، و خطاهای شبکه/API را با backoff محدود retry می‌کنند.

یک ایراد مهم callback نیز اصلاح شد: هویت callback از `callback_query.from` خوانده می‌شود، نه از `message.from`؛ بنابراین callbackها با حساب کاربر اشتباه authenticate نمی‌شوند. shutdown با بستن AsyncClient انجام می‌شود و Docker/Compose برای هر bot سرویس، Dockerfile، token جدا و state volume مستقل دارد.

compileall، AST runner، regression contract و syntax اسکریپت‌ها موفق شدند. اجرای واقعی Telegram API، Core API، Docker و restart/replay sandbox در این محیط ممکن نیست؛ این موارد gate نهایی CI/staging هستند.
