# تکمیل F002 تا F005 ملورین

F002 تا F005 اکنون به سورس واقعی Store Web و Admin Web متصل شدند. هر دو اپ دارای entrypoint واقعی Vite/React، manifest و lockfile، Dockerfile production، Nginx با SPA fallback، proxy هم‌مبدأ `/api` و متغیر اختیاری `VITE_MELORIN_API_URL` برای توسعه split-host هستند. Compose هر دو Web را از ریشه repository build می‌کند و Caddy دامنه اصلی را به Store Web، دامنه ادمین را به Admin Web و `/api/*` را به Core API می‌فرستد. CI نیز build هر دو npm و Docker هر دو Web را اجرا می‌کند.

راستی‌آزمایی: compile پایتون، syntax فایل‌های JavaScript پیکربندی، وجود manifestها، مسیرهای Caddy و بررسی متنی Compose موفق بود. npm، Docker و اجرای زنده مرورگر/API در این محیط موجود نبودند؛ بنابراین CI در اجرای واقعی نقش gate را دارد.
