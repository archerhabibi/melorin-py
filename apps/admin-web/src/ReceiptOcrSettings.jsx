// ReceiptOcrSettings.jsx — Admin > Settings > "خواندن خودکار رسید (OCR)"
// Chooses how Core reads a card-to-card receipt image (time, amount, source-card tail, reference) so the customer types
// nothing. What is read is only a *claim*: the bank deposit SMS stays the proof, and a read amount that differs from the
// request blocks auto-pay. The API key is write-only: the server stores it encrypted and never sends it back.

import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Check, ChevronDown, Cpu, Eye, FlaskConical, Power, ScanText, Sparkles } from 'lucide-react';
import { authFetch } from './api.js';
import { Field, Secret } from './kit.jsx';

const ENGINES = [
  {
    id: 'vision',
    Icon: Eye,
    title: 'هوش مصنوعی بینایی',
    tag: 'پیشنهادی برای محیط واقعی',
    traits: [
      ['دقت', 'بسیار بالا؛ هر بانک و هر فونت', 'ok'],
      ['حریم خصوصی', 'تصویر رسید به سرویس بیرونی ارسال می‌شود', 'wn'],
      ['هزینه', 'به‌ازای هر رسید (چند ده تومان)', 'mu'],
    ],
  },
  {
    id: 'tesseract',
    Icon: Cpu,
    title: 'Tesseract (محلی)',
    tag: 'رایگان و آفلاین',
    traits: [
      ['دقت', 'متوسط؛ به فونت اپ بانک وابسته است', 'wn'],
      ['حریم خصوصی', 'همه‌چیز روی سرور خودتان می‌ماند', 'ok'],
      ['هزینه', 'رایگان', 'ok'],
    ],
  },
  {
    id: 'auto',
    Icon: Sparkles,
    title: 'خودکار',
    tag: 'انتخاب هوشمند',
    traits: [
      ['رفتار', 'اگر کلید API باشد بینایی، وگرنه Tesseract', 'in'],
      ['دقت', 'بسته به موتور انتخاب‌شده', 'mu'],
      ['هزینه', 'فقط وقتی کلید دارید', 'mu'],
    ],
  },
  {
    id: 'off',
    Icon: Power,
    title: 'خاموش',
    tag: 'همه‌ی رسیدها دستی',
    traits: [
      ['رفتار', 'رسید خوانده نمی‌شود', 'mu'],
      ['تطبیق', 'فقط مبلغ و بازه‌ی زمانی پیامک', 'wn'],
      ['هزینه', 'ندارد', 'ok'],
    ],
  },
];
const ENGINE_NAME = { vision: 'هوش مصنوعی بینایی', tesseract: 'Tesseract (محلی)' };
const SOURCE = {
  panel: 'ذخیره‌شده در پنل',
  env: 'از متغیر محیطی سرور (هنوز در پنل ذخیره نشده)',
};

function Pipeline() {
  const steps = [
    ['۱', 'مشتری فقط عکس رسید را می‌فرستد'],
    ['۲', 'مبلغ، زمان، ۴ رقم کارت و مرجع خوانده می‌شود'],
    ['۳', 'پیامک واریز بانک مبنای تأیید است، نه عکس'],
    ['۴', 'هر چیز مبهم به بررسی دستی می‌رود'],
  ];
  return (
    <ol className="grid gap-2 sm:grid-cols-4">
      {steps.map(([n, t]) => (
        <li key={n} className="flex items-start gap-2 rounded-xl bg-[var(--bg2)] p-3 text-xs leading-6">
          <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-[var(--btn)] text-[11px] font-extrabold text-[var(--btntx)]">
            {n}
          </span>
          {t}
        </li>
      ))}
    </ol>
  );
}

export default function ReceiptOcrSettings({ api, toast }) {
  const call = useCallback((p, o = {}) => authFetch(api.base, p, o), [api.base]);
  const [cfg, setCfg] = useState(null);
  const [form, setForm] = useState(null);
  const [keyInput, setKeyInput] = useState('');
  const [clearKey, setClearKey] = useState(false);
  const [busy, setBusy] = useState('');
  const [test, setTest] = useState(null);

  const apply = useCallback((d) => {
    setCfg(d);
    setForm({
      engine: d.engine,
      base_url: d.base_url,
      model: d.model,
      timeout_seconds: String(d.timeout_seconds),
      tesseract_lang: d.tesseract_lang,
    });
    setKeyInput('');
    setClearKey(false);
  }, []);
  const load = useCallback(
    () =>
      call('/api/v1/admin/integrations')
        .then((r) => (r.ok ? r.json() : Promise.reject()))
        .then((d) => apply(d.receipt_ocr))
        .catch(() => toast('دریافت تنظیمات خواندن رسید ناموفق بود')),
    [apply, call, toast],
  );
  useEffect(() => {
    load();
  }, [load]);

  if (!cfg || !form) return <div className="card skel h-32" />;

  const set = (k) => (v) => {
    setForm({ ...form, [k]: v });
    setTest(null);
  };
  const keyWillExist = clearKey ? !!keyInput : cfg.api_key_set || !!keyInput;
  const needsKey = form.engine === 'vision' && !keyWillExist;
  const timeout = Number(String(form.timeout_seconds).replace(/\D/g, ''));
  const timeoutBad = !(timeout >= 5 && timeout <= 90);
  const httpsBad = !/^https:\/\/[^/\s]+/.test(form.base_url.trim());
  const dirty =
    form.engine !== cfg.engine ||
    form.base_url !== cfg.base_url ||
    form.model !== cfg.model ||
    form.tesseract_lang !== cfg.tesseract_lang ||
    String(form.timeout_seconds) !== String(cfg.timeout_seconds) ||
    !!keyInput ||
    clearKey;
  const tesseractMissing = !cfg.tesseract_available;

  const save = async () => {
    setBusy('save');
    const body = { ...form, timeout_seconds: timeout, base_url: form.base_url.trim(), model: form.model.trim() };
    if (keyInput) body.api_key = keyInput.trim();
    else if (clearKey) body.api_key = '';
    try {
      const r = await call('/api/v1/admin/integrations/receipt-ocr', { method: 'PUT', body: JSON.stringify(body) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) return toast(d?.error?.message || 'ذخیره ناموفق بود');
      toast('تنظیمات خواندن رسید ذخیره شد');
      apply(d);
      setTest(null);
    } catch {
      toast('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy('');
    }
  };
  const runTest = async () => {
    setBusy('test');
    try {
      const r = await call('/api/v1/admin/integrations/receipt-ocr/test', { method: 'POST', body: '{}' });
      const d = await r.json().catch(() => ({}));
      setTest(r.ok ? d : { ok: false, error: d?.error?.message || 'آزمایش انجام نشد' });
    } catch {
      setTest({ ok: false, error: 'ارتباط با سرور برقرار نشد' });
    } finally {
      setBusy('');
    }
  };

  const active = cfg.active_engine;
  return (
    <section className="card space-y-5 p-5" aria-labelledby="ocr-title">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="ocr-title" className="flex items-center gap-2 font-extrabold">
          <ScanText size={18} /> خواندن خودکار رسید (OCR)
        </h3>
        <span className={`badge ${active ? 'b-ok' : 'b-mu'}`} role="status">
          {active ? `فعال: ${ENGINE_NAME[active]}` : 'غیرفعال'}
        </span>
      </div>
      <p className="text-xs leading-7 text-[var(--mu)]">
        منبع تنظیم فعلی: {SOURCE[cfg.source] || cfg.source}. تغییرات بلافاصله و بدون راه‌اندازی مجدد اعمال می‌شود.
      </p>
      <Pipeline />

      <div role="radiogroup" aria-label="موتور خواندن رسید" className="grid gap-3 md:grid-cols-2">
        {ENGINES.map((e) => {
          const on = form.engine === e.id;
          return (
            <button
              key={e.id}
              type="button"
              role="radio"
              aria-checked={on}
              onClick={() => set('engine')(e.id)}
              className={`rounded-xl border p-3 text-start transition ${on ? 'border-[var(--ac)] bg-[var(--bg2)] ring-1 ring-[var(--ac)]' : 'border-[var(--ln)] hover:bg-[var(--bg2)]'}`}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 text-sm font-extrabold">
                  <e.Icon size={16} /> {e.title}
                </span>
                {on && <Check size={16} aria-hidden="true" />}
              </span>
              <span className="mt-0.5 block text-[11px] text-[var(--mu)]">{e.tag}</span>
              <span className="mt-2 grid gap-1">
                {e.traits.map(([k, v, t]) => (
                  <span key={k} className="flex items-start gap-2 text-[11px] leading-5">
                    <span className="w-16 shrink-0 font-bold text-[var(--mu)]">{k}</span>
                    <span style={{ color: `var(--${t}, inherit)` }}>{v}</span>
                  </span>
                ))}
              </span>
            </button>
          );
        })}
      </div>

      {form.engine === 'tesseract' && tesseractMissing && (
        <p className="flex items-start gap-2 rounded-xl border border-[var(--wn)] p-3 text-xs leading-6" role="alert">
          <AlertTriangle size={15} className="mt-0.5 shrink-0" />
          tesseract روی این سرور نصب نیست؛ با این انتخاب رسیدها خوانده نمی‌شوند و همه به بررسی دستی می‌روند.
        </p>
      )}
      {(form.engine === 'vision' || form.engine === 'auto') && (
        <div className="space-y-3 rounded-xl border border-[var(--ln)] p-4">
          <h4 className="text-xs font-extrabold">تنظیمات هوش مصنوعی بینایی</h4>
          <div className="grid gap-3 md:grid-cols-2">
            <Field
              label="کلید API"
              error={needsKey ? 'برای موتور «بینایی» کلید API لازم است.' : ''}
              hint={
                cfg.api_key_set && !clearKey
                  ? 'کلید ذخیره شده است و دوباره نمایش داده نمی‌شود. برای تعویض، کلید جدید را وارد کنید.'
                  : 'کلید رمزنگاری‌شده ذخیره می‌شود و هرگز به مرورگر برنمی‌گردد.'
              }
            >
              <Secret
                value={keyInput}
                onChange={setKeyInput}
                placeholder={cfg.api_key_set && !clearKey ? '•••••••• (ذخیره‌شده)' : 'sk-ant-…'}
              />
            </Field>
            <Field label="مدل" hint="مدل بینایی سبک برای رسید کافی و ارزان است.">
              <input
                dir="ltr"
                className="inp font-mono text-xs"
                value={form.model}
                onChange={(e) => set('model')(e.target.value)}
              />
            </Field>
          </div>
          {cfg.api_key_set && (
            <label className="flex items-center gap-2 text-xs">
              <input type="checkbox" checked={clearKey} onChange={(e) => setClearKey(e.target.checked)} />
              حذف کلید ذخیره‌شده
            </label>
          )}
          <details className="group">
            <summary className="flex cursor-pointer list-none items-center gap-1 text-xs font-bold text-[var(--mu)]">
              تنظیمات پیشرفته <ChevronDown size={14} className="transition group-open:rotate-180" />
            </summary>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <Field
                label="آدرس سرویس"
                error={httpsBad ? 'آدرس باید با https شروع شود.' : ''}
                hint="فقط اگر از پروکسی/سرویس سازگار استفاده می‌کنید تغییر دهید."
              >
                <input
                  dir="ltr"
                  className="inp font-mono text-xs"
                  value={form.base_url}
                  onChange={(e) => set('base_url')(e.target.value)}
                />
              </Field>
              <Field
                label="مهلت پاسخ (ثانیه)"
                error={timeoutBad ? 'عددی بین ۵ تا ۹۰.' : ''}
                hint="با کندی سرویس، رسید به بررسی دستی می‌رود و آپلود مشتری هرگز متوقف نمی‌شود."
              >
                <input
                  dir="ltr"
                  inputMode="numeric"
                  className="inp"
                  value={form.timeout_seconds}
                  onChange={(e) => set('timeout_seconds')(e.target.value)}
                />
              </Field>
            </div>
          </details>
          <p className="rounded-lg bg-[var(--bg2)] p-2 text-[11px] leading-6">
            <b>حریم خصوصی:</b> با این موتور عکس رسید برای سرویس بینایی ارسال می‌شود. رسید شامل نام و ۴ رقم کارت است؛ اگر
            این برای شما مناسب نیست از Tesseract استفاده کنید.
          </p>
        </div>
      )}
      {(form.engine === 'tesseract' || form.engine === 'auto') && (
        <Field label="زبان‌های Tesseract" hint="پیش‌فرض fas+eng (فارسی و انگلیسی).">
          <input
            dir="ltr"
            className="inp max-w-xs font-mono text-xs"
            value={form.tesseract_lang}
            onChange={(e) => set('tesseract_lang')(e.target.value)}
          />
        </Field>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button
          className="btn"
          disabled={busy === 'save' || !dirty || needsKey || timeoutBad || httpsBad}
          onClick={save}
        >
          {busy === 'save' ? 'در حال ذخیره...' : 'ذخیره'}
        </button>
        <button className="btn btn-g" disabled={busy === 'test' || dirty} onClick={runTest}>
          <FlaskConical size={14} /> {busy === 'test' ? 'در حال آزمایش...' : 'آزمایش اتصال'}
        </button>
        {dirty && <span className="text-[11px] text-[var(--mu)]">برای آزمایش، ابتدا تغییرات را ذخیره کنید.</span>}
      </div>
      {test && (
        <p
          className={`rounded-xl border p-3 text-xs leading-6 ${test.ok ? 'border-[var(--ok)]' : 'border-[var(--bd)]'}`}
          role="status"
        >
          {test.ok ? `✅ ${test.detail || 'آماده است.'}` : `⚠️ ${test.error}`}
        </p>
      )}

      <details className="group rounded-xl border border-[var(--ln)]">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-2 p-4 text-sm font-bold">
          <span>این تنظیمات دقیقاً چه کاری می‌کنند؟</span>
          <ChevronDown size={16} className="transition group-open:rotate-180" />
        </summary>
        <div className="space-y-2 border-t border-[var(--ln)] p-4 text-xs leading-7 text-[var(--mu)]">
          <p>
            موتور فقط <b>ادعای رسید</b> را می‌خواند؛ هرگز خودش پول را تأیید نمی‌کند. اگر مبلغ خوانده‌شده با مبلغ درخواست
            یکی نباشد، آن رسید از تأیید خودکار و تأیید موقت کنار گذاشته می‌شود.
          </p>
          <p>
            زمان خوانده‌شده در آینده یا خطای موتور هرگز آپلود مشتری را متوقف نمی‌کند؛ رسید در این حالت به بررسی دستی
            می‌رود و فقط یک فیلد «زمان رسید» به مشتری نشان داده می‌شود.
          </p>
          <p>
            روی فیش نمونه‌ی بلوبانک، Tesseract فارسی مبلغ را اشتباه و ساعت و مرجع را نخواند؛ برای محیط واقعی موتور
            بینایی توصیه می‌شود.
          </p>
        </div>
      </details>
    </section>
  );
}
