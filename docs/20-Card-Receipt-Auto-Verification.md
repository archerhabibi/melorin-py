# Card-to-card receipt auto verification / تأیید خودکار رسید کارت‌به‌کارت

Branch: `feat/auto-card-receipt-verification` · Migration `0032_bank_sms_auto_verify`

## English

### Idea
A receipt screenshot can be forged; the deposit SMS the bank sends to the store owner's phone cannot. The owner's phone
forwards every bank SMS to Core. Core parses it, stores it once, and pays the matching customer receipt: the wallet is
credited through the normal `mark_succeeded` path (row locks + ledger idempotency key), so a duplicate SMS, a retry or a
race can never credit twice. Anything that is not 100% unambiguous stays in the manual review queue - Core never guesses
with money.

### Flow
1. Customer creates a wallet top-up (`manual_card`), pays by card-to-card, uploads the receipt **and types the time printed
   on it** (`paid_at`, optional `source_card_last4`, `reference`).
2. The bank SMS arrives at `POST /api/v1/payments/bank-sms/{store_id}` (header `X-Webhook-Token` or `Authorization: Bearer`).
3. Core matches by: same amount (Rial; IRT x 10) · SMS time not before the request and inside `window_minutes` ·
   receipt time equals SMS time within `time_tolerance_minutes` (+59 s, minute resolution) · exactly one candidate
   (or a strictly closest claimed time). Otherwise: `ambiguous` (admin/reseller is notified) or `unmatched`.
4. Order of arrival does not matter: receipt-then-SMS is matched on ingest, SMS-then-receipt is matched when the receipt is
   uploaded, and the worker job `bank_sms_reconcile` re-checks open deposits periodically.

### SMS format (Qarz al-Hasaneh Mehr Iran, also generic core-banking)
```
302570009152325001      serial / tracking number
1,500,000+              signed amount in Rial (+ deposit, - withdrawal)
1405/8/2-22:50          Jalali date-time, Tehran time
مانده:107,923,032       balance
```
Persian/Arabic digits and separators are normalized; line order and extra lines are tolerated. Withdrawals and unparsable
texts are stored but never matched. A balance that does not follow from the previous SMS raises a *balance gap* warning
(an SMS was probably missed).

### Setup (owner)
1. Admin panel -> Payments -> "تأیید خودکار با پیامک بانک" (reseller: panel tab "تأیید خودکار بانک"). Save once: the
   webhook token is shown **once** (only its SHA-256 is stored). Rotating it revokes the old one.
2. On the phone that receives the bank SMS install an SMS-forwarder app and add a webhook:
   `POST https://<your-domain>/api/v1/payments/bank-sms/<store_id>` · header `X-Webhook-Token: <token>` ·
   JSON body `{"text": "<sms body>", "sender": "<sender>"}` (form-encoded `text=`/`message=`/`body=` also works).
3. Optionally restrict `senders`, set `max_auto_amount_rial`, tune the window. Switch "شارژ خودکار" on.
   With it off, Core only *suggests* matches and a human confirms.

### Security notes and known limit
- Webhook: token compared in constant time, one generic 401 for every failure, rate limited (120/min), body capped.
- Idempotent: every SMS has a fingerprint (serial + amount + time); forwarder retries create no second row or credit.
- Every decision is audited (`payment.bank_sms_matched`, `bank_sms.source_saved`, `bank_sms.token_rotated`).
- **Limit:** a bank SMS does not contain the payer. Two different people paying the same amount in the same minute is
  resolved only by the claimed time; if only one of them uploaded a receipt, that receipt is paid. Keep
  `require_claimed_time` on, set `max_auto_amount_rial`, and use unique amounts or small windows for high-value stores.

## فارسی

### ایده
عکس رسید قابل جعل است، اما پیامک واریزی که بانک برای گوشی صاحب فروشگاه می‌فرستد نه. گوشی صاحب فروشگاه هر پیامک بانک را به
Core می‌فرستد؛ Core آن را تحلیل و فقط یک بار ذخیره می‌کند و به رسید مشتریِ منطبق وصل می‌کند و کیف پول را از مسیر
معمولی `mark_succeeded` (قفل ردیف + کلید یکتایی دفتر) شارژ می‌کند؛ پس پیامک تکراری، تلاش مجدد یا رقابت هم‌زمان هرگز دو بار
شارژ نمی‌کند. هر چیزی که صددرصد بدون ابهام نباشد در صف بررسی دستی می‌ماند: با پول حدس زده نمی‌شود.

### جریان
۱. مشتری شارژ کیف پول (کارت‌به‌کارت) می‌سازد، پرداخت می‌کند، رسید را آپلود می‌کند و **زمانِ چاپ‌شده روی رسید** را وارد می‌کند
   (اختیاری: ۴ رقم آخر کارت مبدأ و شماره مرجع).
۲. پیامک بانک به `POST /api/v1/payments/bank-sms/{store_id}` می‌رسد (هدر `X-Webhook-Token`).
۳. شرط‌های تطبیق: مبلغ برابر (ریال؛ تومان × ۱۰) · زمان پیامک بعد از درخواست و داخل بازه · زمان رسید با زمان پیامک در حد
   تلورانس برابر · فقط یک کاندید (یا نزدیک‌ترین زمان اعلامی به‌طور یکتا). در غیر این صورت «نیاز به بررسی» یا «در انتظار رسید».
۴. ترتیب رسیدن مهم نیست (اول رسید یا اول پیامک)؛ کار زمان‌بندی‌شده‌ی `bank_sms_reconcile` هم واریزهای باز را دوباره بررسی می‌کند.

### نمونه‌ی پیامک (قرض‌الحسنه مهر ایران)
سریال `302570009152325001` · مبلغ `1,500,000+` ریال · زمان `1405/8/2-22:50` (تهران) · مانده `107,923,032`.
رسید متناظر: «۱٬۵۰۰٬۰۰۰ ریال — ۲۲:۵۰ شنبه ۲ آبان ۱۴۰۵ — کارت به کارت».

### راه‌اندازی
۱. پنل ادمین ← پرداخت‌ها ← «تأیید خودکار کارت‌به‌کارت با پیامک بانک» (نماینده: تب «تأیید خودکار بانک»). با اولین ذخیره،
   توکن وبهوک **فقط یک‌بار** نمایش داده می‌شود (فقط هش آن ذخیره می‌شود).
۲. در گوشی‌ای که پیامک بانک را می‌گیرد، یک برنامه‌ی SMS Forwarder نصب و وبهوک POST بسازید:
   آدرس `https://دامنه‌ی-شما/api/v1/payments/bank-sms/<store_id>` · هدر `X-Webhook-Token` · بدنه‌ی JSON با کلیدهای `text` و `sender`.
۳. در صورت نیاز فرستنده‌ی مجاز، سقف مبلغ خودکار و بازه را تنظیم و «شارژ خودکار» را روشن کنید (خاموش = فقط پیشنهاد).

### نکات امنیتی و محدودیت
توکن با مقایسه‌ی زمان‌ثابت بررسی می‌شود و برای هر خطا یک پاسخ ۴۰۱ یکسان برمی‌گردد؛ نرخ درخواست محدود است؛ هر پیامک اثر انگشت
دارد و ارسال مجدد اثری ندارد؛ همه‌ی تصمیم‌ها در audit ثبت می‌شود. **محدودیت:** پیامک بانک نام واریزکننده را ندارد؛ اگر دو نفر در یک
دقیقه مبلغ یکسان بپردازند فقط «زمان اعلامی» تفکیک می‌کند و اگر فقط یکی رسید بفرستد همان شارژ می‌شود. گزینه‌ی «زمان رسید الزامی»
را روشن نگه دارید و برای فروشگاه‌های پرمبلغ سقف شارژ خودکار بگذارید.
