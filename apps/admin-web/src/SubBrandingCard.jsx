// Subscription-page branding of ONE store on ONE panel: what the store chose versus what its panel admin holds now.
// "Apply" and "Remove" write only the three melorin_* keys into that admin's custom_variables (other keys stay), after the admin
// types the panel's name. Never automatic (decision 3); the server reads the admin back and reports success only if the panel kept it.
import { useCallback, useEffect, useState } from 'react';
import { Palette } from 'lucide-react';
import { errText } from './kit.jsx';

const LABELS = { melorin_brand_name: 'نام برند', melorin_support_url: 'لینک پشتیبانی', melorin_logo_url: 'لوگو' };
const ltr = (v) => (
  <span dir="ltr" className="latin break-all text-xs">
    {v}
  </span>
);

export default function SubBrandingCard({ storeId, panelId, panelName, call, toast }) {
  const url = `/api/v1/admin/stores/${storeId}/sub-branding/${panelId}`;
  const [pv, setPv] = useState(null);
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const r = await call(url);
      if (!r.ok) throw new Error('load');
      setPv(await r.json());
    } catch {
      setPv({ live: false, note: 'پنل موقتاً در دسترس نیست.', wanted: {} });
    }
  }, [call, url]);
  useEffect(() => {
    load();
  }, [load]);

  const act = async (what) => {
    setBusy(true);
    setError('');
    try {
      const r = await call(`${url}/${what}`, { method: 'POST', body: JSON.stringify({ confirm_name: typed }) });
      if (!r.ok) {
        setError(await errText(r, 'عملیات ناموفق بود'));
        return;
      }
      toast(what === 'apply' ? 'برند روی پنل اعمال و تأیید شد' : 'برند از پنل برداشته شد');
      setTyped('');
      await load();
    } catch {
      setError('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy(false);
    }
  };

  const wanted = pv?.wanted || {};
  const onPanel = pv?.on_panel || {};
  const keys = Object.keys(LABELS);
  const canType = typed.trim() === panelName && !busy;
  return (
    <section className="card space-y-3 p-4" data-testid="sub-branding-card">
      <div>
        <h4 className="flex items-center gap-1.5 text-[13px] font-extrabold">
          <Palette size={15} /> برند صفحهٔ اشتراک
        </h4>
        <p className="mt-1 text-xs leading-6 text-[var(--mu)]">
          فقط سه کلید melorin_* در custom_variables همین ادمین نوشته می‌شود؛ بقیهٔ کلیدها و قالب پنل دست‌نخورده می‌ماند.
          اعمال با تأیید شما و ثبت در ممیزی انجام می‌شود.
        </p>
      </div>
      {pv && !pv.live ? (
        <p className="text-sm" role="status">
          ⏳ {pv.note}
        </p>
      ) : pv ? (
        <dl className="grid gap-2 text-sm sm:grid-cols-2">
          {keys.map((k) => (
            <div key={k} className="rounded-xl bg-[var(--mb)] p-2.5">
              <dt className="text-xs text-[var(--mu)]">{LABELS[k]}</dt>
              <dd className="mt-1 space-y-0.5">
                <div>انتخاب فروشگاه: {wanted[k] ? ltr(wanted[k]) : '—'}</div>
                <div>روی پنل: {onPanel[k] ? ltr(onPanel[k]) : '—'}</div>
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
      {pv?.live && (
        <p className="text-xs" data-testid="branding-sync">
          {pv.in_sync ? '✅ پنل با انتخاب فروشگاه یکی است.' : 'پنل با انتخاب فروشگاه تفاوت دارد.'}
        </p>
      )}
      <label className="block text-xs">
        <span className="text-[var(--mu)]">برای تأیید، نام پنل را تایپ کنید: «{panelName}»</span>
        <input
          className="inp mt-1 w-full"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          aria-label="نام پنل برای تأیید"
        />
      </label>
      {error && (
        <p className="text-xs text-[var(--rd)]" role="alert">
          {error}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          className="btn btn-p !py-2 !text-sm"
          disabled={!canType || !pv?.live || Object.keys(wanted).length === 0}
          onClick={() => act('apply')}
        >
          اعمال روی پنل
        </button>
        <button
          className="btn btn-g btn-d !py-2 !text-sm"
          disabled={!canType || !pv?.live}
          onClick={() => act('revert')}
        >
          برداشتن از پنل
        </button>
      </div>
    </section>
  );
}
