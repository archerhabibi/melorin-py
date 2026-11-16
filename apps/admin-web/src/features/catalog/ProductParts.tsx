import { Clock, Infinity as Inf, Pencil, Smartphone, Tag, Zap } from 'lucide-react';
import type { Json } from '../../shared/types.ts';
import { NumInput, Switch, DeleteButton, num, tint } from '../../shared/kit.tsx';
import { CUR, price, dur, gb, Route } from './productsShared.tsx';
import { Switches } from './ProductSwitches';

export function ProductCard({
  p,
  idx,
  busy,
  hasResellers,
  onEdit,
  onToggle,
  onToggleReseller,
  onDelete,
}: {
  p?: Json;
  idx?: Json;
  busy?: Json;
  hasResellers?: Json;
  onEdit?: Json;
  onToggle?: Json;
  onToggleReseller?: Json;
  onDelete?: Json;
}) {
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
        {(
          [
            [Clock, dur(p.duration_days)],
            [p.traffic_gb ? Zap : Inf, gb(p.traffic_gb)],
            [Smartphone, p.max_devices ? `${num(p.max_devices)} دستگاه` : 'دستگاه نامحدود'],
          ] as [Json, Json][]
        ).map(([I, t], i) => (
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
}: {
  rows?: Json;
  idx?: Json;
  busy?: Json;
  hasResellers?: Json;
  onEdit?: Json;
  onToggle?: Json;
  onToggleReseller?: Json;
  onDelete?: Json;
  quick?: Json;
  draft?: Json;
  setDraft?: Json;
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
            {rows.map((p: Json) => {
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
                          onChange={(v: Json) => setDraft((x: Json) => ({ ...x, [p.id]: { main_price: v } }))}
                        />
                      </div>
                    ) : (
                      <span className="font-semibold">{price(p.main_price, p.currency)}</span>
                    )}
                  </td>
                  <td className="min-w-[130px]">
                    {r.ok ? (
                      <span className="badge b-ok" title={(r.groups || []).map((x: Json) => x.name).join('، ')}>
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
                      onChange={(v: Json) => onToggle(p, v)}
                      label={`فعال‌سازی ${p.name}`}
                    />
                  </td>
                  {hasResellers && (
                    <td>
                      <Switch
                        checked={p.is_active && p.reseller_enabled !== false}
                        disabled={busy.has(p.id) || !p.is_active}
                        onChange={(v: Json) => onToggleReseller(p, v)}
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
