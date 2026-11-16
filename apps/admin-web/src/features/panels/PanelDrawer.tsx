import { useMemo, useRef, useState } from 'react';
import { Badge, dt, sid } from '../../shared/ui.tsx';
import { Dot, health, memberIds } from '../panel-operations/infra.tsx';
import { Drawer, Field, NumInput, Section, Switch, Toggle, DeleteButton, tint } from '../../shared/kit.tsx';
import { Activity, AlertTriangle, Check, ChevronDown, Plus, RefreshCw, Save } from 'lucide-react';
import { focusOnMount } from '../../shared/useDialog.ts';
import { UpstreamBotLink } from './UpstreamBotFields.tsx';
import { UpstreamFlowSection } from './UpstreamFlowParts.tsx';
import { KINDS, kindOf } from './panelUi.tsx';
import type { Json } from '../../shared/types.ts';
import { EMPTY, EMPTY_SRV, fromPanel, buildPayload, validate } from './panelForm';
import { PanelCredentialsSection } from './PanelCredentialsSection.tsx';
import { PanelConnectionSection } from './PanelConnectionSection.tsx';

export function PanelDrawer({
  panel,
  groups,
  idx,
  onClose,
  onSubmit,
  onToggle,
  onDelete,
  toggling,
}: {
  panel?: Json;
  groups?: Json;
  idx?: Json;
  onClose?: Json;
  onSubmit?: Json;
  onToggle?: Json;
  onDelete?: Json;
  toggling?: Json;
}) {
  const edit = !!panel;
  const initial = useMemo(
    () => ({
      f: panel ? fromPanel(panel) : EMPTY,
      srv: EMPTY_SRV,
      gids: panel
        ? groups
            .filter((g: Json) => memberIds(g).includes(panel.id))
            .map((g: Json) => g.id)
            .sort()
        : [],
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
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
  const set = (k: Json) => (v: Json) => {
    setSrvErr('');
    setF((x) => ({ ...x, [k]: v }));
  };
  const setS = (k: Json) => (v: Json) => {
    setSrvErr('');
    setSrv((x) => ({ ...x, [k]: v }));
  };
  const setUb = (fn: Json) => {
    setSrvErr('');
    setF((x) => ({ ...x, ub: fn(x.ub) }));
  };
  const isUb = f.kind === 'upstream_bot';
  const err = useMemo(() => validate(f, withCreds, srv, edit), [f, withCreds, srv, edit]);
  const show = (k: Json) => tried && err[k];
  const dirty =
    JSON.stringify({ f, srv, gids: [...gids].sort() }) !== base.current ||
    (edit && changeCred && !!panel.has_credentials);
  const insecure = !isUb && /^http:\/\//i.test(f.url.trim());
  const toggleG = (id: Json) => setGids((x: Json) => (x.includes(id) ? x.filter((y: Json) => y !== id) : [...x, id]));
  const submit = async (check: Json) => {
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
                onChange={(v: Json) => onToggle(panel, v)}
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

      <PanelConnectionSection
        changeCred={changeCred}
        edit={edit}
        err={err}
        f={f}
        isUb={isUb}
        panel={panel}
        set={set}
        setChangeCred={setChangeCred}
        setF={setF}
        setUb={setUb}
        show={show}
      />
      <PanelCredentialsSection
        edit={edit}
        err={err}
        f={f}
        groups={groups}
        isUb={isUb}
        k={k}
        set={set}
        setUb={setUb}
        show={show}
      />
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
            {groups.map((g: Json) => {
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
