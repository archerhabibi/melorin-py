import { Layers, Pencil } from 'lucide-react';
import { Bar, Switch, DeleteButton, capTone, num, tint } from '../kit.tsx';
import { Dot, Warn, health as hs, infraHref } from '../infra.tsx';
import type { Json, Rec } from '../types.ts';

export const API = '/api/v1/admin/bundles';
export const MODES = {
  automatic: [
    'خودکار',
    'سیستم برای هر فروش جدید یکی از مقصدهای (گروه/اینباند) پنل‌های بسته را با روش توزیع زیر انتخاب می‌کند؛ مشتری چیزی نمی‌بیند. تمدید همیشه روی مقصد قبلی می‌ماند.',
  ],
  manual: ['انتخاب مشتری', 'مشتری هنگام خرید یکی از پنل‌های بسته را با «نام نمایشی» که شما می‌دهید انتخاب می‌کند.'],
};

function Quota({ sold, limit }: { sold?: Json; limit?: Json }) {
  const pct = limit ? Math.min(100, Math.round((sold / limit) * 100)) : 0;
  const full = limit && sold >= limit,
    warn = limit && pct >= 80;
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between text-[11px]">
        <span className="text-[var(--mu)]">سقف فروش بسته</span>
        <b className={`num ${full ? 'text-[var(--bd)]' : ''}`}>
          {num(sold)} / {limit ? num(limit) : 'نامحدود'}
          {full ? ' · پر شده' : ''}
        </b>
      </div>
      {limit ? (
        <Bar value={pct / 100} tone={full ? 'bd' : warn ? 'wn' : 'ok'} label="سهمیه فروش" />
      ) : (
        <div className="bar">
          <i
            style={{
              width: '100%',
              background: 'repeating-linear-gradient(135deg,var(--mb) 0 6px,transparent 6px 12px)',
            }}
          />
        </div>
      )}
    </div>
  );
}

/** Why an enabled group cannot sell right now, or "" when it can. */
export const groupIssue = (g: Json, stat: Json) =>
  !g.is_enabled ? '' : !(g.panels || []).length ? 'پنلی ندارد' : !stat.live ? 'هیچ سرور آماده‌ای ندارد' : '';

const fromPrice = (products: Json) => {
  const cur = [...new Set(products.map((p: Json) => p.currency))];
  if (cur.length !== 1 || !products.length) return null;
  return `${num(Math.min(...products.map((p: Json) => p.main_price)))} ${({ IRT: 'تومان', USD: 'دلار', USDT: 'تتر', XTR: 'ستاره' } as Rec)[cur[0] as string] || cur[0]}`;
};

/** Two switches: the main store, and resellers. Turning the main store off turns resellers off too. */
function Switches({
  g,
  busy,
  hasResellers,
  onToggle,
  onToggleReseller,
}: {
  g?: Json;
  busy?: Json;
  hasResellers?: Json;
  onToggle?: Json;
  onToggleReseller?: Json;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <label className="flex cursor-pointer items-center gap-2 text-xs font-bold">
        <Switch
          checked={g.is_enabled}
          disabled={busy}
          onChange={(v: Json) => onToggle(g, v)}
          label={`فعال‌سازی ${g.name} در فروشگاه اصلی`}
        />
        {hasResellers ? 'فروشگاه اصلی' : g.is_enabled ? 'فعال' : 'غیرفعال'}
      </label>
      {hasResellers && (
        <label
          className={`flex cursor-pointer items-center gap-2 text-xs font-bold ${g.is_enabled ? '' : 'opacity-50'}`}
          title={g.is_enabled ? '' : 'ابتدا در فروشگاه اصلی فعال کنید'}
        >
          <Switch
            checked={g.is_enabled && g.reseller_enabled}
            disabled={busy || !g.is_enabled}
            onChange={(v: Json) => onToggleReseller(g, v)}
            label={`فعال‌سازی ${g.name} برای نمایندگان`}
          />
          نمایندگان
        </label>
      )}
    </div>
  );
}

export function GroupCard({
  g,
  stat,
  products,
  busy,
  hasResellers,
  onEdit,
  onToggle,
  onToggleReseller,
  onDelete,
}: {
  g?: Json;
  stat?: Json;
  products?: Json;
  busy?: Json;
  hasResellers?: Json;
  onEdit?: Json;
  onToggle?: Json;
  onToggleReseller?: Json;
  onDelete?: Json;
}) {
  const ms = g.panels || [],
    dim = g.is_enabled ? '' : 'opacity-55',
    issue = groupIssue(g, stat);
  const state = !g.is_enabled ? 'off' : issue ? 'bd' : 'ok';
  const active = products.filter((p: Json) => p.is_active).length;
  const from = fromPrice(products);
  return (
    <article
      className={`card card-i rise stripe flex flex-col gap-4 p-5 ${state === 'off' ? 'off' : ''}`}
      style={{ '--stripe': state === 'ok' ? 'var(--ok)' : state === 'bd' ? 'var(--bd)' : 'var(--ln)' }}
    >
      <div className={`flex items-start gap-3 ${dim}`}>
        <span className="tile h-12 w-12" style={tint('wn')}>
          <Layers size={22} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-base font-extrabold" title={g.name}>
            {g.name}
          </h3>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {g.kind_label && <span className="badge b-in">{g.kind_label}</span>}
            {g.selection_mode === 'manual' && (
              <span className="badge b-mu" title={MODES.manual[1]}>
                انتخاب پنل با مشتری
              </span>
            )}
          </div>
        </div>
        {state === 'bd' && <span className="badge b-bd">نمی‌فروشد</span>}
      </div>
      <div className={`grid grid-cols-3 gap-2 text-center ${dim}`}>
        <a
          className="rounded-xl bg-[var(--sf2)] p-2.5 hover:ring-1 hover:ring-[var(--ac)]"
          href={infraHref('panels', { group: g.id })}
          title="پنل‌های این بسته"
        >
          <div className="num text-lg font-extrabold">{num(ms.length)}</div>
          <div className="text-[11px] text-[var(--mu)]">پنل</div>
        </a>
        <div className="rounded-xl bg-[var(--sf2)] p-2.5">
          <div className="num text-lg font-extrabold">{num(active)}</div>
          <div className="text-[11px] text-[var(--mu)]">پکیج فعال{from ? ` · از ${from}` : ''}</div>
        </div>
        <div
          className="rounded-xl bg-[var(--sf2)] p-2.5"
          title={stat.servers ? `${num(stat.live)} سرور آماده از ${num(stat.servers)}` : 'سروری نیست'}
        >
          <div className={`num text-lg font-extrabold ${stat.free ? '' : 'text-[var(--wn)]'}`}>{num(stat.free)}</div>
          <div className="text-[11px] text-[var(--mu)]">ظرفیت آزاد</div>
        </div>
      </div>
      {g.sales_limit ? (
        <div className={dim}>
          <Quota sold={g.sold_count || 0} limit={g.sales_limit} />
        </div>
      ) : null}
      {issue && <Warn tone="bd">{issue}؛ تا رفع مشکل، پکیج‌های این بسته فروخته نمی‌شوند.</Warn>}
      <div className="mt-auto flex items-center justify-between gap-2 border-t border-[var(--ln)] pt-3">
        <Switches
          g={g}
          busy={busy}
          hasResellers={hasResellers}
          onToggle={onToggle}
          onToggleReseller={onToggleReseller}
        />
        <div className="flex items-center gap-1.5">
          <DeleteButton compact label={`حذف ${g.name}`} busy={busy} onClick={() => onDelete(g)} />
          <button className="btn btn-g" onClick={() => onEdit(g)}>
            <Pencil size={13} />
            ویرایش
          </button>
        </div>
      </div>
    </article>
  );
}

export function GroupTable({
  rows,
  panelById,
  idx,
  busy,
  hasResellers,
  onEdit,
  onToggle,
  onToggleReseller,
  onDelete,
}: {
  rows?: Json;
  panelById?: Json;
  idx?: Json;
  busy?: Json;
  hasResellers?: Json;
  onEdit?: Json;
  onToggle?: Json;
  onToggleReseller?: Json;
  onDelete?: Json;
}) {
  return (
    <section className="card rise overflow-hidden">
      <div className="overflow-auto">
        <table className="tbl2 min-w-[760px]">
          <thead>
            <tr>
              {[
                'بسته',
                'پنل‌ها',
                'سرور آماده',
                'ظرفیت آزاد',
                'پکیج‌ها',
                'فروش / سقف',
                'فروشگاه اصلی',
                ...(hasResellers ? ['نمایندگان'] : []),
                '',
              ].map((h, i) => (
                <th key={i}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((g: Json) => {
              const st = idx.groupStat(g),
                ps = idx.productsByGroup.get(g.id) || [],
                issue = groupIssue(g, st),
                u = st.capacity ? st.active / st.capacity : 0;
              return (
                <tr key={g.id} className={g.is_enabled ? '' : 'opacity-60'}>
                  <td>
                    <div className="flex items-center gap-2.5">
                      <span className="tile h-9 w-9" style={tint('wn')}>
                        <Layers size={16} />
                      </span>
                      <div className="min-w-0">
                        <div className="font-bold">{g.name}</div>
                        {issue ? (
                          <div className="text-[11px] font-bold text-[var(--bd)]">{issue}</div>
                        ) : (
                          g.kind_label && <div className="text-[11px] text-[var(--mu)]">{g.kind_label}</div>
                        )}
                      </div>
                    </div>
                  </td>
                  <td>
                    <div className="flex items-center gap-1">
                      {(g.panels || []).slice(0, 5).map((m: Json) => (
                        <Dot key={m.id} s={hs(panelById[m.panel_id])} />
                      ))}
                      <span className="num mr-1 text-xs text-[var(--mu)]">{num((g.panels || []).length)}</span>
                    </div>
                  </td>
                  <td className="num">
                    {num(st.live)} <span className="text-[var(--mu)]">/ {num(st.servers)}</span>
                  </td>
                  <td>
                    <div className="flex items-center gap-2">
                      <span className="num w-12 font-bold">{num(st.free)}</span>
                      <div className="w-20">
                        <Bar value={u} tone={capTone(u)} label="ظرفیت" />
                      </div>
                    </div>
                  </td>
                  <td className="num">{num(ps.filter((p: Json) => p.is_active).length)}</td>
                  <td className="num">
                    {num(g.sold_count || 0)}{' '}
                    <span className="text-[var(--mu)]">/ {g.sales_limit ? num(g.sales_limit) : '∞'}</span>
                  </td>
                  <td>
                    <Switch
                      checked={g.is_enabled}
                      disabled={busy.has(g.id)}
                      onChange={(v: Json) => onToggle(g, v)}
                      label={`فعال‌سازی ${g.name}`}
                    />
                  </td>
                  {hasResellers && (
                    <td>
                      <Switch
                        checked={g.is_enabled && g.reseller_enabled}
                        disabled={busy.has(g.id) || !g.is_enabled}
                        onChange={(v: Json) => onToggleReseller(g, v)}
                        label={`فعال‌سازی ${g.name} برای نمایندگان`}
                      />
                    </td>
                  )}
                  <td>
                    <div className="flex items-center justify-end gap-2">
                      <button className="btn btn-g" onClick={() => onEdit(g)}>
                        <Pencil size={13} />
                        ویرایش
                      </button>
                      <DeleteButton compact label={`حذف ${g.name}`} busy={busy.has(g.id)} onClick={() => onDelete(g)} />
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
