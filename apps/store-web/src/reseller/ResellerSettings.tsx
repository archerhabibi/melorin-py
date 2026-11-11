import type { Rec } from '../types';
import { useEffect, useState } from 'react';
import { J, card, btn, inp, useGet } from './ResellerData.tsx';
import type { Json } from '../types';

export function Branding({
  coreFetch,
  base,
  storeId,
  notify,
}: {
  coreFetch?: Json;
  base?: Json;
  storeId?: Json;
  notify?: Json;
}) {
  const [b, setB] = useState({ title: '', primary_color: '#10233f', support_url: '' });
  const [msgs, setMsgs] = useState('{}');
  useEffect(() => {
    coreFetch(`/api/v1/stores/${storeId}`)
      .then((r: Json) => (r.ok ? r.json() : {}))
      .then((s: Json) => s.branding && setB((x) => ({ ...x, ...s.branding })));
  }, [storeId, coreFetch]);
  const save = async () => {
    let bot_messages;
    try {
      bot_messages = JSON.parse(msgs || '{}');
    } catch {
      return notify('پیام‌های ربات باید JSON معتبر باشند');
    }
    const body: Rec = { branding: b };
    if (msgs.trim() && msgs.trim() !== '{}') body.bot_messages = bot_messages;
    const r = await coreFetch(`${base}/branding`, { method: 'PATCH', headers: J, body: JSON.stringify(body) });
    notify(r.ok ? 'برندینگ ذخیره شد' : 'ذخیره ناموفق بود');
  };
  return (
    <div className={card}>
      <h4 className="font-extrabold">برندینگ فروشگاه</h4>
      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <label className="text-xs font-bold">
          عنوان
          <input
            className={`${inp} mt-1`}
            value={b.title || ''}
            onChange={(e) => setB({ ...b, title: e.target.value })}
          />
        </label>
        <label className="text-xs font-bold">
          رنگ اصلی
          <input
            type="color"
            className={`${inp} mt-1 h-11`}
            value={b.primary_color || '#10233f'}
            onChange={(e) => setB({ ...b, primary_color: e.target.value })}
          />
        </label>
        <label className="text-xs font-bold">
          لینک پشتیبانی
          <input
            dir="ltr"
            className={`${inp} mt-1`}
            value={b.support_url || ''}
            onChange={(e) => setB({ ...b, support_url: e.target.value })}
          />
        </label>
      </div>
      <label className="mt-3 block text-xs font-bold">
        پیام‌های ربات (JSON، اختیاری)
        <textarea
          dir="ltr"
          rows={3}
          className={`${inp} mt-1 latin`}
          value={msgs}
          onChange={(e) => setMsgs(e.target.value)}
        />
      </label>
      <button onClick={save} className={`${btn} mt-4`}>
        ذخیره
      </button>
    </div>
  );
}

export function PayConfig({ coreFetch, base, notify }: { coreFetch?: Json; base?: Json; notify?: Json }) {
  const [rows, reload] = useGet(coreFetch, `${base}/payment-config`);
  const cur = (rows || []).find((r: Json) => r.provider === 'manual_card');
  const [f, setF] = useState({ card_number: '', holder: '', bank: '', min_amount: '', max_amount: '', enabled: true });
  useEffect(() => {
    if (cur) setF((x) => ({ ...x, ...cur.public_config, enabled: cur.is_enabled }));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
  }, [rows]);
  const save = async () => {
    const { enabled, ...pub } = f;
    ['min_amount', 'max_amount'].forEach((k) => {
      (pub as Rec)[k] = (pub as Rec)[k] === '' ? undefined : Number((pub as Rec)[k]);
    });
    const r = await coreFetch(`${base}/payment-config/manual_card`, {
      method: 'PUT',
      headers: J,
      body: JSON.stringify({ is_enabled: enabled, public_config: pub }),
    });
    notify(r.ok ? 'اطلاعات کارت ذخیره شد' : 'ذخیره ناموفق بود');
    r.ok && reload();
  };
  const [zp, setZp] = useState('');
  const zcur = (rows || []).find((r: Json) => r.provider === 'zarinpal');
  const saveZp = async () => {
    const r = await coreFetch(`${base}/payment-config/zarinpal`, {
      method: 'PUT',
      headers: J,
      body: JSON.stringify({ is_enabled: true, public_config: {}, secret: { merchant_id: zp } }),
    });
    notify(r.ok ? 'درگاه ذخیره شد' : 'ذخیره ناموفق بود');
    r.ok && (setZp(''), reload());
  };
  const fld = (k: Json, l: Json, t?: Json) => (
    <label className="text-xs font-bold">
      {l}
      <input
        type={t || 'text'}
        dir="ltr"
        className={`${inp} mt-1`}
        value={(f as Rec)[k] ?? ''}
        onChange={(e) => setF({ ...f, [k]: e.target.value })}
      />
    </label>
  );
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className={card}>
        <h4 className="font-extrabold">کارت‌به‌کارت</h4>
        <div className="mt-3 grid gap-3">
          {fld('card_number', 'شماره کارت')}
          {fld('holder', 'صاحب کارت')}
          {fld('bank', 'بانک')}
          <div className="grid grid-cols-2 gap-3">
            {fld('min_amount', 'حداقل مبلغ', 'number')}
            {fld('max_amount', 'حداکثر مبلغ', 'number')}
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={f.enabled} onChange={(e) => setF({ ...f, enabled: e.target.checked })} />
            فعال
          </label>
        </div>
        <button onClick={save} className={`${btn} mt-4`}>
          ذخیره
        </button>
      </div>
      <div className={card}>
        <h4 className="font-extrabold">درگاه زرین‌پال</h4>
        <p className="mt-2 text-xs text-muted">
          وضعیت: {zcur ? (zcur.has_secret ? 'merchant ID ثبت شده' : 'بدون secret') : 'تنظیم نشده'} (مقدار ثبت‌شده هرگز
          نمایش داده نمی‌شود)
        </p>
        <input
          dir="ltr"
          className={`${inp} mt-3`}
          placeholder="Merchant ID جدید"
          value={zp}
          onChange={(e) => setZp(e.target.value)}
        />
        <button disabled={!zp} onClick={saveZp} className={`${btn} mt-3`}>
          ذخیره
        </button>
      </div>
    </div>
  );
}

export async function errOf(r: Json, fallback: Json) {
  try {
    const d = await r.json();
    return (
      d?.error?.message ||
      (typeof d?.detail === 'string' ? d.detail : Array.isArray(d?.detail) ? 'اطلاعات واردشده معتبر نیست.' : '') ||
      fallback
    );
  } catch {
    return fallback;
  }
}
export const DOMAIN_RE = /^(?!-)([a-z0-9-]{1,63}\.)+[a-z]{2,24}$/i;
export const TOKEN_RE = /^\d{6,15}:[A-Za-z0-9_-]{30,64}$/;
export const cleanDomain = (v: Json) =>
  v
    .trim()
    .replace(/^[a-z]+:\/\//i, '')
    .split(/[/?#]/)[0]
    .replace(/\.$/, '')
    .toLowerCase();
