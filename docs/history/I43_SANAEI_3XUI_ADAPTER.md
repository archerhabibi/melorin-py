# I43 — تکمیل Adapter پنل سنایی (3x-ui)

مرجع: https://docs.sanaei.dev/docs/reference/api/ ، کد `web/controller/client.go` در MHSanaei/3x-ui، و `SanaeiDriver.php` در archerhabibi/melorin-public.

## مشکلات نسخه‌ی قبلی
- فقط API قدیمی (inbound-based) پشتیبانی می‌شد؛ در 3x-ui نسخه‌ی 3 کلاینت‌ها زیر `/panel/api/clients/*` هستند.
- `settings` اینباند با `json.loads` خوانده می‌شد؛ در v3 به‌صورت آبجکت nested برمی‌گردد → crash.
- `tgId: ""` ارسال می‌شد؛ در Go نوع `int64` است → خطای `cannot unmarshal string ... tgId`.
- 404 به‌عنوان «session منقضی» تلقی می‌شد و re-login بی‌مورد انجام می‌شد.
- health روی `POST /server/status` بود (در v3 مسیر `GET /panel/api/server/status`).
- API Token (Bearer) پشتیبانی نمی‌شد؛ redirectها کنترل نمی‌شدند؛ نبودِ `sub_base_url` باعث کلاینت یتیم روی پنل می‌شد.
- route سلامت ادمین adapter را close نمی‌کرد (نشت connection).
- فرم ادمین `config` پنل را اصلاً ارسال نمی‌کرد.

## رفتار جدید
- `api_style`: `auto` (پیش‌فرض، probe یک‌باره) | `v3` | `legacy`.
- احراز هویت: `{"api_token": "..."}` (توصیه‌شده) یا `{"username","password"}` با re-login فقط روی 401.
- v3: add/get/traffic/links/update(read→merge→full replace با تبدیل ClientRecord به model.Client)/del/resetTraffic.
- چند inbound همزمان (`inbound_ids`) یا کپی از کلاینت نمونه (`template_username`، کش ۵ دقیقه، miss کش نمی‌شود).
- `sub_base_url` اجباری و قبل از هر نوشتن چک می‌شود. تمدید subId را عوض نمی‌کند.
- خطاها: timeout = UNKNOWN، 5xx/429 = TRANSIENT، بقیه PERMANENT. redirect دنبال نمی‌شود.
- متدهای اضافه: `reset_traffic`, `server_status`.
- اعتبارسنجی ساخت پنل سنایی در `CreatePanel` (credentials، sub_base_url، inbound_ids/template).

## نمونه تنظیم
```json
base_url:    "https://panel.example.com:2053/kharej"
credentials: {"api_token": "..."}
config:      {"inbound_ids": [3, 5], "sub_base_url": "https://sub.example.com:2096/sub", "flow": "xtls-rprx-vision"}
```

## تست
`apps/api/tests/test_sanaei_adapter_contract.py` — ۱۱ تست contract روی پنل جعلی v3 و legacy (چرخه‌ی کامل، idempotency، template، خطاها، redirect، re-login، settings رشته/آبجکت).
هنوز روی پنل واقعی 3x-ui اجرا نشده.
