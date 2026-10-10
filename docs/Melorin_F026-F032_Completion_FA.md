# تکمیل F026 تا F032 ملورین

F026 سخت‌سازی شد: اصلاح منفی کیف پول reseller اکنون پس از قفل دیتابیسی Wallet بررسی می‌شود؛ check و ledger post در برابر دو درخواست همزمان روی یک balance واحد serialize می‌شوند و currency همان Store باقی می‌ماند.

F027 حفظ و تکمیل شد: partial unique index برای یک درخواست pending هر کاربر، approval با row lock، و جلوگیری از ساخت فروشگاه نمایندگی تکراری فعال است.

F028 تکمیل شد: create و update پنل در staging/production فقط HTTPS و TLS verification فعال را می‌پذیرند.

F029 و F030 حفظ و تأیید شدند: PanelAdapter lifecycle متد close دارد، Sanaei client بسته می‌شود، و health job خطای واقعی را در last_health_error ذخیره می‌کند.

F031 تکمیل شد: downgrade migration اولیه دیگر drop_all مخرب ندارد و fail-safe متوقف می‌شود تا database با downgrade حذف نشود.

F032 تکمیل و تست شد: upload به‌صورت محدود chunk-by-chunk خوانده می‌شود و magic bytes برای PNG/JPEG/PDF/WebP بررسی می‌شوند؛ فایل خالی و WebP جعلی تست regression دارند.

compile/AST، syntax اسکریپت‌ها و assertionهای source موفق شدند. اجرای واقعی PostgreSQL، migration، panel و browser در این محیط انجام نشد.
