import { useEffect, useState } from 'react';
import { Plus, Search } from 'lucide-react';
import { Field, NumInput, Section, Switch, errText, num } from '../../../shared/kit.tsx';
import { API } from './BundleParts.tsx';
import type { CallFn, Json, Rec, Toast } from '../../../shared/types.ts';

/** The packages of a bundle. Every package is here by default; the switch hides it in THIS bundle only.
 *  Price fields: the store price in this bundle and, only when resellers exist, the cooperation price they pay.
 *  An empty field = the product's own price. These prices are the same for every reseller (no per-store prices). */
export function BundlePackages({
  group,
  products,
  hasResellers,
  call,
  toast,
  onChanged,
}: {
  group?: Json;
  products?: Json;
  hasResellers?: Json;
  call: CallFn;
  toast: Toast;
  onChanged?: Json;
}) {
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
    (r: Json) =>
      draft[r.product_id] && (draft[r.product_id].main !== undefined || draft[r.product_id].res !== undefined),
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
