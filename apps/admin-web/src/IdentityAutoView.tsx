import type { ReactNode } from 'react';
// «هویت خودکار» — what the automatic identity verification did (docs/21): trusted browsers that sign visitors in
// without a manual step, and accounts that were folded together automatically. The admin can revoke trust here.
import { useEffect, useState } from 'react';
import { ArrowLeftRight, Fingerprint, MonitorSmartphone, ShieldOff, UserRound, Users } from 'lucide-react';
import { authFetch, typedClient } from './api.ts';
import { confirmDialog, dt, sid } from './ui.tsx';
import { Empty, ErrorBar, KpiBar, Pills, SearchBox, Segmented, Stat, errText, num, tint, useRows } from './kit.tsx';
import type { CallFn, Json, Rec, Toast } from './types.ts';

const STATUS: Rec = {
  active: ['فعال', 'ok'],
  expired: ['منقضی', 'mu'],
  revoked: ['لغو شده', 'bd'],
};
const RULES: Rec = {
  shell_into_other: 'حساب خالی در حساب دارای سابقه ادغام شد',
  both_shells: 'دو حساب خالی بودند؛ حساب قدیمی‌تر ماند',
};
const PROVIDERS: Rec = { google: 'Google', email: 'ایمیل', telegram: 'تلگرام' };

const who = (u: Json) => (u ? u.display_name || u.email || sid(u.id) : '-');

function Chip({ tone, children }: { tone?: Json; children?: ReactNode }) {
  return (
    <span className="rounded-full px-2 py-0.5 text-[11px] font-bold" style={tint(tone)}>
      {children}
    </span>
  );
}

function DevicesTab({ call, base, toast, onChanged }: { call: CallFn; base: string; toast: Toast; onChanged?: Json }) {
  const [status, setStatus] = useState('active');
  const [q, setQ] = useState('');
  const query = `?status=${status}${q.trim() ? `&q=${encodeURIComponent(q.trim())}` : ''}`;
  const { rows, failed, load } = useRows(call, `/api/v1/admin/trusted-devices${query}`);
  const [busy, setBusy] = useState<Json>(null);

  // typed api-client (same transport as authFetch); one literal path per action so the schema checks each body
  const run = async (key: Json, send: () => Promise<{ response: Response }>, done: Json) => {
    setBusy(key);
    try {
      const { response: res } = await send();
      if (res.ok) {
        toast(done);
        load();
        onChanged();
      } else toast(await errText(res, 'ناموفق'));
    } catch {
      toast('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy(null);
    }
  };
  const revokeOne = async (d: Json) => {
    if (
      !(await confirmDialog(
        `اعتماد به «${d.label || 'دستگاه ناشناس'}» لغو شود؟ ورود بعدی از این مرورگر دوباره تأیید دستی می‌خواهد.`,
        { title: 'لغو اعتماد', danger: true, ok: 'لغو اعتماد' },
      ))
    )
      return;
    run(
      d.id,
      () =>
        typedClient(base).post('/api/v1/admin/trusted-devices/{device_id}/revoke', {
          params: { path: { device_id: d.id } },
        }),
      'اعتماد دستگاه لغو شد',
    );
  };
  const revokeAccount = async (d: Json) => {
    if (
      !(await confirmDialog(`همهٔ دستگاه‌های مورداعتماد «${who(d.user)}» لغو شود؟`, {
        title: 'لغو همهٔ دستگاه‌ها',
        danger: true,
        ok: 'لغو همه',
      }))
    )
      return;
    run(
      `u${d.user?.id}`,
      () =>
        typedClient(base).post('/api/v1/admin/trusted-devices/revoke-account', {
          body: { user_id: d.user?.id },
        }),
      'همهٔ دستگاه‌های این حساب لغو شد',
    );
  };

  return (
    <div className="space-y-4">
      <div className="tool">
        <SearchBox
          value={q}
          onChange={setQ}
          label="جستجو در دستگاه‌ها"
          placeholder="نام، ایمیل، مرورگر یا شناسهٔ تلگرام…"
        />
        <Pills
          label="وضعیت"
          value={status}
          onChange={setStatus}
          options={[
            ['active', 'فعال'],
            ['expired', 'منقضی'],
            ['revoked', 'لغو شده'],
            ['all', 'همه'],
          ]}
        />
      </div>
      {failed && <ErrorBar onRetry={load}>دریافت فهرست ناموفق بود.</ErrorBar>}
      {rows && rows.length === 0 && !failed && (
        <Empty
          Icon={MonitorSmartphone}
          title="دستگاهی پیدا نشد"
          text="وقتی کاربری ورود با تلگرام را تأیید و «مرا به خاطر بسپار» را نگه دارد، مرورگرش اینجا دیده می‌شود."
        />
      )}
      <ul className="space-y-2">
        {(rows || []).map((d) => (
          <li key={d.id} className="card flex flex-wrap items-center gap-3 p-3">
            <span className="tile h-10 w-10 bg-[var(--mb)] text-[var(--mu)]">
              <MonitorSmartphone size={18} />
            </span>
            <div className="min-w-0 flex-1 space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <b className="text-sm">{d.label || 'دستگاه ناشناس'}</b>
                <Chip tone={STATUS[d.status][1]}>{STATUS[d.status][0]}</Chip>
                <span className="text-[11px] text-[var(--mu)]">{d.store_name}</span>
              </div>
              <p className="text-xs text-[var(--mu)]">
                {who(d.user)}
                {d.user?.email && d.user.display_name ? ` · ${d.user.email}` : ''} · تلگرام {d.telegram_id}
              </p>
              <p className="text-[11px] text-[var(--mu)]" dir="ltr">
                {d.last_ip || '-'} · {num(d.uses)}× · آخرین استفاده {dt(d.last_seen_at)} · انقضا {dt(d.expires_at)}
                {d.revoked_at ? ` · لغو ${dt(d.revoked_at)}` : ''}
              </p>
            </div>
            {d.status === 'active' && (
              <div className="flex gap-2">
                <button className="btn btn-g btn-d" disabled={busy === d.id} onClick={() => revokeOne(d)}>
                  <ShieldOff size={13} /> لغو اعتماد
                </button>
                <button
                  className="btn btn-g"
                  disabled={busy === `u${d.user?.id}`}
                  onClick={() => revokeAccount(d)}
                  title="همهٔ دستگاه‌های این حساب"
                >
                  <Users size={13} /> همهٔ حساب
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function MergesTab({ call }: { call: CallFn }) {
  const [days, setDays] = useState('90');
  const { rows, failed, load } = useRows(call, `/api/v1/admin/identity-auto-merges?days=${days}`);
  return (
    <div className="space-y-4">
      <div className="tool">
        <Pills
          label="بازه"
          value={days}
          onChange={setDays}
          options={[
            ['30', '۳۰ روز'],
            ['90', '۹۰ روز'],
            ['365', 'یک سال'],
          ]}
        />
      </div>
      <p className="px-1 text-xs leading-6 text-[var(--mu)]">
        فقط حساب «خالی» (بدون سفارش، پرداخت، اکانت، تیکت، کیف پول، رمز و ادمین) در حساب دیگر ادغام می‌شود؛ حساب خالی
        بایگانی می‌شود و حذف نمی‌شود. اگر هر دو سابقه داشته باشند، مورد در تب «نیاز به بررسی» می‌ماند.
      </p>
      {failed && <ErrorBar onRetry={load}>دریافت فهرست ناموفق بود.</ErrorBar>}
      {rows && rows.length === 0 && !failed && (
        <Empty
          Icon={ArrowLeftRight}
          title="ادغام خودکاری ثبت نشده"
          text="در این بازه هیچ حسابی به‌طور خودکار ادغام نشده است."
        />
      )}
      <ul className="space-y-2">
        {(rows || []).map((m) => (
          <li key={m.id} className="card flex flex-wrap items-center gap-3 p-3">
            <span className="tile h-10 w-10 bg-[var(--mb)] text-[var(--mu)]">
              <ArrowLeftRight size={18} />
            </span>
            <div className="min-w-0 flex-1 space-y-1">
              <p className="text-sm">
                <UserRound size={13} className="ml-1 inline" />
                <b>{who(m.shell)}</b> ← در <b>{who(m.keeper)}</b> ادغام شد
              </p>
              <p className="text-[11px] text-[var(--mu)]">
                {RULES[m.rule] || m.rule || 'قانون نامشخص'} · {dt(m.created_at)}
                {m.providers?.length ? ` · ${m.providers.map((p: Json) => PROVIDERS[p] || p).join('، ')}` : ''}
              </p>
            </div>
            <span className="text-[11px] text-[var(--mu)]" dir="ltr">
              {sid(m.shell?.id)} → {sid(m.keeper?.id)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// `section` ('devices' | 'merges') pins the view to one tab when the screen is hosted inside the identity hub.
export default function IdentityAutoView({ api, toast, section }: { api?: Json; toast: Toast; section?: Json }) {
  const call = (p: Json, o = {}) => authFetch(api.base, p, o);
  const [tab, setTabState] = useState(section || 'devices');
  const setTab = (v: Json) => !section && setTabState(v);
  const [tick, setTick] = useState(0);
  const [s, setS] = useState<Rec>({});
  useEffect(() => {
    let alive = true;
    typedClient(api.base)
      .get('/api/v1/admin/trusted-devices/summary')
      .then((r) => (r.response.ok ? r.data : {}))
      .then((d) => alive && setS((d as Rec) || {}))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="space-y-5">
      <KpiBar cols={4}>
        <Stat
          label="دستگاه فعال"
          value={num(s.active_devices)}
          tone="ok"
          Icon={MonitorSmartphone}
          active={tab === 'devices'}
          onClick={() => setTab('devices')}
        />
        <Stat label="حساب دارای دستگاه" value={num(s.accounts)} tone="in" Icon={Users} />
        <Stat label="دستگاه لغو شده" value={num(s.revoked_devices)} tone="mu" Icon={ShieldOff} />
        <Stat
          label="ادغام خودکار (۳۰ روز)"
          value={num(s.auto_merges_30d)}
          tone="wn"
          Icon={Fingerprint}
          active={tab === 'merges'}
          onClick={() => setTab('merges')}
        />
      </KpiBar>
      {!section && (
        <Segmented
          label="بخش"
          value={tab}
          onChange={setTab}
          options={[
            ['devices', 'دستگاه‌های مورداعتماد'],
            ['merges', 'ادغام‌های خودکار'],
          ]}
        />
      )}
      {tab === 'devices' ? (
        <DevicesTab call={call} base={api.base} toast={toast} onChanged={() => setTick((t) => t + 1)} />
      ) : (
        <MergesTab call={call} />
      )}
    </div>
  );
}
