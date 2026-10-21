# تکمیل F024 تا F026 ملورین

F024 اصلاح شد: قرارداد اجرایی `API-ROUTES-ACTIVE.md` با مسیرهای واقعی sync شد و endpointهای Admin گزارش، refund، CSV، users، tickets و stores در Core ثبت شدند.

F025 اصلاح شد: navigationهای Users، Tickets و Stores دیگر placeholder نیستند؛ endpointهای واقعی Admin اضافه شد و Admin Web برای هر سه بخش داده زنده از Core می‌گیرد و render می‌کند. وضعیت‌های بدون endpoint business نیز نمایش جعلی ندارند.

F026 اصلاح شد: اصلاح کیف پول reseller به Store و currency همان Store محدود است و correction منفی نمی‌تواند موجودی مشتری را زیر صفر ببرد؛ ledger و idempotency حفظ شده‌اند.

compile/AST و assertionهای source موفق شدند. اجرای زنده API/browser/PostgreSQL در این محیط ممکن نیست.
