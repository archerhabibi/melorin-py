import { useMemo, useRef, useState } from 'react';
import { BALANCING } from '../../panels/targets.ts';
import { ArrowDown, ArrowUp, ChevronDown, Layers, Plus, Search, X } from 'lucide-react';
import { Drawer, Field, NumInput, Section, Segmented, Toggle, DeleteButton, num, tint } from '../../../shared/kit.tsx';
import { Dot, Warn, health as hs, infraHref, memberIds } from '../../panel-operations/infra.tsx';
import { focusOnMount } from '../../../shared/useDialog.ts';
import { MODES } from './BundleParts.tsx';
import type { CallFn, Json, Rec, Toast } from '../../../shared/types.ts';
import { BundlePackages } from './BundlePackages';
import { ResellerPrices } from './ResellerPrices';

const EMPTY = {
  name: '',
  selection_mode: 'automatic',
  balancing: 'round_robin',
  naming_mode: 'automatic',
  kind_label: '',
  sales_limit: '',
  is_enabled: true,
  reseller_enabled: true,
  panel_ids: [],
  member_labels: {},
};
const fromGroup = (g: Json) => ({
  name: g.name,
  selection_mode: g.selection_mode,
  balancing: g.balancing || 'round_robin',
  naming_mode: g.naming_mode,
  kind_label: g.kind_label || '',
  sales_limit: g.sales_limit ? String(g.sales_limit) : '',
  is_enabled: g.is_enabled,
  reseller_enabled: g.reseller_enabled,
  panel_ids: memberIds(g),
  member_labels: Object.fromEntries((g.panels || []).map((m: Json) => [m.panel_id, m.label || ''])),
});

export function GroupDrawer({
  group,
  panels,
  products,
  idx,
  hasResellers,
  resellerStores,
  call,
  toast,
  onChanged,
  onClose,
  onSubmit,
  onDelete,
}: {
  group?: Json;
  panels?: Json;
  products?: Json;
  idx?: Json;
  hasResellers?: Json;
  resellerStores?: Json;
  call: CallFn;
  toast: Toast;
  onChanged?: Json;
  onClose?: Json;
  onSubmit?: Json;
  onDelete?: Json;
}) {
  const edit = !!group;
  const [f, setF] = useState(() => (group ? fromGroup(group) : EMPTY));
  const base = useRef(JSON.stringify(f));
  const [tried, setTried] = useState(false),
    [busy, setBusy] = useState(false),
    [srv, setSrv] = useState(''),
    [pq, setPq] = useState('');
  const [adv, setAdv] = useState(
    () =>
      !!group &&
      (group.selection_mode !== 'automatic' ||
        (group.balancing || 'round_robin') !== 'round_robin' ||
        group.naming_mode !== 'automatic' ||
        !!group.sales_limit ||
        !!group.kind_label),
  );
  const set = (k: Json) => (v: Json) => {
    setSrv('');
    setF((x) => ({ ...x, [k]: v }));
  };
  const dirty = JSON.stringify(f) !== base.current;
  const byId = useMemo(() => Object.fromEntries(panels.map((p: Json) => [p.id, p])), [panels]);
  const err: Rec = {};
  if (f.name.trim().length < 2) err.name = 'نام بسته حداقل ۲ نویسه باشد';
  if (f.selection_mode === 'manual' && !f.panel_ids.length) err.panels = 'بسته دستی باید حداقل یک پنل داشته باشد';
  if (f.sales_limit !== '' && Number(f.sales_limit) < 1) err.limit = 'سقف باید عدد مثبت باشد یا خالی بماند';
  const toggleP = (id: Json) =>
    set('panel_ids')(f.panel_ids.includes(id) ? f.panel_ids.filter((x: Json) => x !== id) : [...f.panel_ids, id]);
  const setLabel = (id: Json, v: Json) => set('member_labels')({ ...f.member_labels, [id]: v });
  const move = (i: Json, d: Json) => {
    const a = [...f.panel_ids];
    const j = i + d;
    if (j < 0 || j >= a.length) return;
    [a[i], a[j]] = [a[j], a[i]];
    set('panel_ids')(a);
  };
  const avail = panels.filter(
    (p: Json) => !f.panel_ids.includes(p.id) && `${p.name}`.toLowerCase().includes(pq.trim().toLowerCase()),
  );
  const submit = async () => {
    setTried(true);
    if (Object.keys(err).length) {
      if (err.panels) setAdv(true);
      return;
    }
    setBusy(true);
    const msg = await onSubmit(
      { ...f, name: f.name.trim(), sales_limit: f.sales_limit === '' ? null : Number(f.sales_limit) },
      group,
    );
    setBusy(false);
    if (msg) setSrv(msg);
  };
  const noServer = f.panel_ids.filter((id: Json) => !idx.panelStat(id).n);
  return (
    <Drawer
      title={edit ? `ویرایش «${group.name}»` : 'افزودن بسته فروش VPN'}
      subtitle={edit ? `${num(group.sold_count || 0)} فروش ثبت‌شده` : 'نام، پنل‌ها و قیمت پکیج‌ها'}
      icon={
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint('in')}>
          <Layers size={20} />
        </span>
      }
      dirty={dirty}
      busy={busy}
      onClose={onClose}
      error={srv}
      footer={
        <button className="btn !py-2 !text-sm" disabled={busy} onClick={submit}>
          {busy ? 'در حال ذخیره…' : edit ? 'ذخیره تغییرات' : 'ساخت بسته'}
        </button>
      }
      danger={edit && <DeleteButton label="حذف بسته" busy={busy} onClick={() => onDelete(group)} />}
    >
      <Section title="اطلاعات">
        <Field label="نام بسته" error={tried && err.name}>
          <input
            ref={focusOnMount}
            className="inp"
            maxLength={120}
            value={f.name}
            placeholder="مثلاً: آلمان - پرسرعت"
            onChange={(e) => set('name')(e.target.value)}
          />
        </Field>
        <Toggle
          checked={f.is_enabled}
          onChange={set('is_enabled')}
          label="فعال در فروشگاه اصلی"
          hint={
            hasResellers
              ? 'با غیرفعال‌کردن، برای نمایندگان هم نمایش داده نمی‌شود.'
              : 'بسته غیرفعال برای فروش جدید استفاده نمی‌شود.'
          }
        />
        {hasResellers && (
          <div className={f.is_enabled ? '' : 'pointer-events-none opacity-50'}>
            <Toggle
              checked={f.is_enabled && f.reseller_enabled}
              onChange={set('reseller_enabled')}
              label="فعال برای نمایندگان"
              hint={
                f.is_enabled
                  ? 'خاموش = فقط فروشگاه اصلی از این بسته می‌فروشد.'
                  : 'ابتدا بسته را در فروشگاه اصلی فعال کنید.'
              }
            />
          </div>
        )}
      </Section>

      <Section
        title="پنل‌های بسته"
        hint={
          f.selection_mode === 'manual'
            ? 'ترتیب فهرست = ترتیب نمایش برای مشتری؛ نام نمایشی را شما می‌دهید و نام داخلی پنل به مشتری نشان داده نمی‌شود.'
            : 'اکانت جدید روی پنلی ساخته می‌شود که اکانت فعال کمتری دارد؛ اگر برابر بودند، بالاتر در فهرست اولویت دارد.'
        }
      >
        {f.panel_ids.length > 0 && (
          <ol className="space-y-1.5">
            {f.panel_ids.map((id: Json, i: Json) => {
              const p = byId[id];
              return (
                <li
                  key={id}
                  className="flex items-center gap-2 rounded-xl border border-[var(--ln)] bg-[var(--sf2)] px-3 py-2"
                >
                  <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-[var(--mb)] text-[11px] font-extrabold">
                    {num(i + 1)}
                  </span>
                  <Dot s={hs(p)} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-bold">{p?.name || 'پنل حذف‌شده'}</div>
                    <div className="text-[11px] text-[var(--mu)]">
                      {p && !p.is_enabled ? 'غیرفعال · ' : ''}
                      <span className={idx.panelStat(id).n ? '' : 'text-[var(--wn)]'}>
                        {num(idx.panelStat(id).n)} سرور
                      </span>
                    </div>
                  </div>
                  {f.selection_mode === 'manual' && (
                    <input
                      aria-label="نام نمایشی برای مشتری"
                      className="inp !w-36 !py-1 !text-xs"
                      maxLength={80}
                      placeholder="نام نمایشی (مثلاً آلمان)"
                      value={(f.member_labels as Rec)[id] || ''}
                      onChange={(e) => setLabel(id, e.target.value)}
                    />
                  )}
                  <button
                    type="button"
                    className="btn btn-g !px-1.5"
                    aria-label="بالاتر"
                    disabled={i === 0}
                    onClick={() => move(i, -1)}
                  >
                    <ArrowUp size={13} />
                  </button>
                  <button
                    type="button"
                    className="btn btn-g !px-1.5"
                    aria-label="پایین‌تر"
                    disabled={i === f.panel_ids.length - 1}
                    onClick={() => move(i, 1)}
                  >
                    <ArrowDown size={13} />
                  </button>
                  <button
                    type="button"
                    className="btn btn-g btn-d !px-1.5"
                    aria-label="حذف از بسته"
                    onClick={() => toggleP(id)}
                  >
                    <X size={13} />
                  </button>
                </li>
              );
            })}
          </ol>
        )}
        {tried && err.panels && <p className="text-[11px] text-[var(--bd)]">{err.panels}</p>}
        <div>
          <label className="relative block">
            <Search
              size={15}
              className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[var(--mu)]"
            />
            <input
              aria-label="جستجوی پنل"
              className="inp !pr-9"
              placeholder="افزودن پنل… (جستجو)"
              value={pq}
              onChange={(e) => setPq(e.target.value)}
            />
          </label>
          <div className="mt-2 max-h-48 space-y-1 overflow-y-auto">
            {!panels.length ? (
              <p className="p-4 text-center text-xs text-[var(--mu)]">
                هنوز پنلی ساخته نشده؛ ابتدا از «پنل‌ها و سرورها» یک پنل اضافه کنید.
              </p>
            ) : !avail.length ? (
              <p className="p-3 text-center text-xs text-[var(--mu)]">
                {pq ? 'پنلی پیدا نشد' : 'همه‌ی پنل‌ها به بسته اضافه شده‌اند'}
              </p>
            ) : (
              avail.map((p: Json) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => toggleP(p.id)}
                  className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-right text-sm transition hover:bg-[var(--mb)]"
                >
                  <Dot s={hs(p)} />
                  <span className="min-w-0 flex-1 truncate font-bold">{p.name}</span>
                  <span className="text-[11px] text-[var(--mu)]">
                    {!p.is_enabled ? 'غیرفعال · ' : ''}
                    {num(idx.panelStat(p.id).n)} سرور
                  </span>
                  <Plus size={14} className="text-[var(--ac)]" />
                </button>
              ))
            )}
          </div>
        </div>
        {noServer.length > 0 && (
          <Warn>
            برخی پنل‌های بسته هنوز سرور ندارند؛ تا سرور اضافه نشود اکانتی روی آن‌ها ساخته نمی‌شود.{' '}
            <a className="underline" href={infraHref('panels', { id: noServer[0], add: 'server' })}>
              افزودن سرور
            </a>
          </Warn>
        )}
        {edit && (
          <p className="text-[11px] leading-5 text-[var(--mu)]">
            حذف یا تغییر ترتیب پنل‌ها، آمار فروش پنل‌های باقی‌مانده را حفظ می‌کند.
          </p>
        )}
      </Section>

      {edit ? (
        <BundlePackages
          group={group}
          products={products}
          hasResellers={hasResellers}
          call={call}
          toast={toast}
          onChanged={onChanged}
        />
      ) : (
        <p className="rounded-xl bg-[var(--sf2)] px-4 py-3 text-xs leading-6 text-[var(--mu)]">
          همه‌ی پکیج‌ها به‌صورت پیش‌فرض در بسته‌ی جدید فعال‌اند؛ بعد از ساخت، قیمت هر پکیج را همین‌جا تنظیم کنید.
        </p>
      )}

      {edit && resellerStores.length > 0 && <ResellerPrices group={group} stores={resellerStores} call={call} />}

      <section>
        <button
          type="button"
          className="flex items-center gap-1.5 text-xs font-bold text-[var(--mu)]"
          aria-expanded={adv}
          onClick={() => setAdv(!adv)}
        >
          <ChevronDown size={14} className={adv ? '' : '-rotate-90'} />
          تنظیمات بیشتر{f.selection_mode === 'manual' && <span className="badge b-in">انتخاب دستی</span>}
        </button>
        {adv && (
          <div className="mt-3 space-y-4">
            <Section title="نمایش و سقف">
              <Field label="برچسب بسته" hint="اختیاری. متنی که کنار نام بسته به مشتری نشان داده می‌شود (مثلاً مستقیم).">
                <input
                  className="inp"
                  maxLength={40}
                  value={f.kind_label}
                  placeholder="مثلاً: مستقیم"
                  onChange={(e) => set('kind_label')(e.target.value)}
                />
              </Field>
              <Field
                label="سقف فروش بسته"
                error={tried && err.limit}
                hint="خالی = نامحدود؛ با رسیدن به سقف، فروش از این بسته متوقف می‌شود"
              >
                <NumInput value={f.sales_limit} onChange={set('sales_limit')} placeholder="نامحدود" suffix="اکانت" />
              </Field>
            </Section>
            <Section title="نحوه‌ی انتخاب پنل">
              <Segmented
                label="نحوه‌ی انتخاب پنل"
                value={f.selection_mode}
                onChange={set('selection_mode')}
                options={Object.entries(MODES).map(([k, [t]]) => [k, t])}
              />
              <p className="text-[11px] leading-5 text-[var(--mu)]">{(MODES as Rec)[f.selection_mode][1]}</p>
            </Section>
            {f.selection_mode === 'automatic' && (
              <Section title="روش توزیع بین مقصدها">
                <Segmented
                  label="روش توزیع"
                  value={f.balancing}
                  onChange={set('balancing')}
                  options={Object.entries(BALANCING).map(([k, [t]]) => [k, t])}
                />
                <p className="text-[11px] leading-5 text-[var(--mu)]">{BALANCING[f.balancing][1]}</p>
              </Section>
            )}
            <Section title="نام کاربری اکانت‌ها">
              <Field
                hint={
                  f.naming_mode === 'custom'
                    ? 'مشتری هنگام خرید نام کاربری را وارد می‌کند (اجباری، حداقل ۳ نویسه)'
                    : 'نام کاربری به‌صورت خودکار ساخته می‌شود'
                }
              >
                <Segmented
                  label="نام‌گذاری"
                  value={f.naming_mode}
                  onChange={set('naming_mode')}
                  options={[
                    ['automatic', 'خودکار'],
                    ['custom', 'دلخواه مشتری'],
                  ]}
                />
              </Field>
            </Section>
          </div>
        )}
      </section>
    </Drawer>
  );
}
