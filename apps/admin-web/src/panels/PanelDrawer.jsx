import { useMemo, useRef, useState } from 'react';
import { Badge, dt, sid } from '../ui.jsx';
import { Dot, health, memberIds } from '../infra.jsx';
import { Drawer, Field, NumInput, Section, Secret, Segmented, Switch, Toggle, DeleteButton, tint } from '../kit.jsx';
import { Activity, AlertTriangle, Check, ChevronDown, Plus, RefreshCw, Save, ShieldCheck } from 'lucide-react';
import { focusOnMount } from '../useDialog.js';
import { UpstreamBotLink, UpstreamCredentials, UpstreamFlowSection, UpstreamSettings } from '../UpstreamBotFields.jsx';
import {
  UB_KEYS,
  botUrl,
  emptyUb,
  ubBot,
  ubBuildConfig,
  ubCredentials,
  ubFromPanel,
  ubValidate,
} from '../upstreamBot.js';
import { KINDS, kindOf, Chips } from './panelUi.jsx';

// ---------- panel add / edit form ----------
const EMPTY = {
  kind: 'sanaei',
  name: '',
  url: '',
  auth: 'token',
  token: '',
  user: '',
  pass: '',
  inbounds: [],
  subUrl: '',
  apiStyle: 'auto',
  groups: [],
  tpl: '',
  scope: 'groups',
  verifyTls: true,
  extra: '',
  ub: emptyUb(),
};
const EMPTY_SRV = { on: true, name: '', location: '', capacity: '500' };
const KNOWN = {
  sanaei: ['inbound_ids', 'inbound_id', 'sub_base_url', 'api_style', 'verify_tls'],
  pasarguard: ['group_ids', 'user_template_id', 'verify_tls'],
  upstream_bot: UB_KEYS,
  mock: [],
};
const ints = (a) => (Array.isArray(a) ? a : []).map(Number).filter((n) => Number.isInteger(n) && n > 0);

// Rebuild the form from a stored panel; config keys the form has no field for stay in the JSON box so a save never drops them.
function fromPanel(p) {
  const c = p.config || {},
    f = { ...EMPTY, kind: p.kind, name: p.name, url: p.base_url, verifyTls: c.verify_tls !== false };
  if (p.kind === 'sanaei') {
    f.inbounds = ints(c.inbound_ids ?? (c.inbound_id != null ? [c.inbound_id] : []));
    f.subUrl = c.sub_base_url || '';
    f.apiStyle = c.api_style || 'auto';
  }
  if (p.kind === 'pasarguard') {
    if (c.user_template_id != null) {
      f.scope = 'template';
      f.tpl = String(c.user_template_id);
    } else f.groups = ints(c.group_ids);
  }
  if (p.kind === 'upstream_bot') f.ub = ubFromPanel(p);
  const rest = Object.fromEntries(Object.entries(c).filter(([k]) => !(KNOWN[p.kind] || []).includes(k)));
  f.extra = Object.keys(rest).length ? JSON.stringify(rest, null, 2) : '';
  return f;
}
const parseExtra = (t) => {
  if (!t.trim()) return {};
  const x = JSON.parse(t);
  if (!x || typeof x !== 'object' || Array.isArray(x)) throw new Error('obj');
  return x;
};

function buildPayload(f, withCreds) {
  if (f.kind === 'upstream_bot')
    return {
      name: f.name.trim(),
      kind: f.kind,
      base_url: botUrl(ubBot(f.ub)),
      credentials: withCreds ? ubCredentials(f.ub) : {},
      config: { ...ubBuildConfig(f.ub), ...parseExtra(f.extra) },
    };
  const credentials = {};
  let config = {};
  if (withCreds && f.kind !== 'mock') {
    if (f.auth === 'token') credentials[f.kind === 'sanaei' ? 'api_token' : 'api_key'] = f.token.trim();
    else {
      credentials.username = f.user.trim();
      credentials.password = f.pass;
    }
  }
  if (f.kind === 'sanaei') config = { inbound_ids: f.inbounds, sub_base_url: f.subUrl.trim(), api_style: f.apiStyle };
  else if (f.kind === 'pasarguard') {
    if (f.scope === 'groups') config.group_ids = f.groups;
    else config.user_template_id = parseInt(f.tpl, 10);
  }
  if (f.kind !== 'mock') config.verify_tls = f.verifyTls;
  config = { ...config, ...parseExtra(f.extra) };
  if (f.kind === 'sanaei' && !config.inbound_ids?.length) delete config.inbound_ids;
  return { name: f.name.trim(), kind: f.kind, base_url: f.url.trim().replace(/\/+$/, ''), credentials, config };
}
function validate(f, withCreds, srv, edit) {
  const e = {};
  let extra = {};
  if (f.extra.trim()) {
    try {
      extra = parseExtra(f.extra);
    } catch {
      e.extra = 'JSON پیشرفته نامعتبر است (باید یک شیء باشد)';
    }
  }
  if (!f.name.trim()) e.name = 'نام پنل را وارد کنید';
  if (f.kind === 'upstream_bot') Object.assign(e, ubValidate(f.ub, withCreds));
  else {
    try {
      const u = new URL(f.url.trim());
      if (!/^https?:$/.test(u.protocol)) throw 0;
    } catch {
      e.url = 'آدرس معتبر نیست (مثال: https://panel.example.com:2053/path)';
    }
  }
  if (
    withCreds &&
    f.kind !== 'mock' &&
    f.kind !== 'upstream_bot' &&
    (f.auth === 'token' ? !f.token.trim() : !(f.user.trim() && f.pass))
  )
    e.auth = f.auth === 'token' ? 'توکن را وارد کنید' : 'نام کاربری و رمز عبور هر دو لازم است';
  if (f.kind === 'sanaei') {
    if (!/^https?:\/\//.test(f.subUrl.trim()))
      e.subUrl = 'آدرس ساب‌اسکریپشن لازم است (مثال: https://sub.example.com:2096/sub)';
    if (!f.inbounds.length && !extra.template_username) e.inbounds = 'حداقل یک Inbound ID لازم است';
  }
  if (f.kind === 'pasarguard') {
    if (f.scope === 'groups' && !f.groups.length) e.scope = 'حداقل یک Group ID لازم است';
    if (f.scope === 'template' && !(parseInt(f.tpl, 10) > 0)) e.scope = 'شناسه قالب باید عدد مثبت باشد';
  }
  if (!edit && srv.on && !(Number(srv.capacity) >= 1 && Number(srv.capacity) <= 100000))
    e.capacity = 'ظرفیت باید بین ۱ تا ۱۰۰٬۰۰۰ باشد';
  return e;
}

export function PanelDrawer({ panel, groups, idx, onClose, onSubmit, onToggle, onDelete, toggling }) {
  const edit = !!panel;
  const initial = useMemo(
    () => ({
      f: panel ? fromPanel(panel) : EMPTY,
      srv: EMPTY_SRV,
      gids: panel
        ? groups
            .filter((g) => memberIds(g).includes(panel.id))
            .map((g) => g.id)
            .sort()
        : [],
    }),
    [],
  );
  const [f, setF] = useState(initial.f);
  const [srv, setSrv] = useState(initial.srv);
  const [gids, setGids] = useState(initial.gids);
  const base = useRef(JSON.stringify(initial));
  const [changeCred, setChangeCred] = useState(!panel || !panel.has_credentials);
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [srvErr, setSrvErr] = useState('');
  const [adv, setAdv] = useState(() => !!(panel && fromPanel(panel).extra));
  const withCreds = changeCred && f.kind !== 'mock';
  const set = (k) => (v) => {
    setSrvErr('');
    setF((x) => ({ ...x, [k]: v }));
  };
  const setS = (k) => (v) => {
    setSrvErr('');
    setSrv((x) => ({ ...x, [k]: v }));
  };
  const setUb = (fn) => {
    setSrvErr('');
    setF((x) => ({ ...x, ub: fn(x.ub) }));
  };
  const isUb = f.kind === 'upstream_bot';
  const err = useMemo(() => validate(f, withCreds, srv, edit), [f, withCreds, srv, edit]);
  const show = (k) => tried && err[k];
  const dirty =
    JSON.stringify({ f, srv, gids: [...gids].sort() }) !== base.current ||
    (edit && changeCred && !!panel.has_credentials);
  const insecure = !isUb && /^http:\/\//i.test(f.url.trim());
  const toggleG = (id) => setGids((x) => (x.includes(id) ? x.filter((y) => y !== id) : [...x, id]));
  const submit = async (check) => {
    setTried(true);
    if (Object.keys(err).length) {
      if (err.extra) setAdv(true);
      return;
    }
    setBusy(true);
    setSrvErr('');
    const msg = await onSubmit(buildPayload(f, withCreds), check, {
      server:
        !edit && srv.on
          ? { name: srv.name.trim() || f.name.trim(), location: srv.location.trim(), capacity: Number(srv.capacity) }
          : null,
      gids,
      was: initial.gids,
    });
    setBusy(false);
    if (msg) setSrvErr(msg);
  };
  const k = kindOf(f.kind),
    st = panel ? health(panel) : null;
  return (
    <Drawer
      title={edit ? `ویرایش «${panel.name}»` : 'افزودن پنل جدید'}
      subtitle={edit ? `${k.title} · شناسه ${sid(panel.id)}` : 'اتصال یک پنل VPN و تعریف ظرفیت آن در یک مرحله'}
      icon={
        edit ? (
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint(k.tone)}>
            <k.Icon size={20} />
          </span>
        ) : undefined
      }
      dirty={dirty}
      busy={busy}
      onClose={onClose}
      error={srvErr}
      danger={edit && <DeleteButton label="حذف پنل" busy={busy || toggling} onClick={() => onDelete(panel)} />}
      footer={
        <>
          <button className="btn" disabled={busy || (edit && !dirty)} onClick={() => submit(true)}>
            {busy ? <RefreshCw size={15} className="animate-spin" /> : <Activity size={15} />}
            {edit ? 'ذخیره و بررسی سلامت' : 'ثبت و بررسی سلامت'}
          </button>
          <button
            className="btn btn-g !py-2 !text-sm"
            disabled={busy || (edit && !dirty)}
            onClick={() => submit(false)}
          >
            {edit ? (
              <>
                <Save size={14} />
                فقط ذخیره
              </>
            ) : (
              'فقط ثبت'
            )}
          </button>
        </>
      }
    >
      {edit && (
        <Section title="وضعیت">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Dot s={st} ping />
              <Badge s={st} />
              <span className="text-xs text-[var(--mu)]">
                آخرین بررسی: {panel.last_health_at ? dt(panel.last_health_at) : 'هرگز'}
              </span>
            </div>
            <label className="flex cursor-pointer items-center gap-2 text-xs font-bold">
              <Switch
                checked={panel.is_enabled}
                disabled={toggling}
                onChange={(v) => onToggle(panel, v)}
                label={panel.is_enabled ? 'غیرفعال‌سازی پنل' : 'فعال‌سازی پنل'}
              />
              {panel.is_enabled ? 'فعال' : 'غیرفعال'}
            </label>
          </div>
          {st === 'unhealthy' && panel.last_health_error && (
            <p dir="auto" className="break-words rounded-lg bg-[var(--bdb)] p-3 text-xs leading-6 text-[var(--bd)]">
              <b>آخرین خطا: </b>
              {panel.last_health_error}
            </p>
          )}
          {!panel.is_enabled && (
            <p className="text-[11px] leading-5 text-[var(--mu)]">
              پنل غیرفعال برای ساخت اکانت جدید انتخاب نمی‌شود و بررسی سلامت خودکار هم برای آن اجرا نمی‌شود. اکانت‌های
              موجود حذف نمی‌شوند.
            </p>
          )}
          <p className="text-[11px] text-[var(--mu)]">
            ایجاد: {dt(panel.created_at)} · آخرین ویرایش: {dt(panel.updated_at)}
          </p>
        </Section>
      )}

      {!edit && (
        <Section title="۱ · نوع پنل">
          <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="نوع پنل">
            {Object.entries(KINDS).map(([key, m]) => (
              <button
                key={key}
                type="button"
                role="radio"
                aria-checked={f.kind === key}
                onClick={() => set('kind')(key)}
                className={`card p-3 text-right transition ${f.kind === key ? '!border-[var(--ac)] ring-2 ring-[color-mix(in_srgb,var(--ac)_25%,transparent)]' : 'hover:-translate-y-0.5'}`}
              >
                <span className="grid h-9 w-9 place-items-center rounded-lg" style={tint(m.tone)}>
                  <m.Icon size={18} />
                </span>
                <span className="mt-2 block text-sm font-extrabold">{m.title}</span>
                <span className="mt-1 block text-[11px] leading-5 text-[var(--mu)]">{m.desc}</span>
              </button>
            ))}
          </div>
        </Section>
      )}

      <Section title={edit ? 'اتصال' : '۲ · اتصال'}>
        <Field label="نام نمایشی" error={show('name') || undefined}>
          <input
            ref={focusOnMount}
            className="inp"
            value={f.name}
            maxLength={100}
            placeholder={isUb ? 'مثلاً: ربات والد - سرویس اقتصادی' : 'مثلاً: آلمان - هتزنر ۱'}
            onChange={(e) => set('name')(e.target.value)}
          />
        </Field>
        {isUb ? (
          <UpstreamBotLink ub={f.ub} setUb={setUb} error={show('bot') || undefined} />
        ) : (
          <Field
            label="آدرس پنل (Base URL)"
            error={show('url') || undefined}
            hint="آدرس کامل همراه پورت و web base path"
          >
            <input
              dir="ltr"
              inputMode="url"
              spellCheck={false}
              className="inp"
              value={f.url}
              placeholder="https://panel.example.com:2053/secret-path"
              onChange={(e) => set('url')(e.target.value)}
            />
          </Field>
        )}
        {insecure && (
          <p className="flex items-start gap-2 rounded-lg bg-[var(--wnb)] p-3 text-xs leading-6 text-[var(--wn)]">
            <AlertTriangle size={15} className="mt-1 shrink-0" />
            آدرس HTTP است؛ در محیط staging/production فقط HTTPS پذیرفته می‌شود.
          </p>
        )}
      </Section>

      {f.kind !== 'mock' && (
        <Section title={`${edit ? '' : '۳ · '}احراز هویت (رمزنگاری‌شده ذخیره می‌شود)`}>
          {edit && panel.has_credentials && !changeCred ? (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-[var(--sf2)] px-3 py-2.5">
              <span className="flex items-center gap-2 text-xs">
                <ShieldCheck size={15} className="text-[var(--ok)]" />
                اعتبارنامه ذخیره شده است و نمایش داده نمی‌شود.
              </span>
              <button type="button" className="btn btn-g" onClick={() => setChangeCred(true)}>
                تغییر اعتبارنامه
              </button>
            </div>
          ) : (
            <>
              {isUb ? (
                <UpstreamCredentials ub={f.ub} setUb={setUb} show={show} edit={edit} />
              ) : (
                <>
                  <Segmented
                    label="روش ورود"
                    value={f.auth}
                    onChange={set('auth')}
                    options={[
                      ['token', f.kind === 'sanaei' ? 'API Token' : 'API Key'],
                      ['login', 'نام کاربری و رمز'],
                    ]}
                  />
                  {f.auth === 'token' ? (
                    <Field label={f.kind === 'sanaei' ? 'API Token' : 'API Key'} error={show('auth') || undefined}>
                      <Secret value={f.token} onChange={set('token')} placeholder="••••••••" />
                    </Field>
                  ) : (
                    <div className="grid gap-3 sm:grid-cols-2">
                      <Field label="نام کاربری">
                        <input
                          dir="ltr"
                          autoComplete="off"
                          className="inp"
                          value={f.user}
                          onChange={(e) => set('user')(e.target.value)}
                        />
                      </Field>
                      <Field label="رمز عبور">
                        <Secret value={f.pass} onChange={set('pass')} />
                      </Field>
                      {show('auth') && <p className="text-[11px] text-[var(--bd)] sm:col-span-2">{err.auth}</p>}
                    </div>
                  )}
                  {f.kind === 'sanaei' && f.auth === 'login' && (
                    <p className="text-[11px] leading-5 text-[var(--mu)]">
                      اگر 2FA روی پنل فعال است، ورود با نام کاربری کار نمی‌کند؛ از API Token استفاده کنید.
                    </p>
                  )}
                </>
              )}
              {edit && panel.has_credentials && (
                <button
                  type="button"
                  className="text-xs font-bold text-[var(--mu)] underline"
                  onClick={() => {
                    setChangeCred(false);
                    setF((x) => ({
                      ...x,
                      token: '',
                      user: '',
                      pass: '',
                      ub: { ...x.ub, apiId: '', apiHash: '', session: '' },
                    }));
                  }}
                >
                  انصراف از تغییر اعتبارنامه
                </button>
              )}
            </>
          )}
        </Section>
      )}

      {f.kind !== 'mock' && (
        <Section title={`${edit ? '' : '۴ · '}تنظیمات ${k.title}`}>
          {f.kind === 'sanaei' && (
            <>
              <Field
                label="Inbound IDها"
                error={show('inbounds') || undefined}
                hint="شناسه Inboundهایی که کلاینت در آن‌ها ساخته می‌شود؛ بعد از هر عدد Enter بزنید"
              >
                <Chips values={f.inbounds} onChange={set('inbounds')} placeholder="مثلاً 1" />
              </Field>
              <Field
                label="آدرس ساب‌اسکریپشن"
                error={show('subUrl') || undefined}
                hint="Sub Port + Sub Path از Settings → Subscription پنل"
              >
                <input
                  dir="ltr"
                  spellCheck={false}
                  className="inp"
                  value={f.subUrl}
                  placeholder="https://sub.example.com:2096/sub"
                  onChange={(e) => set('subUrl')(e.target.value)}
                />
              </Field>
              <Field label="سبک API">
                <Segmented
                  label="سبک API"
                  value={f.apiStyle}
                  onChange={set('apiStyle')}
                  options={[
                    ['auto', 'خودکار'],
                    ['v3', 'v3'],
                    ['legacy', 'Legacy'],
                  ]}
                />
              </Field>
            </>
          )}
          {isUb && <UpstreamSettings ub={f.ub} setUb={setUb} err={err} show={show} />}
          {f.kind === 'pasarguard' && (
            <>
              <Segmented
                label="محدوده"
                value={f.scope}
                onChange={set('scope')}
                options={[
                  ['groups', 'Group IDs'],
                  ['template', 'قالب کاربر'],
                ]}
              />
              {f.scope === 'groups' ? (
                <Field label="Group IDها" error={show('scope') || undefined}>
                  <Chips values={f.groups} onChange={set('groups')} placeholder="مثلاً 1" />
                </Field>
              ) : (
                <Field label="شناسه قالب کاربر" error={show('scope') || undefined}>
                  <input
                    dir="ltr"
                    inputMode="numeric"
                    className="inp"
                    value={f.tpl}
                    onChange={(e) => set('tpl')(e.target.value.replace(/\D/g, ''))}
                  />
                </Field>
              )}
            </>
          )}
          {!isUb && (
            <Toggle
              checked={f.verifyTls}
              onChange={set('verifyTls')}
              label="بررسی گواهی TLS"
              hint="در محیط عملیاتی خاموش‌کردن آن مجاز نیست؛ فقط برای تست با گواهی self-signed."
            />
          )}
        </Section>
      )}
      {isUb && <UpstreamFlowSection ub={f.ub} />}

      {!edit && (
        <Section
          title="۵ · ظرفیت (اولین سرور)"
          hint="سرور یعنی سقف اکانت‌های فعال روی این پنل. بعداً می‌توانید سرور بیشتری اضافه کنید."
        >
          <Toggle
            checked={srv.on}
            onChange={setS('on')}
            label="همین حالا یک سرور برای این پنل بساز"
            hint="خاموش = پنل بدون سرور ثبت می‌شود و تا اضافه‌کردن سرور اکانتی روی آن ساخته نمی‌شود."
          />
          {srv.on && (
            <>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="نام سرور" hint="خالی = همان نام پنل">
                  <input
                    className="inp"
                    value={srv.name}
                    maxLength={100}
                    placeholder={f.name || 'مثلاً Germany-1'}
                    onChange={(e) => setS('name')(e.target.value)}
                  />
                </Field>
                <Field label="موقعیت (اختیاری)">
                  <input
                    className="inp"
                    value={srv.location}
                    maxLength={100}
                    placeholder="مثلاً آلمان"
                    onChange={(e) => setS('location')(e.target.value)}
                  />
                </Field>
              </div>
              <Field label="ظرفیت" error={show('capacity') || undefined}>
                <NumInput value={srv.capacity} onChange={setS('capacity')} suffix="اکانت" placeholder="500" />
              </Field>
            </>
          )}
        </Section>
      )}

      <Section
        title={edit ? 'بسته‌ها' : '۶ · بسته‌ها (اختیاری)'}
        hint="بسته مشخص می‌کند محصولات کدام پنل‌ها را برای ساخت اکانت بسنجند. محصولاتی که بسته ندارند روی هر پنل سالمی ساخته می‌شوند."
      >
        {groups.length ? (
          <div className="flex flex-wrap gap-2">
            {groups.map((g) => {
              const on = gids.includes(g.id);
              return (
                <button
                  key={g.id}
                  type="button"
                  aria-pressed={on}
                  className={`btn btn-g !py-1 !text-xs ${on ? '!border-[var(--ac)]' : ''}`}
                  onClick={() => toggleG(g.id)}
                >
                  {on ? <Check size={13} /> : <Plus size={13} />}
                  {g.name}
                  {!g.is_enabled && <span className="text-[var(--mu)]">(غیرفعال)</span>}
                </button>
              );
            })}
          </div>
        ) : (
          <p className="text-xs leading-6 text-[var(--mu)]">
            هنوز بسته‌ای ساخته نشده است. از صفحه‌ی «بسته‌های فروش» می‌توانید بسازید.
          </p>
        )}
      </Section>

      <section>
        <button
          type="button"
          className="flex items-center gap-1.5 text-xs font-bold text-[var(--mu)]"
          aria-expanded={adv}
          onClick={() => setAdv(!adv)}
        >
          <ChevronDown size={14} className={adv ? '' : '-rotate-90'} />
          تنظیمات پیشرفته (JSON)
        </button>
        {adv && (
          <div className="mt-2">
            <Field
              label="Config اضافه"
              error={show('extra') || undefined}
              hint={'روی تنظیمات بالا ادغام می‌شود؛ مثلاً {"timeout": 30}'}
            >
              <textarea
                rows={4}
                dir="ltr"
                spellCheck={false}
                className="inp font-mono text-xs"
                value={f.extra}
                onChange={(e) => set('extra')(e.target.value)}
              />
            </Field>
          </div>
        )}
      </section>
      {edit && (
        <p className="flex items-start gap-2 rounded-lg bg-[var(--inb)] p-3 text-[11px] leading-5 text-[var(--in)]">
          <Activity size={14} className="mt-0.5 shrink-0" />
          با تغییر آدرس، تنظیمات یا اعتبارنامه، وضعیت سلامت به «بررسی‌نشده» برمی‌گردد؛ برای اطمینان از اتصال از «ذخیره و
          بررسی سلامت» استفاده کنید.
          {isUb && ' بررسی سلامت این پنل فقط ورود session و دسترسی به ربات را می‌سنجد و هیچ خریدی انجام نمی‌دهد.'}
        </p>
      )}
    </Drawer>
  );
}
