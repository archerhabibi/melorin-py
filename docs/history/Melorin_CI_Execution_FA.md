# اجرای CI ملورین

اجرای واقعی CI در این sandbox تلاش شد، اما Node.js 22 موجود است و npm و Docker موجود نیستند؛ بنابراین buildهای npm و Docker اصلاً شروع نشدند و نتیجه ساختگی اعلام نمی‌شود.

خطاهای CI پیدا و اصلاح شدند:
- build API با context ریشه و `-f apps/api/Dockerfile` اجرا می‌شود.
- `working-directory: ../..` نادرست از GitHub Actions حذف شد.
- buildهای Docker مربوط به Store Web و Admin Web با context ریشه هماهنگ شدند.
- نصب dependencyهای Web با `npm install --include=dev --no-audit --no-fund` انجام می‌شود تا lockfile اولیه که فقط root metadata داشت قبل از build اصلاح شود و در `npm ci` شکست نخورد.
- routing در Compose و Caddy بین `store_web`، `admin_web` و `api` هماهنگ است.

gateهای قابل اجرای محلی شامل compile پایتون، syntax فایل‌های JavaScript، سازگاری ریشه lockfile، syntax اسکریپت‌ها و assertionهای CI/Caddy موفق شدند. gate نهایی runtime باید در GitHub Actions اجرا شود چون npm و Docker اینجا در دسترس نیستند.
