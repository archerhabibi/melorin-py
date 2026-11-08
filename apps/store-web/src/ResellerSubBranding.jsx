// Reseller › Subscription-page branding: three plain fields (name, support link, logo).
// Saving here changes NOTHING on a panel. The platform admin applies them to this store's panel admin after review.
import { useCallback, useEffect, useState } from 'react';
import { Palette, Save } from 'lucide-react';
import { Empty, Loading } from './ui.jsx';

const J = { 'Content-Type': 'application/json' };
const FIELDS = [
  ['display_name', 'نام نمایشی برند', 'حداکثر ۶۴ نویسه؛ فقط متن ساده.', 'text'],
  ['support_url', 'لینک پشتیبانی', 'آدرس https://… یا tg://… ؛ خالی‌گذاشتن آن را پاک می‌کند.', 'url'],
  ['logo_url', 'لینک لوگو', 'آدرس https:// به یک تصویر (png، jpg، webp، svg یا gif).', 'url'],
];

export default function ResellerSubBranding({ coreFetch, base, notify }) {
  const [saved, setSaved] = useState(null);
  const [applied, setApplied] = useState([]);
  const [draft, setDraft] = useState({});
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await coreFetch(`${base}/sub-branding`);
      if (!r.ok) throw new Error('load');
      const d = await r.json();
      setSaved(d.fields || {});
      setApplied(d.applied_on || []);
      setDraft(d.fields || {});
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [coreFetch, base]);
  useEffect(() => {
    load();
  }, [load]);

  if (failed) return <Empty text="تنظیمات برند اشتراک در دسترس نیست." icon={Palette} />;
  if (!saved) return <Loading rows={3} />;
  // only fields that really changed are sent; an emptied one is sent as "" (= clear)
  const changes = Object.fromEntries(FIELDS.map(([k]) => [k, draft[k] ?? '']).filter(([k, v]) => v !== (saved[k] ?? '')));
  const dirty = Object.keys(changes).length > 0;

  async function save() {
    setBusy(true);
    try {
      const r = await coreFetch(`${base}/sub-branding`, { method: 'PUT', headers: J, body: JSON.stringify(changes) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        notify(d?.error?.message || d?.detail || 'ذخیره ناموفق بود');
        return;
      }
      notify(d.note || 'ذخیره شد');
      await load();
    } catch {
      notify('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card space-y-4" data-testid="sub-branding">
      <div>
        <h4 className="flex items-center gap-2 font-extrabold">
          <Palette size={18} aria-hidden="true" /> برند صفحهٔ اشتراک
        </h4>
        <p className="mt-2 text-sm text-muted">
          نام، لینک پشتیبانی و لوگوی شما در صفحهٔ اشتراک مشتریان نمایش داده می‌شود. ذخیره در اینجا فقط مقدارها را نگه
          می‌دارد؛ اعمال روی پنل را مدیر پلتفرم پس از بررسی انجام می‌دهد. قالب صفحه ثابت و بررسی‌شده است و کد دلخواه
          پذیرفته نمی‌شود.
        </p>
        {applied.length > 0 && <p className="mt-2 text-xs text-mint">روی {applied.length} پنل اعمال شده است.</p>}
      </div>
      {FIELDS.map(([k, label, hint, type]) => (
        <label key={k} className="block text-sm">
          <span className="font-bold">{label}</span>
          <input
            className="input mt-1"
            dir={type === 'url' ? 'ltr' : undefined}
            type={type}
            value={draft[k] ?? ''}
            onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
          />
          <span className="mt-1 block text-xs text-muted">{hint}</span>
        </label>
      ))}
      <button type="button" className="btn-primary" disabled={!dirty || busy} onClick={save}>
        <Save size={16} aria-hidden="true" /> ذخیره
      </button>
    </div>
  );
}
