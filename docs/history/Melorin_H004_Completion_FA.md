# تکمیل H004: reproducible Web dependencies

## نتیجه
H004 اصلاح شد. CI دیگر package manifest یا lockfile را mutate نمی‌کند؛ هر دو Web فقط با `npm ci --include=dev --ignore-scripts` از lockfile commit‌شده نصب می‌شوند. dependency versions مستقیم pin شده‌اند، `packageManager: npm@10.8.2` ثبت شده، و lockfile gate وجود همه direct dependencyها را در lock graph بررسی می‌کند.

## تغییرات
- حذف تمام `npm install` و `npm install --package-lock-only` از CI.
- حفظ `npm ci` به‌عنوان تنها مسیر نصب CI.
- تکمیل root و direct package entries در lockfileهای Store/Admin Web.
- اضافه‌شدن package manager pin و lockfile graph check.

## شواهد
lockfile check، compile/AST، shell syntax و assertion CI موفق شدند. npm و registry در این محیط موجود نیستند، بنابراین اجرای واقعی `npm ci` و Vite build هنوز باید در GitHub Actions/staging تأیید شود؛ lockfileها در CI دیگر خودکار بازنویسی نمی‌شوند.
