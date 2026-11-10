import { useEffect, useMemo, useRef, useState } from 'react';

import { Boxes, ChevronDown, Clock, Infinity as Inf, Pencil, Save, Smartphone, Tag, Zap } from 'lucide-react';
import { Drawer, Field, NumInput, Section, Segmented, Switch, Toggle, DeleteButton, num, tint } from './kit.jsx'; // #4

import { focusOnMount } from './useDialog.js';

import { CUR, price, dur, gb, EMPTY, fromProduct, payload, validate, Route } from './productsShared.jsx';

export function ProductDrawer({ product, products, hasResellers, onClose, onSubmit, onDelete }) {
  const edit = !!product;
  const taken = useMemo(
    () => new Set((products || []).filter((x) => x.id !== product?.id).map((x) => x.code)),
    [products, product],
  );
  const suggestCode = (f) => {
    const base = `vpn-${+f.duration_days || 0}d-${f.unlimited_traffic ? 'unl' : `${+f.traffic_gb || 0}g`}`;
    let code = base,
      n = 2;
    while (taken.has(code)) code = `${base}-${n++}`;
    return code;
  };
  const [f, setF] = useState(() => (product ? fromProduct(product) : { ...EMPTY, code: suggestCode(EMPTY) }));
  const base = useRef(JSON.stringify(f));
  const [tried, setTried] = useState(false),
    [busy, setBusy] = useState(false),
    [srv, setSrv] = useState('');
  const [codeTouched, setCodeTouched] = useState(edit),
    [more, setMore] = useState(false);
  const set = (k) => (v) => {
    setSrv('');
    setF((x) => ({ ...x, [k]: v }));
  };
  // New product: the code follows the plan (duration + traffic) until the admin edits it by hand.
  useEffect(() => {
    if (!edit && !codeTouched) setF((x) => ({ ...x, code: suggestCode(x) }));
  }, [f.duration_days, f.traffic_gb, f.unlimited_traffic, codeTouched, edit, taken]); // eslint-disable-line react-hooks/exhaustive-deps
  const err = useMemo(() => validate(f), [f]);
  const dirty = JSON.stringify(f) !== base.current;
  const submit = async () => {
    setTried(true);
    if (Object.keys(err).length) {
      if (err.code) setMore(true);
      return;
    }
    setBusy(true);
    const m = await onSubmit(payload(f), f.is_active, product);
    setBusy(false);
    if (m) setSrv(m);
  };
  const show = (k) => tried && err[k];
  return (
    <Drawer
      title={edit ? `ویرایش «${product.name}»` : 'افزودن محصول'}
      subtitle={edit ? `کد ${product.code}` : 'مدت، حجم و قیمت فروشگاه'}
      icon={
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint('ok')}>
          <Boxes size={20} />
        </span>
      }
      dirty={dirty}
      busy={busy}
      onClose={onClose}
      error={srv}
      footer={
        <button className="btn !py-2 !text-sm" disabled={busy} onClick={submit}>
          <Save size={15} />
          {busy ? 'در حال ذخیره…' : edit ? 'ذخیره تغییرات' : 'ساخت محصول'}
        </button>
      }
      danger={edit && <DeleteButton label="حذف محصول" busy={busy} onClick={() => onDelete(product)} />}
    >
      <Section title="مشخصات">
        <Field label="نام محصول" error={show('name')}>
          <input
            ref={focusOnMount}
            className="inp"
            maxLength={200}
            placeholder="مثلاً: ۳۰ روزه ۵۰ گیگ"
            value={f.name}
            onChange={(e) => set('name')(e.target.value)}
          />
        </Field>
        <Field label="مدت اعتبار" error={show('duration_days')}>
          <div className="space-y-2">
            <div className="flex flex-wrap gap-1.5">
              {[7, 30, 60, 90, 180, 365].map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => set('duration_days')(String(d))}
                  className={`btn btn-g ${+f.duration_days === d ? '!border-[var(--ac)] !text-[var(--ac)]' : ''}`}
                >
                  {dur(d)}
                </button>
              ))}
            </div>
            <NumInput value={f.duration_days} onChange={set('duration_days')} suffix="روز" />
          </div>
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="حجم ترافیک" error={show('traffic_gb')}>
            <div className="space-y-2">
              <NumInput
                value={f.unlimited_traffic ? '' : f.traffic_gb}
                disabled={f.unlimited_traffic}
                placeholder={f.unlimited_traffic ? 'نامحدود' : ''}
                onChange={set('traffic_gb')}
                suffix="گیگ"
              />
              <Toggle checked={f.unlimited_traffic} onChange={set('unlimited_traffic')} label="نامحدود" />
            </div>
          </Field>
          <Field label="تعداد دستگاه هم‌زمان" error={show('max_devices')}>
            <div className="space-y-2">
              <NumInput
                value={f.unlimited_devices ? '' : f.max_devices}
                disabled={f.unlimited_devices}
                placeholder={f.unlimited_devices ? 'بدون محدودیت' : ''}
                onChange={set('max_devices')}
                suffix="دستگاه"
              />
              <Toggle checked={f.unlimited_devices} onChange={set('unlimited_devices')} label="بدون محدودیت" />
            </div>
          </Field>
        </div>
      </Section>
      <Section
        title="قیمت فروشگاه"
        hint={
          hasResellers
            ? 'قیمت نماینده و قیمت هر بسته از صفحه‌ی «بسته‌های فروش» تنظیم می‌شود؛ قیمت فروش هر نماینده را خودش تعیین می‌کند.'
            : 'قیمت هر بسته را هم می‌توانید از صفحه‌ی «بسته‌های فروش» جدا تنظیم کنید.'
        }
      >
        <div className="grid gap-4 sm:grid-cols-[auto_1fr]">
          <Field label="واحد پول">
            <Segmented label="واحد پول" value={f.currency} onChange={set('currency')} options={Object.entries(CUR)} />
          </Field>
          <Field label="قیمت فروشگاه" error={show('main_price')}>
            <NumInput value={f.main_price} onChange={set('main_price')} suffix={CUR[f.currency]} />
          </Field>
        </div>
      </Section>
      <Section
        title="وضعیت"
        hint="این محصول به‌صورت پیش‌فرض در همه‌ی بسته‌های فروش فعال است. هر بسته را می‌توانید از صفحه‌ی همان بسته پنهان کنید."
      >
        <Toggle
          checked={f.is_active}
          onChange={set('is_active')}
          label="فعال در فروشگاه اصلی"
          hint={
            hasResellers
              ? 'با غیرفعال‌کردن، برای نمایندگان هم نمایش داده نمی‌شود.'
              : 'محصول غیرفعال برای خرید جدید نمایش داده نمی‌شود.'
          }
        />
        {hasResellers && (
          <div className={f.is_active ? '' : 'pointer-events-none opacity-50'}>
            <Toggle
              checked={f.is_active && f.reseller_enabled}
              onChange={set('reseller_enabled')}
              label="فعال برای نمایندگان"
              hint={
                f.is_active
                  ? 'خاموش = فقط فروشگاه اصلی این محصول را می‌فروشد.'
                  : 'ابتدا محصول را در فروشگاه اصلی فعال کنید.'
              }
            />
          </div>
        )}
      </Section>
      <section>
        <button
          type="button"
          className="flex items-center gap-1.5 text-xs font-bold text-[var(--mu)]"
          aria-expanded={more}
          onClick={() => setMore(!more)}
        >
          <ChevronDown size={14} className={more ? '' : '-rotate-90'} />
          کد، دسته‌بندی و توضیح
          <span dir="ltr" className="font-mono font-normal">
            {f.code}
          </span>
          {f.is_test && <span className="badge b-wn">تست</span>}
        </button>
        {more && (
          <div className="mt-3 space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                label="کد محصول"
                error={show('code')}
                hint={
                  edit
                    ? 'تغییر کد روی اتصال‌های بیرونی (API/بات) اثر می‌گذارد.'
                    : 'خودکار از مدت و حجم ساخته می‌شود؛ در صورت نیاز ویرایش کنید.'
                }
              >
                <input
                  dir="ltr"
                  spellCheck={false}
                  className="inp font-mono"
                  maxLength={50}
                  value={f.code}
                  onChange={(e) => {
                    setCodeTouched(true);
                    set('code')(e.target.value);
                  }}
                />
              </Field>
              <Field label="دسته‌بندی" hint="اختیاری">
                <input
                  className="inp"
                  maxLength={100}
                  value={f.category}
                  onChange={(e) => set('category')(e.target.value)}
                />
              </Field>
            </div>
            <Field label="توضیحات" hint="اختیاری">
              <input className="inp" value={f.description} onChange={(e) => set('description')(e.target.value)} />
            </Field>
            <Toggle
              checked={f.is_test}
              onChange={set('is_test')}
              label="محصول آزمایشی (تست)"
              hint="برای اکانت‌های آزمایشی؛ برای فروش عادی خاموش بماند."
            />
          </div>
        )}
      </section>
    </Drawer>
  );
}

export function Switches({ p, busy, hasResellers, onToggle, onToggleReseller }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <label className="flex cursor-pointer items-center gap-2 text-xs font-bold">
        <Switch
          checked={p.is_active}
          disabled={busy}
          onChange={(v) => onToggle(p, v)}
          label={`فعال‌سازی ${p.name} در فروشگاه اصلی`}
        />
        {hasResellers ? 'فروشگاه اصلی' : p.is_active ? 'فعال' : 'غیرفعال'}
      </label>
      {hasResellers && (
        <label
          className={`flex cursor-pointer items-center gap-2 text-xs font-bold ${p.is_active ? '' : 'opacity-50'}`}
          title={p.is_active ? '' : 'ابتدا در فروشگاه اصلی فعال کنید'}
        >
          <Switch
            checked={p.is_active && p.reseller_enabled !== false}
            disabled={busy || !p.is_active}
            onChange={(v) => onToggleReseller(p, v)}
            label={`فعال‌سازی ${p.name} برای نمایندگان`}
          />
          نمایندگان
        </label>
      )}
    </div>
  );
}

export function ProductCard({ p, idx, busy, hasResellers, onEdit, onToggle, onToggleReseller, onDelete }) {
  const r = idx.reach(p),
    dim = p.is_active ? '' : 'opacity-55';
  const state = !p.is_active ? 'off' : r.ok ? 'ok' : 'bd';
  return (
    <article
      className={`card card-i rise stripe flex flex-col gap-4 p-5 ${state === 'off' ? 'off' : ''}`}
      style={{ '--stripe': state === 'ok' ? 'var(--ok)' : state === 'bd' ? 'var(--bd)' : 'var(--ln)' }}
    >
      <div className={`flex items-start gap-3 ${dim}`}>
        <span className="tile h-12 w-12" style={tint(p.is_test ? 'wn' : 'ok')}>
          <Zap size={22} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-base font-extrabold" title={p.name}>
            {p.name}
          </h3>
          <p dir="ltr" className="mt-0.5 truncate text-right font-mono text-[11px] text-[var(--mu)]">
            {p.code}
          </p>
        </div>
        {p.is_test && <span className="badge b-wn">تست</span>}
      </div>
      <div className={`flex flex-wrap gap-1.5 ${dim}`}>
        {[
          [Clock, dur(p.duration_days)],
          [p.traffic_gb ? Zap : Inf, gb(p.traffic_gb)],
          [Smartphone, p.max_devices ? `${num(p.max_devices)} دستگاه` : 'دستگاه نامحدود'],
        ].map(([I, t], i) => (
          <span key={i} className="spec">
            <I size={13} className="text-[var(--mu)]" />
            {t}
          </span>
        ))}
        {p.category && (
          <span className="spec">
            <Tag size={13} className="text-[var(--mu)]" />
            {p.category}
          </span>
        )}
      </div>
      <div className={`price num ${dim}`}>
        {num(p.main_price)}
        <span className="mr-1.5 text-xs font-bold text-[var(--mu)]">{CUR[p.currency] || p.currency}</span>
      </div>
      {p.is_active && <Route p={p} idx={idx} />}
      <div className="mt-auto flex items-center justify-between gap-2 border-t border-[var(--ln)] pt-3">
        <Switches
          p={p}
          busy={busy}
          hasResellers={hasResellers}
          onToggle={onToggle}
          onToggleReseller={onToggleReseller}
        />
        <div className="flex items-center gap-1.5">
          <DeleteButton compact label={`حذف ${p.name}`} busy={busy} onClick={() => onDelete(p)} />
          <button className="btn btn-g" onClick={() => onEdit(p)}>
            <Pencil size={13} />
            ویرایش
          </button>
        </div>
      </div>
    </article>
  );
}

export function ProductTable({
  rows,
  idx,
  busy,
  hasResellers,
  onEdit,
  onToggle,
  onToggleReseller,
  onDelete,
  quick,
  draft,
  setDraft,
}) {
  return (
    <section className="card rise overflow-hidden">
      <div className="overflow-auto">
        <table className="tbl2 min-w-[760px]">
          <thead>
            <tr>
              {[
                'محصول',
                'مدت',
                'ترافیک',
                'دستگاه',
                'قیمت فروشگاه',
                'فروش',
                'فروشگاه اصلی',
                ...(hasResellers ? ['نمایندگان'] : []),
                '',
              ].map((h, i) => (
                <th key={i}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => {
              const d = draft[p.id]?.main_price,
                dirty = quick && d !== undefined && d !== String(p.main_price);
              const r = idx.reach(p);
              return (
                <tr key={p.id} className={`${p.is_active ? '' : 'opacity-60'} ${dirty ? '!bg-[var(--wnb)]' : ''}`}>
                  <td>
                    <div className="font-bold">
                      {p.name}
                      {p.is_test && <span className="badge b-wn mr-2">تست</span>}
                    </div>
                    <div dir="ltr" className="text-right font-mono text-[11px] text-[var(--mu)]">
                      {p.code}
                    </div>
                  </td>
                  <td>{dur(p.duration_days)}</td>
                  <td>{gb(p.traffic_gb)}</td>
                  <td>{p.max_devices ? num(p.max_devices) : '∞'}</td>
                  <td>
                    {quick ? (
                      <div className="w-36">
                        <NumInput
                          aria-label={`قیمت ${p.name}`}
                          value={d ?? String(p.main_price)}
                          onChange={(v) => setDraft((x) => ({ ...x, [p.id]: { main_price: v } }))}
                        />
                      </div>
                    ) : (
                      <span className="font-semibold">{price(p.main_price, p.currency)}</span>
                    )}
                  </td>
                  <td className="min-w-[130px]">
                    {r.ok ? (
                      <span className="badge b-ok" title={(r.groups || []).map((x) => x.name).join('، ')}>
                        {num(r.live.length)} سرور · {num(r.free)} آزاد
                      </span>
                    ) : (
                      <span className="badge b-bd" title={r.issue}>
                        مسیر ندارد
                      </span>
                    )}
                  </td>
                  <td>
                    <Switch
                      checked={p.is_active}
                      disabled={busy.has(p.id)}
                      onChange={(v) => onToggle(p, v)}
                      label={`فعال‌سازی ${p.name}`}
                    />
                  </td>
                  {hasResellers && (
                    <td>
                      <Switch
                        checked={p.is_active && p.reseller_enabled !== false}
                        disabled={busy.has(p.id) || !p.is_active}
                        onChange={(v) => onToggleReseller(p, v)}
                        label={`فعال‌سازی ${p.name} برای نمایندگان`}
                      />
                    </td>
                  )}
                  <td>
                    <div className="flex items-center gap-1.5">
                      <button className="btn btn-g" onClick={() => onEdit(p)}>
                        <Pencil size={13} />
                        ویرایش
                      </button>
                      {!quick && (
                        <DeleteButton
                          compact
                          label={`حذف ${p.name}`}
                          busy={busy.has(p.id)}
                          onClick={() => onDelete(p)}
                        />
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

