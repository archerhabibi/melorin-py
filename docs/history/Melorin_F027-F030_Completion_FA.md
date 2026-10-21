# تکمیل F027 تا F030 ملورین

F027 اصلاح شد: برای هر کاربر فقط یک درخواست نمایندگی pending با partial unique index دیتابیس مجاز است؛ approval با row lock و بررسی فروشگاه موجود انجام می‌شود و migration مستقل اضافه شد.

F028 اصلاح شد: در staging/production ساخت Panel با URL غیر HTTPS یا `verify_tls=false` رد می‌شود؛ TLS verification پیش‌فرض adapterها حفظ شده است.

F029 اصلاح شد: lifecycle متد `close()` به PanelAdapter اضافه شد؛ Sanaei client واقعاً بسته می‌شود و health job در مسیر finally آن را می‌بندد. Adapterهای بدون client نیز قرارداد close دارند.

F030 اصلاح شد: خطای health دیگر دور ریخته نمی‌شود و در `last_health_error` ذخیره می‌گردد؛ حالت healthy خطای قبلی را پاک می‌کند.

compile/AST، syntax اسکریپت‌ها و assertionهای source موفق شدند. اجرای واقعی PostgreSQL migration، panel و TLS در این محیط انجام نشد.
