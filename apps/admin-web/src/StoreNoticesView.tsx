// «اعلان‌ها» tab of the store hub (PG-06): when a store's customers are warned about low traffic. Moved out of panel operations:
// the setting belongs to one store, not to a panel. Also holds the store's own notice wording (vpn-notice-texts) and the
// owner's daily digest switch (vpn-digest), which had no screen before.
import { useCallback, useEffect, useState } from 'react';
import { authFetch } from './api.ts';
import { canWrite } from './adminAccess.ts';
import { Switch } from './kit.tsx';
import type { CallFn, Toast } from './types.ts';
import { asList, errMessage } from './adminHubTypes.ts';
import type { ErrorBody, HubApiProp, NoticeCfg, NoticeTextMeta, StoreRow } from './adminHubTypes.ts';

const DEFAULT_LEVELS_TEXT = '80, 90';
function NoticeLevels({
  call,
  toast,
  storeId,
  writable,
  onCfg,
}: {
  call: CallFn;
  toast: Toast;
  storeId: string;
  writable: boolean;
  onCfg: (c: NoticeCfg | null) => void;
}) {
  const [cfg, setCfg] = useState<NoticeCfg | null>(null);
  const [text, setText] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setCfg(null);
    if (!storeId) return;
    (async () => {
      try {
        const r = await call(`/api/v1/admin/stores/${storeId}/vpn-notices`);
        if (!r.ok) throw new Error(String(r.status));
        const j = await r.json();
        setCfg(j);
        onCfg(j);
        setText(j.traffic_low_levels.join(', '));
      } catch {
        toast('دریافت تنظیمات هشدار ناموفق بود');
      }
    })();
  }, [call, storeId, toast, onCfg]);

  const parse = () => {
    const parts = text.split(/[,،\s]+/).filter(Boolean);
    const nums = parts.map((x) => (/^\d+$/.test(x) ? Number(x) : NaN));
    return nums.some((n) => !(n >= 1 && n <= 99)) || nums.length > 4 ? null : nums;
  };

  const save = async (reset: boolean) => {
    const levels = reset ? null : parse();
    if (!reset && levels === null) {
      toast('حداکثر ۴ عدد صحیح بین ۱ تا ۹۹ وارد کنید (با کاما جدا کنید)');
      return;
    }
    setSaving(true);
    try {
      const r = await call(`/api/v1/admin/stores/${storeId}/vpn-notices`, {
        method: reset ? 'DELETE' : 'PUT',
        body: reset ? undefined : JSON.stringify({ traffic_low_levels: levels }),
      });
      if (!r.ok) throw new Error(((await r.json().catch(() => ({}))) as ErrorBody).error?.message || String(r.status));
      const j = await r.json();
      setCfg(j);
      onCfg(j);
      setText(j.traffic_low_levels.join(', '));
      toast('ذخیره شد');
    } catch (e) {
      toast(`ناموفق: ${errMessage(e)}`);
    }
    setSaving(false);
  };

  return (
    <div className="space-y-3">
      <p className="text-sm">
        مشتریان هر فروشگاه وقتی درصد مصرف حجم اکانتشان به این عددها رسید، یک‌بار پیام می‌گیرند. پیش‌فرض:{' '}
        {DEFAULT_LEVELS_TEXT}. لیست خالی یعنی این فروشگاه هشدار حجم نمی‌فرستد.
      </p>
      {cfg && (
        <div className="flex flex-wrap items-center gap-2">
          <input
            className="inp"
            dir="ltr"
            value={text}
            onChange={(e) => setText(e.target.value)}
            aria-label="درصدهای هشدار"
            placeholder={DEFAULT_LEVELS_TEXT}
          />
          <button className="btn" disabled={saving || !writable} onClick={() => save(false)}>
            ذخیره
          </button>
          <button className="btn btn-g" disabled={saving || !writable || cfg.is_default} onClick={() => save(true)}>
            بازگشت به پیش‌فرض
          </button>
          <span className="text-xs text-[var(--mu)]">
            {cfg.is_default ? 'پیش‌فرض سامانه' : 'تنظیم اختصاصی این فروشگاه'}
          </span>
        </div>
      )}
    </div>
  );
}

const KIND_LABEL: Record<string, string> = {
  vpn_expired: 'انقضای اکانت',
  vpn_near_expiry: 'نزدیک انقضا',
  vpn_traffic_low: 'کم‌شدن حجم',
  vpn_traffic_exhausted: 'اتمام حجم',
  vpn_disabled: 'غیرفعال‌شدن اکانت',
  vpn_queued_plan_started: 'شروع پلن صف‌شده',
};

type Draft = Record<string, { title: string; body: string }>;

/** The store's own wording for customer notices. Kinds left empty use the platform text. */
function NoticeTexts({ call, toast, storeId, writable }: { call: CallFn; toast: Toast; storeId: string; writable: boolean }) {
  const [meta, setMeta] = useState<NoticeTextMeta | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setMeta(null);
    if (!storeId) return;
    (async () => {
      try {
        const r = await call(`/api/v1/admin/stores/${storeId}/vpn-notice-texts`);
        if (!r.ok) throw new Error(String(r.status));
        const j = await r.json();
        setMeta(j);
        setDraft(j.texts || {});
      } catch {
        toast('دریافت متن اعلان‌ها ناموفق بود');
      }
    })();
  }, [call, storeId, toast]);

  const edit = (kind: string, field: 'title' | 'body', v: string) =>
    setDraft((d) => ({ ...d, [kind]: { ...(d[kind] ?? { title: '', body: '' }), [field]: v } }));

  const save = async (clear: boolean) => {
    // a kind with an empty title and body is not sent: it falls back to the platform text
    const texts = clear
      ? {}
      : Object.fromEntries(Object.entries(draft).filter(([, t]) => t.title.trim() || t.body.trim()));
    const half = Object.entries(texts).find(([, t]) => !t.title.trim() || !t.body.trim());
    if (half) {
      toast(`برای «${KIND_LABEL[half[0]] ?? half[0]}» هم عنوان و هم متن لازم است`);
      return;
    }
    setSaving(true);
    try {
      const r = await call(`/api/v1/admin/stores/${storeId}/vpn-notice-texts`, {
        method: 'PUT',
        body: JSON.stringify({ texts }),
      });
      if (!r.ok) throw new Error(((await r.json().catch(() => ({}))) as ErrorBody).error?.message || String(r.status));
      const j = await r.json();
      setMeta(j);
      setDraft(j.texts || {});
      toast('ذخیره شد');
    } catch (e) {
      toast(`ناموفق: ${errMessage(e)}`);
    }
    setSaving(false);
  };

  if (!meta) return null;
  return (
    <div className="space-y-3">
      <h3 className="font-extrabold">متن اعلان‌های مشتری</h3>
      <p className="text-sm">
        متن اختصاصی این فروشگاه برای پیام‌های اکانت. جای‌نگه‌دارها:{' '}
        <span dir="ltr" className="latin">
          {(meta.placeholders || []).join('  ')}
        </span>
        . اگر هر دو خانه‌ی یک نوع خالی بماند، متن پیش‌فرض سامانه فرستاده می‌شود.
      </p>
      {(meta.kinds || []).map((k: string) => (
        <div key={k} className="space-y-1">
          <div className="text-sm font-extrabold">{KIND_LABEL[k] ?? k}</div>
          <input
            className="inp w-full"
            maxLength={80}
            value={draft[k]?.title ?? ''}
            onChange={(e) => edit(k, 'title', e.target.value)}
            aria-label={`عنوان ${KIND_LABEL[k] ?? k}`}
            placeholder="عنوان"
            disabled={!writable}
          />
          <textarea
            className="inp w-full"
            rows={2}
            maxLength={500}
            value={draft[k]?.body ?? ''}
            onChange={(e) => edit(k, 'body', e.target.value)}
            aria-label={`متن ${KIND_LABEL[k] ?? k}`}
            placeholder="متن پیام"
            disabled={!writable}
          />
        </div>
      ))}
      <div className="flex flex-wrap gap-2">
        <button className="btn" disabled={saving || !writable} onClick={() => save(false)}>
          ذخیره‌ی متن‌ها
        </button>
        <button className="btn btn-g" disabled={saving || !writable} onClick={() => save(true)}>
          بازگشت به متن پیش‌فرض
        </button>
      </div>
    </div>
  );
}

/** Daily VPN digest for the store owner (off by default; a day with nothing to report sends nothing). */
function DigestSwitch({ call, toast, storeId, cfg, writable }: { call: CallFn; toast: Toast; storeId: string; cfg: NoticeCfg | null; writable: boolean }) {
  const [on, setOn] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => setOn(!!cfg?.daily_digest), [cfg]);
  if (!cfg) return null;
  const flip = async (v: boolean) => {
    setBusy(true);
    try {
      const r = await call(`/api/v1/admin/stores/${storeId}/vpn-digest`, { method: 'PUT', body: JSON.stringify({ enabled: v }) });
      if (!r.ok) throw new Error(((await r.json().catch(() => ({}))) as ErrorBody).error?.message || String(r.status));
      setOn(v);
      toast(v ? 'خلاصه‌ی روزانه فعال شد' : 'خلاصه‌ی روزانه غیرفعال شد');
    } catch (e) {
      toast(`ناموفق: ${errMessage(e)}`);
    }
    setBusy(false);
  };
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="text-sm">
        خلاصه‌ی روزانه‌ی اکانت‌ها برای مالک فروشگاه
        {!cfg.has_owner && <span className="text-[var(--mu)]"> (این فروشگاه هنوز مالک ندارد)</span>}
      </div>
      <div aria-busy={busy}>
        <Switch checked={on} onChange={(v: boolean) => writable && !busy && flip(v)} label="خلاصه‌ی روزانه" />
      </div>
    </div>
  );
}

export default function StoreNoticesView({ api, toast }: { api?: HubApiProp; toast: Toast }) {
  const call = useCallback((p: string, o?: RequestInit) => authFetch(api?.base ?? '', p, o), [api?.base]);
  const writable = canWrite(api?.perms, 'حجم فروشگاه‌ها');
  const [stores, setStores] = useState<StoreRow[]>([]);
  const [storeId, setStoreId] = useState('');
  const [cfg, setCfg] = useState<NoticeCfg | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await call('/api/v1/admin/stores');
        if (r.ok) setStores(asList<StoreRow>(await r.json()));
      } catch {
        toast('دریافت فهرست فروشگاه‌ها ناموفق بود');
      }
    })();
  }, [call, toast]);

  return (
    <section className="card space-y-4 p-4">
      <select className="inp" value={storeId} onChange={(e) => setStoreId(e.target.value)} aria-label="فروشگاه">
        <option value="">یک فروشگاه انتخاب کنید</option>
        {stores.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
      <NoticeLevels call={call} toast={toast} storeId={storeId} writable={writable} onCfg={setCfg} />
      {storeId && <DigestSwitch call={call} toast={toast} storeId={storeId} cfg={cfg} writable={writable} />}
      {storeId && <NoticeTexts call={call} toast={toast} storeId={storeId} writable={writable} />}
    </section>
  );
}
