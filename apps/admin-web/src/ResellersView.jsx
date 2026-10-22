// Resellers desk: every reseller store with the LIVE state of its Telegram bot → drawer to edit identity, standing,
// limits, bot token / on-off and the texts the bot shows. The token is write-only: it is never sent back to the browser.
import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ExternalLink,
  Globe,
  Plug,
  PlugZap,
  RefreshCw,
  Store,
  Trash2,
  Unplug,
} from 'lucide-react';
import { authFetch } from './api.js';
import { confirmDialog, dt } from './ui.jsx';
import {
  Drawer,
  Empty,
  ErrorBar,
  Field,
  KpiBar,
  NumInput,
  Pills,
  SearchBox,
  Segmented,
  Stat,
  Toggle,
  errText,
  num,
  useRows,
} from './kit.jsx';

// Effective bot state computed by Core (stores/bots.py): what the admin should believe about the bot right now.
const BOT_STATE = {
  running: ['b-ok', 'متصل'],
  connecting: ['b-in', 'در حال اتصال'],
  pending: ['b-wn', 'در انتظار راه‌اندازی'],
  offline: ['b-bd', 'قطع (پاسخ نمی‌دهد)'],
  error: ['b-bd', 'خطا'],
  disabled: ['b-mu', 'غیرفعال'],
  no_token: ['b-mu', 'بدون ربات'],
  store_suspended: ['b-mu', 'فروشگاه تعلیق'],
  stopped: ['b-mu', 'متوقف'],
};
const PROBLEM = new Set(['error', 'offline']);
const FILTERS = [
  ['all', 'همه'],
  ['running', 'متصل'],
  ['problem', 'دارای مشکل'],
  ['off', 'غیرفعال / بدون ربات'],
  ['suspended', 'تعلیق'],
];
const TEXTS = [
  ['welcome', 'پیام خوش‌آمدگویی', 'اولین پیامی که مشتری با /start می‌بیند. خالی = پیام پیش‌فرض.', 1000],
  ['support', 'متن پشتیبانی', 'قبل از ثبت پیام پشتیبانی نمایش داده می‌شود (ساعت کاری، آیدی تلگرام…).', 500],
  ['rules', 'قوانین خرید', 'جایگزین متن پیش‌فرض قوانین. خالی = متن پیش‌فرض.', 3000],
];

export const BotBadge = ({ state }) => {
  const m = BOT_STATE[state] || ['b-mu', state || '—'];
  return <span className={`badge ${m[0]}`}>{m[1]}</span>;
};

function BotCell({ bot }) {
  if (!bot.has_token) return <span className="text-[var(--mu)]">—</span>;
  return (
    <span className="inline-flex flex-col items-start gap-1">
      <span className="inline-flex items-center gap-1.5">
        <Bot size={14} className="text-[var(--mu)]" />
        <span dir="ltr" className="latin text-xs font-bold">
          {bot.username ? `@${bot.username}` : 'نامشخص'}
        </span>
      </span>
      <BotBadge state={bot.state} />
    </span>
  );
}

function Loader({ id, call, toast, onClose, onDone }) {
  const [r, setR] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    call(`/api/v1/admin/resellers/${id}`)
      .then(async (x) => (x.ok ? setR(await x.json()) : setFailed(true)))
      .catch(() => setFailed(true));
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (failed) return <Drawer title="خطا" onClose={onClose} footer={null} error="دریافت اطلاعات نماینده ناموفق بود." />;
  if (!r)
    return (
      <Drawer title="در حال بارگذاری…" onClose={onClose} footer={null}>
        <div className="skel h-24 w-full" />
      </Drawer>
    );
  return <Editor key={r.id} initial={r} call={call} toast={toast} onClose={onClose} onDone={onDone} />;
}

function Editor({ initial, call, toast, onClose, onDone }) {
  const [r, setR] = useState(initial); // last server copy
  const pick = (x) => ({
    name: x.name,
    domain: x.domain || '',
    status: x.status,
    debt: String(x.debt_limit ?? 0),
    sales: !!x.sales_enabled,
    api: !!x.api_enabled,
    botOn: !!x.bot.enabled,
    texts: { welcome: '', support: '', rules: '', ...(x.bot_messages || {}) },
  });
  const [f, setF] = useState(pick(initial));
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const set = (k) => (v) => setF((x) => ({ ...x, [k]: v }));
  const base = pick(r);
  const dirty = JSON.stringify(f) !== JSON.stringify(base);

  const run = async (path, method, body, okMsg) => {
    setBusy(true);
    setError('');
    try {
      const res = await call(path, { method, body: body ? JSON.stringify(body) : undefined });
      if (!res.ok) {
        setError(await errText(res, 'عملیات ناموفق بود'));
        return null;
      }
      const d = await res.json();
      toast(okMsg);
      return d;
    } catch {
      setError('ارتباط با سرور برقرار نشد');
      return null;
    } finally {
      setBusy(false);
    }
  };
  const adopt = (d) => {
    setR(d);
    setF(pick(d));
    onDone(false);
  };
  const base_ = `/api/v1/admin/resellers/${r.id}`;

  const save = async () => {
    const b = pick(r),
      body = {};
    if (f.name.trim() !== b.name) body.name = f.name.trim();
    if (f.domain.trim() !== b.domain) body.domain = f.domain.trim();
    if (f.status !== b.status) body.status = f.status;
    if (f.debt !== b.debt) body.debt_limit = Number(f.debt || 0);
    if (f.sales !== b.sales) body.sales_enabled = f.sales;
    if (f.api !== b.api) body.api_enabled = f.api;
    if (f.botOn !== b.botOn) body.bot_enabled = f.botOn;
    if (JSON.stringify(f.texts) !== JSON.stringify(b.texts)) body.bot_messages = f.texts;
    if (
      body.status === 'suspended' &&
      !(await confirmDialog('فروشگاه تعلیق می‌شود: وب‌سایت و ربات آن دیگر به مشتریان پاسخ نمی‌دهند.', {
        title: 'تعلیق فروشگاه',
        danger: true,
        ok: 'تعلیق',
      }))
    )
      return;
    if (
      body.domain &&
      b.domain &&
      !(await confirmDialog(
        `دامنهٔ فروشگاه از ${b.domain} به ${body.domain} تغییر می‌کند. DNS دامنهٔ جدید باید به این سرور اشاره کند و لینک‌های قدیمی از کار می‌افتند.`,
        { title: 'تغییر دامنه', ok: 'تغییر دامنه' },
      ))
    )
      return;
    const d = await run(base_, 'PATCH', body, 'تغییرات ذخیره شد');
    if (d) adopt(d);
  };
  const saveToken = async () => {
    if (
      r.bot.has_token &&
      !(await confirmDialog('ربات فعلی جایگزین می‌شود و مشتریان باید از ربات جدید استفاده کنند.', {
        title: 'تغییر ربات',
        ok: 'جایگزین کن',
      }))
    )
      return;
    const d = await run(
      `${base_}/bot-token`,
      'PUT',
      { token: token.trim() },
      'ربات ثبت شد؛ تا ۳۰ ثانیه دیگر متصل می‌شود',
    );
    if (d) {
      setToken('');
      adopt(d);
    }
  };
  const disconnect = async () => {
    if (
      !(await confirmDialog(
        'توکن حذف می‌شود و ربات این فروشگاه از کار می‌افتد. ربات آزاد می‌شود و می‌توان آن را به فروشگاه دیگری داد.',
        { title: 'قطع ارتباط ربات', danger: true, ok: 'قطع ارتباط' },
      ))
    )
      return;
    const d = await run(`${base_}/bot-token`, 'DELETE', null, 'ربات قطع شد');
    if (d) adopt(d);
  };
  const verify = async () => {
    const d = await run(`${base_}/verify-bot`, 'POST', null, 'توکن توسط تلگرام تأیید شد');
    if (d) adopt(d);
  };
  const refresh = async () => {
    const x = await call(base_);
    if (x.ok) {
      const d = await x.json();
      setR(d);
      if (!dirty) setF(pick(d));
    }
  };

  const bot = r.bot;
  const row = (k, v) => (
    <div className="flex items-start justify-between gap-4 border-b border-[var(--ln)] py-2.5 text-sm last:border-0">
      <span className="shrink-0 text-[var(--mu)]">{k}</span>
      <span className="min-w-0 break-words text-left font-bold">{v ?? '—'}</span>
    </div>
  );
  const tone = PROBLEM.has(bot.state)
    ? 'bg-[var(--bdb)] text-[var(--bd)]'
    : bot.state === 'running'
      ? 'bg-[var(--okb)] text-[var(--ok)]'
      : 'bg-[var(--mb)] text-[var(--mu)]';

  return (
    <Drawer
      title={r.name}
      subtitle={`نماینده · ${r.slug} · ثبت ${dt(r.created_at)}`}
      dirty={dirty}
      busy={busy}
      error={error}
      onClose={onClose}
      icon={
        <span className="tile h-10 w-10 bg-[var(--inb)] text-[var(--in)]">
          <Store size={19} />
        </span>
      }
      footer={
        <button className="btn !py-2 !text-sm" disabled={busy || !dirty || f.name.trim().length < 2} onClick={save}>
          <CheckCircle2 size={15} />
          ذخیرهٔ تغییرات
        </button>
      }
    >
      <section className="card space-y-4 p-4">
        <h4 className="text-[13px] font-extrabold">مشخصات فروشگاه</h4>
        <Field label="نام فروشگاه">
          <input className="inp" maxLength={200} value={f.name} onChange={(e) => set('name')(e.target.value)} />
        </Field>
        <Field
          label="دامنه"
          hint="مثال: shop.example.com — بدون http و پورت. DNS باید به این سرور اشاره کند؛ گواهی TLS در اولین بازدید صادر می‌شود."
        >
          <div className="flex items-center gap-2">
            <input dir="ltr" className="inp latin" value={f.domain} onChange={(e) => set('domain')(e.target.value)} />
            {r.domain && (
              <a
                className="btn btn-g !px-2"
                href={`https://${r.domain}`}
                target="_blank"
                rel="noopener noreferrer"
                aria-label="باز کردن فروشگاه"
              >
                <ExternalLink size={15} />
              </a>
            )}
          </div>
        </Field>
        {row(
          'مالک',
          r.owner ? (
            <span>
              {r.owner.name || '—'}{' '}
              <span dir="ltr" className="latin text-xs font-normal text-[var(--mu)]">
                {r.owner.email}
              </span>
            </span>
          ) : (
            '—'
          ),
        )}
        {row('مشتریان فعال', num(r.customers))}
      </section>

      <section className="card space-y-4 p-4">
        <h4 className="text-[13px] font-extrabold">وضعیت و محدودیت‌ها</h4>
        <Field label="وضعیت فروشگاه" hint="تعلیق: وب‌سایت و ربات فروشگاه برای مشتریان از دسترس خارج می‌شود.">
          <Segmented
            label="وضعیت"
            value={f.status}
            onChange={set('status')}
            options={[
              ['active', 'فعال'],
              ['suspended', 'تعلیق'],
            ]}
          />
        </Field>
        <Field label="سقف بدهی نماینده" hint="تا چه مبلغی می‌تواند بدون شارژ کیف پول اصلی خود بفروشد.">
          <NumInput value={f.debt} onChange={set('debt')} suffix={r.currency} />
        </Field>
        <Toggle
          checked={f.sales}
          onChange={set('sales')}
          label="فروش فعال"
          hint="خاموش: مشتریان نمی‌توانند خرید کنند، ولی فروشگاه دیده می‌شود."
        />
        <Toggle
          checked={f.api}
          onChange={set('api')}
          label="دسترسی API"
          hint="اجازهٔ ساخت و استفاده از کلید API برای اتصال سایت خود نماینده."
        />
      </section>

      <section className="card space-y-4 p-4">
        <div className="flex items-center justify-between gap-2">
          <h4 className="text-[13px] font-extrabold">ربات تلگرام</h4>
          <button className="btn btn-g !py-1 !text-xs" onClick={refresh} disabled={busy}>
            <RefreshCw size={12} />
            به‌روزرسانی وضعیت
          </button>
        </div>
        <div className={`flex items-start gap-3 rounded-xl p-3 text-xs leading-6 ${tone}`}>
          {PROBLEM.has(bot.state) ? (
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          ) : bot.state === 'running' ? (
            <PlugZap size={16} className="mt-0.5 shrink-0" />
          ) : (
            <Unplug size={16} className="mt-0.5 shrink-0" />
          )}
          <div className="min-w-0">
            <div className="font-extrabold">
              <BotBadge state={bot.state} />{' '}
              {bot.username && (
                <span dir="ltr" className="latin mr-2">
                  @{bot.username}
                </span>
              )}
            </div>
            {bot.detail && <p className="mt-1">{bot.detail}</p>}
            {bot.state === 'offline' && (
              <p className="mt-1">ربات مدتی است وضعیت خود را گزارش نمی‌کند؛ سرویس telegram_reseller را بررسی کنید.</p>
            )}
            {bot.state === 'pending' && (
              <p className="mt-1">ثبت شده؛ سرویس ربات تا ۳۰ ثانیهٔ دیگر آن را راه‌اندازی می‌کند.</p>
            )}
            {bot.seen_at && <p className="mt-1 opacity-80">آخرین گزارش: {dt(bot.seen_at)}</p>}
          </div>
        </div>
        <Toggle
          checked={f.botOn}
          onChange={set('botOn')}
          label="ربات روشن باشد"
          hint="خاموش‌کردن ربات، فروشگاه و وب‌سایت را تعلیق نمی‌کند."
        />
        <Field
          label={bot.has_token ? 'جایگزینی توکن ربات' : 'توکن ربات'}
          hint="از BotFather بگیرید. تلگرام همین حالا آن را تأیید می‌کند؛ توکن رمزنگاری ذخیره می‌شود و هرگز نمایش داده نمی‌شود."
        >
          <div className="flex items-center gap-2">
            <input
              dir="ltr"
              type="password"
              autoComplete="off"
              spellCheck={false}
              className="inp latin"
              placeholder="123456789:AA…"
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
            <button className="btn !py-2 !text-xs" disabled={busy || token.trim().length < 10} onClick={saveToken}>
              <Plug size={14} />
              {bot.has_token ? 'جایگزین' : 'ثبت و اتصال'}
            </button>
          </div>
        </Field>
        {bot.has_token && (
          <div className="flex flex-wrap gap-2">
            <button className="btn btn-g !py-1.5 !text-xs" disabled={busy} onClick={verify}>
              <Globe size={13} />
              بررسی توکن با تلگرام
            </button>
            <button className="btn btn-g btn-d !py-1.5 !text-xs" disabled={busy} onClick={disconnect}>
              <Trash2 size={13} />
              قطع ارتباط ربات
            </button>
          </div>
        )}
      </section>

      <section className="card space-y-4 p-4">
        <h4 className="text-[13px] font-extrabold">متن‌های ربات</h4>
        {TEXTS.map(([k, label, hint, max]) => (
          <Field key={k} label={label} hint={`${hint} (${num(f.texts[k].length)}/${num(max)})`}>
            <textarea
              rows={k === 'rules' ? 5 : 3}
              className="inp"
              maxLength={max}
              value={f.texts[k]}
              onChange={(e) => setF((x) => ({ ...x, texts: { ...x.texts, [k]: e.target.value } }))}
            />
          </Field>
        ))}
      </section>
    </Drawer>
  );
}

export default function ResellersView({ api, toast }) {
  const call = (p, o = {}) => authFetch(api.base, p, o);
  const { rows, failed, load } = useRows(call, '/api/v1/admin/resellers');
  const [filter, setFilter] = useState('all');
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(null);
  const all = rows || [];
  const inFilter = (x, k) =>
    k === 'all' ||
    (k === 'running' && x.bot.state === 'running') ||
    (k === 'problem' && PROBLEM.has(x.bot.state)) ||
    (k === 'off' && ['disabled', 'no_token', 'stopped'].includes(x.bot.state)) ||
    (k === 'suspended' && x.status === 'suspended');
  const count = (k) => all.filter((x) => inFilter(x, k)).length;
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    return all.filter(
      (x) =>
        inFilter(x, filter) &&
        (!t ||
          [x.name, x.slug, x.domain, x.owner?.email, x.owner?.name, x.bot.username].some((v) =>
            (v || '').toLowerCase().includes(t),
          )),
    );
  }, [all, filter, q]);  

  return (
    <div className="space-y-5">
      <KpiBar cols={4}>
        <Stat
          label="نمایندگان"
          value={all.length}
          tone="in"
          Icon={Store}
          active={filter === 'all'}
          onClick={() => setFilter('all')}
        />
        <Stat
          label="ربات متصل"
          value={count('running')}
          tone="ok"
          Icon={PlugZap}
          active={filter === 'running'}
          onClick={() => setFilter('running')}
        />
        <Stat
          label="ربات دارای مشکل"
          value={count('problem')}
          tone="bd"
          Icon={AlertTriangle}
          active={filter === 'problem'}
          onClick={() => setFilter('problem')}
          sub="خطا یا قطع"
        />
        <Stat
          label="تعلیق"
          value={count('suspended')}
          tone="wn"
          Icon={Unplug}
          active={filter === 'suspended'}
          onClick={() => setFilter('suspended')}
        />
      </KpiBar>
      <section className="card rise overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--ln)] px-5 py-4">
          <div>
            <h3 className="font-extrabold">نمایندگان</h3>
            <p className="mt-1 text-xs text-[var(--mu)]">
              ویرایش فروشگاه، سقف بدهی و ربات تلگرام هر نماینده؛ وضعیت ربات زنده است.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Pills
              label="فیلتر"
              value={filter}
              onChange={setFilter}
              options={FILTERS.map(([k, l]) => [k, l, count(k), { warn: k === 'problem' }])}
            />
            <SearchBox value={q} onChange={setQ} placeholder="نام، دامنه، ایمیل، ربات…" label="جستجو در نمایندگان" />
          </div>
        </div>
        {failed && (
          <div className="p-4">
            <ErrorBar onRetry={load}>دریافت فهرست نمایندگان ناموفق بود</ErrorBar>
          </div>
        )}
        <div className="max-h-[70vh] overflow-auto">
          <table className="tbl min-w-[900px]">
            <thead>
              <tr>
                <th>فروشگاه</th>
                <th>مالک</th>
                <th>دامنه</th>
                <th>ربات</th>
                <th>سقف بدهی</th>
                <th>مشتریان</th>
                <th>وضعیت</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows === null ? (
                Array.from({ length: 4 }, (_, i) => (
                  <tr key={i}>
                    <td colSpan={8}>
                      <div className="skel h-5 w-full" />
                    </td>
                  </tr>
                ))
              ) : shown.length ? (
                shown.map((x) => (
                  <tr key={x.id} className="cursor-pointer" onClick={() => setOpen(x.id)}>
                    <td>
                      <div className="font-bold">{x.name}</div>
                      <div dir="ltr" className="latin text-right text-xs text-[var(--mu)]">
                        {x.slug}
                      </div>
                    </td>
                    <td>
                      <div className="font-bold">{x.owner?.name || '—'}</div>
                      <div dir="ltr" className="latin text-right text-xs text-[var(--mu)]">
                        {x.owner?.email}
                      </div>
                    </td>
                    <td>
                      {x.domain ? (
                        <span dir="ltr" className="latin inline-flex items-center gap-1.5 text-xs">
                          <Globe size={13} className="text-[var(--mu)]" />
                          {x.domain}
                        </span>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td>
                      <BotCell bot={x.bot} />
                    </td>
                    <td className="num">{num(x.debt_limit)}</td>
                    <td className="num">{num(x.customers)}</td>
                    <td>
                      <span className={`badge ${x.status === 'active' ? 'b-ok' : 'b-mu'}`}>
                        {x.status === 'active' ? 'فعال' : 'تعلیق'}
                      </span>
                    </td>
                    <td>
                      <button
                        className="btn btn-g !py-1.5 !text-xs"
                        onClick={(e) => {
                          e.stopPropagation();
                          setOpen(x.id);
                        }}
                      >
                        ویرایش
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={8}>
                    <Empty
                      Icon={Store}
                      title="نماینده‌ای در این فیلتر نیست"
                      text={
                        all.length
                          ? 'فیلتر یا عبارت جستجو را تغییر دهید.'
                          : 'نمایندگان پس از تأیید درخواست نمایندگی اینجا ظاهر می‌شوند.'
                      }
                    />
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
      {open && (
        <Loader
          key={open}
          id={open}
          call={call}
          toast={toast}
          onClose={() => {
            setOpen(null);
            load();
          }}
          onDone={() => load()}
        />
      )}
    </div>
  );
}
