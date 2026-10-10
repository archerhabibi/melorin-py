# تکمیل F033 تا F038 ملورین

F033 حفظ و تکمیل شد: Web clientها refresh token را پس از 401 rotate می‌کنند و Core reuse detection دارد.

F034 اصلاح شد: نسخه dependencyهای Web دقیق و بدون range هستند، lockfile root با manifest کنترل می‌شود و CI اسکریپت `check_web_lockfiles.py` را اجرا می‌کند. چون npm در این محیط نصب نیست، resolution کامل registry ادعا نمی‌شود.

F035 اصلاح شد: دامنه Telegram در `TELEGRAM-SCOPE.md` صریح و evidence-based ثبت شد؛ مسیرهای transport، auth و notification از قابلیت‌هایی که هنوز به sandbox/runtime نیاز دارند جدا شده‌اند و ادعای completeness حذف شد.

F036 اصلاح شد: متد `refund` به PaymentAdapter اضافه شد؛ adapterهایی که refund واقعی ندارند صریحاً NotImplemented می‌دهند و دیگر قرارداد فنی آن را مبهم یا silently پشتیبانی‌شده نشان نمی‌دهد.

F037 اصلاح شد: مستند backup به اسکریپت‌های واقعی encryption، checksum، retention، off-host و restore verification وصل شد و محدودیت نبود restore drill صریح ثبت شد.

F038 بررسی شد: `MELORIN_BOT_SERVICE_SECRET` فقط یک‌بار در `.env.example` وجود دارد؛ مقدار نمونه نیز secret واقعی نیست.

compile/AST، syntax اسکریپت‌ها و lockfile checks موفق شدند. npm registry، Docker، PostgreSQL، Telegram و restore واقعی در این محیط اجرا نشدند.
