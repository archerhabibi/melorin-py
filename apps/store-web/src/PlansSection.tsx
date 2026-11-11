// Bundle / option pickers and the package grid (split out of App.jsx, T-R11).
import { ArrowLeft, Check, RefreshCw, Sparkles } from 'lucide-react';
import { fa } from './ui.tsx';
import { NAME_RE } from './landing.tsx';
import type { Json } from './types';

export function PlansSection({
  apiState,
  bundles,
  bundle,
  bundleId,
  catalog,
  catalogLoading,
  pkgLoading,
  manual,
  customName,
  panelId,
  setPanelId,
  accountName,
  setAccountName,
  active,
  pickBundle,
  choose,
  setSelectedQuote,
  setReloadKey,
}: {
  apiState?: Json;
  bundles?: Json;
  bundle?: Json;
  bundleId?: Json;
  catalog?: Json;
  catalogLoading?: Json;
  pkgLoading?: Json;
  manual?: Json;
  customName?: Json;
  panelId?: Json;
  setPanelId?: Json;
  accountName?: Json;
  setAccountName?: Json;
  active?: Json;
  pickBundle?: Json;
  choose?: Json;
  setSelectedQuote?: Json;
  setReloadKey?: Json;
}) {
  return (
    <section id="plans" className="bg-hero px-5 py-24">
      <div className="mx-auto max-w-6xl">
        <div className="flex flex-col justify-between gap-5 md:flex-row md:items-end">
          <div>
            <div className="text-sm font-extrabold text-[#f7c85c]">سرویس‌ها</div>
            <h2 className="mt-3 text-4xl font-black leading-tight">برای ریتم خودت انتخاب کن.</h2>
          </div>
          <p className="flex max-w-sm items-center gap-2 text-sm leading-7 text-white/60">
            <span className={`h-2 w-2 shrink-0 rounded-full ${bundles.length ? 'bg-[#86e0b8]' : 'bg-[#f79680]'}`} />
            {apiState} · قیمت نهایی فقط از Core می‌آید.
          </p>
        </div>
        {!catalogLoading && bundles.length > 1 && (
          <div className="mt-10">
            <div className="text-sm font-bold text-white/70">بسته فروش را انتخاب کن</div>
            <div className="mt-3 flex flex-wrap gap-3">
              {bundles.map((x: Json) => (
                <button
                  key={x.id}
                  onClick={() => pickBundle(x.id)}
                  aria-pressed={bundleId === x.id}
                  className={`flex items-center gap-3 rounded-2xl px-5 py-3 text-right text-sm font-extrabold transition ${bundleId === x.id ? 'bg-[#f7c85c] text-[#10233f]' : 'bg-white/[.07] text-white ring-1 ring-white/10 hover:bg-white/[.12]'}`}
                >
                  {x.name}
                  {x.kind_label && (
                    <span
                      className={`rounded-full px-2.5 py-0.5 text-[11px] font-bold ${bundleId === x.id ? 'bg-[#10233f] text-[#f7c85c]' : 'bg-white/10 text-[#86e0b8]'}`}
                    >
                      {x.kind_label}
                    </span>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}
        {!catalogLoading && bundle && manual && (
          <div className="mt-8">
            <div className="text-sm font-bold text-white/70">گزینه / لوکیشن را انتخاب کن</div>
            <div className="mt-3 flex flex-wrap gap-3">
              {(bundle.panels || []).map((x: Json) => (
                <button
                  key={x.id}
                  onClick={() => {
                    setPanelId(x.id);
                    setSelectedQuote(null);
                  }}
                  aria-pressed={panelId === x.id}
                  className={`rounded-2xl px-5 py-3 text-sm font-extrabold transition ${panelId === x.id ? 'bg-[#f7c85c] text-[#10233f]' : 'bg-white/[.07] text-white ring-1 ring-white/10 hover:bg-white/[.12]'}`}
                >
                  {x.label}
                </button>
              ))}
              {!(bundle.panels || []).length && (
                <span className="text-sm text-white/60">فعلاً گزینه‌ای در این بسته موجود نیست.</span>
              )}
            </div>
          </div>
        )}
        {!catalogLoading && bundle && customName && (!manual || panelId) && (
          <div className="mt-8 max-w-sm">
            <label className="block text-sm font-bold text-white/70">
              نام کاربری اکانت (اختیاری)
              <input
                dir="ltr"
                value={accountName}
                onChange={(e) => setAccountName(e.target.value.replace(/[^A-Za-z0-9_-]/g, ''))}
                maxLength={32}
                autoComplete="off"
                placeholder="my_name"
                className="input latin mt-2 text-left !text-ink"
              />
            </label>
            <p
              className={`mt-1.5 text-xs ${accountName && !NAME_RE.test(accountName) ? 'text-[#f79680]' : 'text-white/50'}`}
            >
              حداقل ۳ کاراکتر؛ فقط حروف انگلیسی، عدد، _ و - — اگر خالی بگذارید، نام به‌صورت خودکار ساخته می‌شود
            </p>
          </div>
        )}
        <div className="mt-12 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
          {catalogLoading || pkgLoading ? (
            Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="h-72 animate-pulse rounded-3xl bg-white/10" />
            ))
          ) : !bundles.length ? (
            <div className="rounded-3xl border border-white/15 bg-white/5 p-10 text-center text-white/75 md:col-span-2 lg:col-span-3">
              <p>سرویس‌ها موقتاً در دسترس نیست. لطفاً بعداً دوباره تلاش کنید.</p>
              <button
                onClick={() => setReloadKey((k: Json) => k + 1)}
                className="btn mt-5 bg-white/10 text-white hover:bg-white/20"
              >
                <RefreshCw size={16} />
                تلاش دوباره
              </button>
            </div>
          ) : !bundleId || (manual && !panelId) ? (
            <div className="rounded-3xl border border-white/15 bg-white/5 p-10 text-center text-white/75 md:col-span-2 lg:col-span-3">
              {!bundleId
                ? 'برای دیدن پکیج‌ها، یک بسته فروش را انتخاب کن.'
                : 'برای دیدن پکیج‌ها، یک گزینه را انتخاب کن.'}
            </div>
          ) : catalog.length ? (
            catalog.map((p: Json) => {
              const name = p.name || p.title || p.code || 'Melorin';
              const on = active === name;
              return (
                <button
                  key={String(p.product_id || p.id || name)}
                  onClick={() => choose(p)}
                  aria-pressed={on}
                  className={`group relative flex flex-col text-right rounded-3xl p-7 transition duration-300 hover:-translate-y-1.5 ${on ? 'bg-[#f7c85c] text-[#10233f] shadow-[0_24px_60px_-20px_#f7c85c88]' : 'bg-white/[.07] text-white ring-1 ring-white/10 hover:bg-white/[.12]'}`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-2xl font-black">{name}</span>
                    <span
                      className={`grid h-9 w-9 place-items-center rounded-full ${on ? 'bg-[#10233f] text-[#f7c85c]' : 'bg-white/10 text-[#86e0b8]'}`}
                    >
                      <Sparkles size={16} />
                    </span>
                  </div>
                  <ul className={`mt-7 space-y-3 text-sm ${on ? 'text-[#33466a]' : 'text-white/70'}`}>
                    <li className="flex items-center gap-2">
                      <Check size={15} className={on ? '' : 'text-[#86e0b8]'} />
                      {p.meta ||
                        `${p.duration_days ? fa(p.duration_days) : '؟'} روز · ${p.traffic_gb ? fa(p.traffic_gb) : '؟'} گیگابایت`}
                    </li>
                    <li className="flex items-center gap-2">
                      <Check size={15} className={on ? '' : 'text-[#86e0b8]'} />
                      تحویل خودکار پس از پرداخت
                    </li>
                    <li className="flex items-center gap-2">
                      <Check size={15} className={on ? '' : 'text-[#86e0b8]'} />
                      پرداخت از کیف پول
                    </li>
                  </ul>
                  <div className="mt-auto pt-9">
                    <div className="flex items-baseline gap-2">
                      <span className="text-4xl font-black tracking-tight">
                        {p.price ? new Intl.NumberFormat('fa-IR').format(p.price) : p.display_price || 'قیمت در Core'}
                      </span>
                      <span className="text-xs opacity-60">تومان</span>
                    </div>
                    <div
                      className={`mt-5 inline-flex items-center gap-2 text-sm font-extrabold ${on ? 'text-[#10233f]' : 'text-[#f7c85c]'}`}
                    >
                      {on ? (
                        <>
                          <Check size={16} />
                          انتخاب شده
                        </>
                      ) : (
                        <>
                          مشاهده پیش‌فاکتور <ArrowLeft size={16} className="transition group-hover:-translate-x-1" />
                        </>
                      )}
                    </div>
                  </div>
                </button>
              );
            })
          ) : (
            <div className="rounded-3xl border border-white/15 bg-white/5 p-10 text-center text-white/75 md:col-span-2 lg:col-span-3">
              این بسته فعلاً پکیجی برای فروش ندارد.
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
