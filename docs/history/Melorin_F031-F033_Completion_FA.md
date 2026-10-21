# تکمیل F031 تا F033 ملورین

F031 اصلاح شد: downgrade migration اولیه دیگر `drop_all` اجرا نمی‌کند و به‌صورت fail-safe متوقف می‌شود؛ rollback مخرب باید از backup یا migration صریح انجام شود.

F032 در baseline قبلی اصلاح شده بود و اکنون حفظ شد: upload سقف chunk-by-chunk دارد و magic bytes بررسی می‌شوند.

F033 اصلاح شد: Store Web و Admin Web در 401، refresh token را یک‌بار به `/auth/refresh` می‌فرستند، access و refresh جدید را ذخیره می‌کنند و درخواست اصلی را دوباره با Bearer token اجرا می‌کنند. سمت Core نیز rotation اتمیک و reuse detection خانواده refresh token برقرار است.

compile/AST، syntax اسکریپت‌ها و assertionهای source موفق شدند. اجرای واقعی browser، PostgreSQL migration و API زنده در این محیط انجام نشد.
