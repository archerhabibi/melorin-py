import { useEffect, useMemo, useRef, useState } from 'react';
import { BALANCING } from '../targets.ts';
import { ArrowDown, ArrowUp, ChevronDown, Layers, Plus, Search, X } from 'lucide-react';
import {
  Drawer,
  Field,
  NumInput,
  Section,
  Segmented,
  Switch,
  Toggle,
  DeleteButton,
  errText,
  num,
  tint,
} from '../kit.tsx';
import { Dot, Warn, health as hs, infraHref, memberIds } from '../infra.tsx';
import { focusOnMount } from '../useDialog.ts';
import { API, MODES } from './BundleParts.tsx';
import type { Json, Rec } from '../types.ts';

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

/** The packages of a bundle. Every package is here by default; the switch hides it in THIS bundle only.
 *  Price fields: the store price in this bundle and, only when resellers exist, the cooperation price they pay.
 *  An empty field = the product's own price. These prices are the same for every reseller (no per-store prices). */
function BundlePackages({ group, products, hasResellers, call, toast, onChanged }: { group?: Json; products?: Json; hasResellers?: Json; call?: Json; toast?: Json; onChanged?: Json }) {
  const [rows, setRows] = useState<Json>(null),
    [draft, setDraft] = useState<Rec>({}),
    [busy, setBusy] = useState(''),
    [saving, setSaving] = useState(false),
    [q, setQ] = useState('');
  const load = async () => {
    try {
      const r = await call(`${API}/${group.id}/products`);
      setRows(r.ok ? await r.json() : []);
    } catch {
      setRows([]);
    }
  };
  useEffect(() => {
    load();
  }, [group.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const body = (row: Json, patch: Json) => ({
    main_price: row.main_price,
    reseller_price: row.reseller_price,
    is_listed: row.is_listed,
    sort: row.sort,
    ...patch,
  });
  const put = async (row: Json, patch: Json, quiet?: boolean) => {
    const r = await call(`${API}/${group.id}/products/${row.product_id}`, {
      method: 'PUT',
      body: JSON.stringify(body(row, patch)),
    });
    if (!r.ok) {
      if (!quiet) toast(await errText(r, 'ذخیره پکیج ناموفق بود'));
      return false;
    }
    try {
      const out = await r.clone().json();
      if (out?.stores_below_cost > 0)
        toast(
          `${out.stores_below_cost} فروشگاه نماینده قیمت فروششان از این قیمت نماینده کمتر است و این پکیج برایشان نمایش داده نمی‌شود تا قیمتشان را بالا ببرند.`,
        );
    } catch {
      /* no warning */
    }
    return true;
  };
  const toggleListed = async (row: Json, v: Json) => {
    setBusy(row.product_id);
    const ok = await put(row, { is_listed: v });
    setBusy('');
    if (ok) {
      await load();
      onChanged?.();
    }
  };
  const n2 = (v: Json) => (v === '' || v == null ? null : Number(v));
  const dirtyRows = (rows || []).filter(
    (r: Json) => draft[r.product_id] && (draft[r.product_id].main !== undefined || draft[r.product_id].res !== undefined),
  );
  const saveAll = async () => {
    setSaving(true);
    let bad = 0;
    for (const r of dirtyRows) {
      const d = draft[r.product_id];
      if (
        !(await put(
          r,
          {
            main_price: d.main !== undefined ? n2(d.main) : r.main_price,
            reseller_price: d.res !== undefined ? n2(d.res) : r.reseller_price,
          },
          true,
        ))
      )
        bad++;
    }
    setSaving(false);
    toast(bad ? `${num(bad)} پکیج ذخیره نشد` : 'قیمت‌ها ذخیره شد');
    if (!bad) setDraft({});
    await load();
    onChanged?.();
  };
  const add = async (p: Json) => {
    setBusy(p.id);
    const ok = await put(
      { product_id: p.id, main_price: null, reseller_price: null, sort: (rows || []).length },
      { is_listed: true },
    );
    setBusy('');
    if (ok) {
      await load();
      onChanged?.();
    }
  };
  const have = new Set((rows || []).map((x: Json) => x.product_id));
  const missing = products.filter(
    (p: Json) => !p.is_test && !have.has(p.id) && `${p.name} ${p.code}`.toLowerCase().includes(q.trim().toLowerCase()),
  );
  const field = (r: Json, k: Json, ph: Json) => (
    <NumInput
      aria-label={`${k === 'main' ? 'قیمت فروشگاه' : 'قیمت نماینده'} ${r.name}`}
      value={draft[r.product_id]?.[k] ?? (k === 'main' ? r.main_price : r.reseller_price) ?? ''}
      placeholder={String(ph)}
      onChange={(v: Json) => setDraft((x) => ({ ...x, [r.product_id]: { ...x[r.product_id], [k]: v } }))}
    />
  );
  return (
    <Section
      title="پکیج‌ها و قیمت"
      hint={
        hasResellers
          ? 'همه‌ی پکیج‌ها به‌صورت پیش‌فرض در این بسته فعال‌اند. خالی‌گذاشتن قیمت یعنی قیمت خود محصول. قیمت نماینده برای همه‌ی نماینده‌ها یکسان است.'
          : 'همه‌ی پکیج‌ها به‌صورت پیش‌فرض در این بسته فعال‌اند. خالی‌گذاشتن قیمت یعنی قیمت خود محصول.'
      }
    >
      {rows === null ? (
        <div className="skel h-16 rounded-xl" />
      ) : !rows.length ? (
        <p className="rounded-xl bg-[var(--sf2)] p-3 text-xs text-[var(--wn)]">
          هنوز پکیجی در این بسته نیست؛ ابتدا از صفحه‌ی «محصولات» یک پکیج بسازید.
        </p>
      ) : (
        <ul className="space-y-2">
          {rows.map((r: Json) => {
            const d = draft[r.product_id] || {};
            const dirty = d.main !== undefined || d.res !== undefined;
            return (
              <li
                key={r.product_id}
                className={`rounded-xl border bg-[var(--sf2)] p-3 ${dirty ? 'border-[var(--wn)]' : 'border-[var(--ln)]'}`}
              >
                <div className="flex items-center gap-2">
                  <div className={`min-w-0 flex-1 ${r.is_listed ? '' : 'opacity-55'}`}>
                    <div className="truncate text-sm font-bold">
                      {r.name}
                      {!r.is_active && <span className="mr-1.5 badge b-mu">غیرفعال در محصولات</span>}
                      {r.is_active && hasResellers && r.reseller_enabled === false && (
                        <span className="mr-1.5 badge b-mu">خاموش برای نمایندگان</span>
                      )}
                    </div>
                    <div className="text-[11px] text-[var(--mu)]">قیمت محصول {num(r.base_main_price)}</div>
                  </div>
                  <label className="flex cursor-pointer items-center gap-1.5 text-[11px] font-bold">
                    <Switch
                      checked={r.is_listed}
                      disabled={busy === r.product_id || saving}
                      onChange={(v: Json) => toggleListed(r, v)}
                      label={`فعال بودن ${r.name} در این بسته`}
                    />
                    {r.is_listed ? 'فعال' : 'پنهان'}
                  </label>
                </div>
                {r.is_listed && (
                  <div className={`mt-2 grid gap-2 ${hasResellers ? 'sm:grid-cols-2' : ''}`}>
                    <Field label="قیمت فروشگاه در این بسته">{field(r, 'main', r.base_main_price)}</Field>
                    {hasResellers && <Field label="قیمت نماینده">{field(r, 'res', r.base_reseller_price)}</Field>}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {dirtyRows.length > 0 && (
        <div className="flex gap-2">
          <button type="button" className="btn !py-1.5 !text-xs" disabled={saving} onClick={saveAll}>
            {saving ? 'در حال ذخیره…' : `ذخیره‌ی قیمت‌ها (${num(dirtyRows.length)})`}
          </button>
          <button type="button" className="btn btn-g !py-1.5 !text-xs" disabled={saving} onClick={() => setDraft({})}>
            لغو تغییرات
          </button>
        </div>
      )}
      {rows !== null && products.some((p: Json) => !p.is_test && !have.has(p.id)) && (
        <details className="rounded-xl bg-[var(--sf2)] p-3 text-xs">
          <summary className="cursor-pointer font-bold text-[var(--mu)]">افزودن پکیج‌های جاافتاده</summary>
          <label className="relative mt-2 block">
            <Search
              size={15}
              className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[var(--mu)]"
            />
            <input
              aria-label="جستجوی پکیج"
              className="inp !pr-9"
              placeholder="جستجو…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </label>
          <div className="mt-2 max-h-40 space-y-1 overflow-y-auto">
            {missing.map((p: Json) => (
              <button
                key={p.id}
                type="button"
                disabled={!!busy}
                onClick={() => add(p)}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-right text-sm transition hover:bg-[var(--mb)]"
              >
                <span className="min-w-0 flex-1 truncate font-bold">{p.name}</span>
                <Plus size={14} className="text-[var(--ac)]" />
              </button>
            ))}
          </div>
        </details>
      )}
    </Section>
  );
}

/** READ-ONLY: what each reseller store charges in this bundle. The admin cannot change these; resellers set them. */
function ResellerPrices({ group, stores, call }: { group?: Json; stores?: Json; call?: Json }) {
  const [sid, setSid] = useState(stores[0]?.id || ''),
    [rows, setRows] = useState<Json>(null);
  useEffect(() => {
    if (!sid) return;
    setRows(null);
    call(`/api/v1/admin/stores/${sid}/reseller-prices`)
      .then((r: Json) => (r.ok ? r.json() : []))
      .then(setRows)
      .catch(() => setRows([]));
  }, [sid]); // eslint-disable-line react-hooks/exhaustive-deps
  const list = (rows || [])
    .map((r: Json) => ({ r, b: (r.bundles || []).find((x: Json) => x.bundle_id === group.id) }))
    .filter((x: Json) => x.b);
  const ST: Rec = { ok: ['ok', 'قابل فروش'], unset: ['mu', 'قیمت ندارد'], below_cost: ['bd', 'زیر قیمت نماینده'] };
  return (
    <Section
      title="قیمت فروش نمایندگان (فقط نمایش)"
      hint="این قیمت‌ها را خود نماینده تعیین می‌کند و ادمین نمی‌تواند تغییرشان دهد."
    >
      <select aria-label="نماینده" className="inp" value={sid} onChange={(e) => setSid(e.target.value)}>
        {stores.map((s: Json) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
      {rows === null ? (
        <div className="skel h-12 rounded-xl" />
      ) : !list.length ? (
        <p className="text-xs text-[var(--mu)]">پکیجی برای نمایش نیست.</p>
      ) : (
        <div className="overflow-auto">
          <table className="tbl2 min-w-[420px]">
            <thead>
              <tr>
                {['پکیج', 'قیمت نماینده', 'قیمت فروش او', 'وضعیت'].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {list.map(({ r, b }: Json) => {
                const [t, l] = ST[b.state] || ST.unset;
                return (
                  <tr key={r.product_id}>
                    <td className="font-bold">{r.name}</td>
                    <td className="num">{num(b.cost)}</td>
                    <td className="num">{b.effective_price ? num(b.effective_price) : '—'}</td>
                    <td>
                      <span className={`badge b-${t}`}>{l}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

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
}: { group?: Json; panels?: Json; products?: Json; idx?: Json; hasResellers?: Json; resellerStores?: Json; call?: Json; toast?: Json; onChanged?: Json; onClose?: Json; onSubmit?: Json; onDelete?: Json }) {
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
