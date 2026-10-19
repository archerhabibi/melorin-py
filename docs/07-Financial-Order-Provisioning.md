# قوانین مالی، سفارش و Provisioning
## مدل مالی
Wallet هر User در هر Store مستقل است و Currency روی هر Store قابل تنظیم است. وقتی مشتری به نماینده تبدیل می‌شود، همان کیف پول قبلی او در Main Store (با همان موجودی) برای هزینهٔ نمایندگی استفاده می‌شود و فقط Debt Limit به آن اضافه می‌شود تا هزینهٔ فروش‌های نمایندگی بتواند آن را تا -Debt Limit منفی کند؛ خریدهای شخصی مالک همچنان از زیر صفر نمی‌روند. کیف پول مالک در فروشگاه نمایندگی خودش (و هر فروشگاه دیگر) کیف پولی مستقل و بدون ارتباط است. انتقال پول بین Resellerها ممنوع. Ledger مرجع حقیقت است؛ تمام تغییرات append-only ثبت می‌شوند. متقاضی نمایندگی باید قبل از فعال‌سازی، مشتری/عضو Main Store باشد.
## قیمت‌ها
Main Price فروش مستقیم؛ Reseller Price هزینه نماینده در Main Store؛ Customer Price قیمت نماینده برای مشتری خودش. Order باید snapshot قیمت‌ها، تخفیف، مبلغ نهایی و Currency داشته باشد.
## قانون Wallet-first و شارژ Store-scoped
- هر خرید در هر Store صرفاً از Wallet همان Store پرداخت می‌شود؛ checkout مستقیم با درگاه برای سفارش مجاز نیست.
- درگاه یا پرداخت دستی فقط Wallet همان Store را شارژ می‌کند.
- مشتری Reseller A، Wallet خود را در Store A شارژ می‌کند و وجه به درگاه/حساب پرداخت متعلق به Reseller A می‌رود؛ وجه نباید به Main Store یا Reseller دیگر هدایت شود.
- Reseller مجاز است Wallet مشتریان خودش را شارژ کند. عملیات شارژ دستی باید Ledger، مرجع/دلیل و Audit مناسب داشته باشد؛ اگر شارژ از پرداخت بیرونی ناشی می‌شود، Payment باید تأیید شده باشد.
## خرید Reseller
1. احراز عضویت مشتری در Store مربوط و اعتبارسنجی Product/Store.
2. محاسبه Customer Price و Coupon/Discount فقط در Core.
3. بررسی Customer Wallet و Debt Limit نماینده پیش از هر Debit.
4. در یک DB transaction، Debit مشتری در Store نماینده، ثبت بدهی/اعتبار نماینده در Main Store، Order و Ledger entries هماهنگ شوند.
5. پس از Commit، Outbox/ARQ Job برای Provisioning.
اگر نماینده به Debt Limit رسیده باشد، خرید قبل از Debit مشتری رد شود. فقط همان Reseller Store متوقف شود.
## Debt Limit
تصمیم اجرایی: `debt_limit` به‌صورت حداکثر قدرمطلق بدهی مثبت ذخیره و فروش وقتی `balance <= -debt_limit` باشد متوقف شود. شرط باید در تراکنش اتمیک بررسی شود. هشدار نزدیک حد/رسیدن به حد و پیام به مشتری الزامی است.
## Atomicity & Compensation
عملیات DB در transaction؛ فراخوانی شبکه‌ای به Gateway/Panel داخل transaction طولانی ممنوع. Provisioning با State Machine، Outbox، Retry و Compensation. اگر Provisioning شکست خورد، Debitها تا بررسی باقی می‌مانند و Refund خودکار ممنوع. Admin می‌تواند Retry، اتصال Account موجود، Refund یا credit انتخاب کند؛ همه Audit و Ledger reversal دارند.
## Idempotency
Payment Request/Callback، Wallet Charge/Debit، Order، Provisioning/Retry، Refund، Commission و Notification دارای کلید/مرجع یکتا باشند. Callback تکراری، Account یا Commission/Refund تکراری ایجاد نکند.
## State Machines
Order: Pending → Payment Pending → Paid → Processing → Provisioning → Completed؛ حالات جانبی Payment Failed، Provisioning Failed، Cancelled، Refund Pending، Refunded، Manual Review. Payment و VPN Account Lifecycle مستقل‌اند.
## Provisioning
انتخاب Server با سازگاری Product، health، capacity و سپس کمترین اکانت فعال. Retry با backoff و سقف تنظیم‌پذیر. پس از شکست: Manual Review. Reconciliation اختلاف DB/Panel را ثبت کند و وضعیت مالی را خودکار تغییر ندهد. تمدید یک قانون Core است (`vpn/renewal.py`، جزئیات در `docs/13-Renewal-Core-Design.md`): فقط تا ۱۰ روز پس از انقضا، فقط با همان پکیج اکانت، با قیمت فعلی پکیج در بسته فروش اولیه، و نتیجه دقیقاً برابر یک اکانت جدید همان پکیج است (زمان و حجم جایگزین می‌شود، اضافه نمی‌شود).
## Coupon
Admin یا Reseller مجاز می‌تواند Coupon بسازد. Coupon به یک Store یا دامنه‌ای که Admin صریحاً مجاز کرده محدود است؛ Reseller فقط در Store خودش Coupon می‌سازد. V1 به‌صورت پیش‌فرض Couponها را ترکیب نمی‌کند و Core یک Coupon معتبر را طبق قاعده مرکزی انتخاب/اعمال می‌کند. تخفیف از مبلغ واجد شرایط و سقف تنظیم‌شده تجاوز نمی‌کند. شروع/پایان، سقف مصرف کل و سقف هر مشتری قابل تنظیم است. Redemption و quota باید اتمیک باشند تا خرید هم‌زمان سقف را دور نزند.
## Referral
طرح کمیسیون/پاداش را Admin تنظیم می‌کند و مدل آن می‌تواند بر اساس طرح انتخاب شود. انتساب بر اساس اولین معرف ثبت‌شده است. کمیسیون درصدی بر مبلغ خالص پس از تخفیف محاسبه می‌شود، مگر طرح صریحاً مدل دیگری تعیین کند. Refund باعث Commission Reversal می‌شود؛ اگر کمیسیون خرج شده باشد، reversal در Ledger ثبت و بازیافت از کمیسیون‌های آتی به‌عنوان رفتار پیش‌فرض پیشنهاد می‌شود؛ سیاست بدهی/منفی‌شدن حساب معرف هنوز نیازمند تصمیم صریح است.
