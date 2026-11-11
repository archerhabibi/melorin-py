import { AlertTriangle, Layers, ServerCog } from 'lucide-react';
import type { Json, Rec } from './types.ts';
import { num } from './kit.tsx'; // #4
import { infraHref } from './infra.tsx';

export const API = '/api/v1/admin/products';
export const CUR: Rec = { IRT: 'تومان', USD: 'دلار', USDT: 'تتر', XTR: 'ستاره' };
export const price = (n: Json, c: Json) => `${num(n)} ${CUR[c] || c}`;
export const dur = (d: Json) => (d % 30 === 0 && d >= 30 ? `${num(d / 30)} ماهه` : `${num(d)} روزه`);
export const gb = (n: Json) => (n ? `${num(n)} گیگ` : 'نامحدود');

// A product here is only the plan itself: specs + the store's own price. The cooperation price (what resellers pay),
// the per-bundle price and "hide in this bundle" live on the bundles screen. A package is sold in every bundle by default.
export const EMPTY = {
  code: '',
  name: '',
  description: '',
  category: '',
  duration_days: '30',
  unlimited_traffic: false,
  traffic_gb: '',
  unlimited_devices: true,
  max_devices: '',
  currency: 'IRT',
  main_price: '',
  is_active: true,
  reseller_enabled: true,
  is_test: false,
};
export const fromProduct = (p: Json) => ({
  code: p.code,
  name: p.name,
  description: p.description || '',
  category: p.category || '',
  duration_days: String(p.duration_days),
  unlimited_traffic: !p.traffic_gb,
  traffic_gb: p.traffic_gb ? String(p.traffic_gb) : '',
  unlimited_devices: !p.max_devices,
  max_devices: p.max_devices ? String(p.max_devices) : '',
  currency: p.currency,
  main_price: String(p.main_price),
  is_active: p.is_active,
  reseller_enabled: p.reseller_enabled !== false,
  is_test: !!p.is_test,
});
export const payload = (f: Json) => ({
  code: f.code.trim(),
  name: f.name.trim(),
  description: f.description.trim() || null,
  category: f.category.trim() || null,
  duration_days: +f.duration_days,
  traffic_gb: f.unlimited_traffic ? 0 : +f.traffic_gb,
  max_devices: f.unlimited_devices ? null : +f.max_devices,
  currency: f.currency,
  main_price: +f.main_price,
  is_test: f.is_test,
  reseller_enabled: f.reseller_enabled,
});
export function validate(f: Json) {
  const e: Rec = {};
  if (!/^[A-Za-z0-9_-]{2,50}$/.test(f.code.trim())) e.code = 'کد ۲ تا ۵۰ نویسه؛ فقط حروف انگلیسی، عدد، - و _';
  if (f.name.trim().length < 2) e.name = 'نام محصول را وارد کنید';
  if (!(+f.duration_days > 0)) e.duration_days = 'مدت باید حداقل ۱ روز باشد';
  if (!f.unlimited_traffic && !(+f.traffic_gb > 0)) e.traffic_gb = 'حجم را وارد کنید یا «نامحدود» را بزنید';
  if (!f.unlimited_devices && !(+f.max_devices > 0)) e.max_devices = 'تعداد دستگاه را وارد کنید';
  if (f.main_price === '') e.main_price = 'قیمت فروشگاه را وارد کنید';
  return e;
}

/** One line: in how many bundles the package is sold and whether a server can take it (or why not). */
export function Route({ p, idx }: { p?: Json; idx?: Json }) {
  const r = idx.reach(p),
    n = (r.groups || []).filter((g: Json) => g.is_enabled).length;
  if (!r.ok)
    return (
      <p className="flex items-start gap-1.5 text-[11px] font-bold leading-5 text-[var(--bd)]">
        <AlertTriangle size={12} className="mt-0.5 shrink-0" />
        {r.issue}
      </p>
    );
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-[var(--mu)]">
      <Layers size={12} />
      در {num(n)} بسته فروش
      <span>·</span>
      <a
        href={infraHref('panels', { product: p.code })}
        className="inline-flex items-center gap-1 font-bold hover:text-[var(--ac)]"
      >
        <ServerCog size={12} />
        {num(r.live.length)} سرور آماده · {num(r.free)} ظرفیت آزاد
      </a>
    </div>
  );
}
