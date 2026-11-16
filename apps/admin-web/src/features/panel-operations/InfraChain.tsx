import { useMemo } from 'react';
import { ArrowLeft, Sparkles } from 'lucide-react';
import { Ring, num, tint } from '../../shared/kit.tsx';
import type { Json, Rec } from '../../shared/types.ts';
import { CHAIN, infraHref, health, serverState, free, usage } from './infra.tsx';

/* ---------- guided next step ---------- */
/** The first thing that still blocks selling, as { text, cta, href } — or null when everything is ready. */
export function nextStep(infra: Json) {
  if (infra.loading || infra.failed) return null;
  const panels = infra.panels.rows || [],
    products = infra.products.rows || [],
    idx = infra.idx;
  if (!panels.length)
    return {
      text: 'هنوز پنلی وصل نشده. اولین پنل را اضافه کنید؛ سرور (ظرفیت) همان‌جا ساخته می‌شود.',
      cta: 'افزودن پنل',
      href: infraHref('panels', { add: 1 }),
    };
  const noServer = panels.find((p: Json) => p.is_enabled && !(idx.serversByPanel.get(p.id) || []).length);
  if (noServer)
    return {
      text: `پنل «${noServer.name}» سرور ندارد؛ تا ظرفیت تعریف نشود اکانتی روی آن ساخته نمی‌شود.`,
      cta: 'افزودن سرور',
      href: infraHref('panels', { id: noServer.id, add: 'server' }),
    };
  const sick = panels.find((p: Json) => p.is_enabled && health(p) !== 'healthy');
  if (sick)
    return {
      text: `سلامت پنل «${sick.name}» ${health(sick) === 'unhealthy' ? 'ناسالم است' : 'هنوز بررسی نشده'}؛ تا سالم نشود فروشی روی آن انجام نمی‌شود.`,
      cta: 'بررسی پنل',
      href: infraHref('panels', { id: sick.id }),
    };
  if (!products.length)
    return {
      text: 'پنل‌ها آماده‌اند. حالا اولین محصول را بسازید؛ همان‌جا می‌توانید بسته فروش هم بسازید.',
      cta: 'افزودن محصول',
      href: infraHref('products', { add: 1 }),
    };
  const broken = products.filter((p: Json) => p.is_active && !idx.reach(p).ok);
  if (broken.length)
    return {
      text: `${num(broken.length)} محصول فعال مسیر تخصیص ندارد و خریدش با خطا روبه‌رو می‌شود.`,
      cta: 'مشاهده',
      href: infraHref('products', { filter: 'broken' }),
    };
  return null;
}

/* ---------- UI: the chain header shown on top of all three screens ---------- */
export function issuesOf(infra: Json) {
  const { idx } = infra;
  const panels = infra.panels.rows || [],
    servers = infra.servers.rows || [],
    groups = infra.groups.rows || [],
    products = infra.products.rows || [];
  const full = servers.filter((s: Json) => s.is_enabled && usage(s) >= 1).length;
  return {
    panels: {
      n: panels.length,
      bad: panels.filter((p: Json) => p.is_enabled && health(p) !== 'healthy').length,
      badText: 'ناسالم/بررسی‌نشده',
      empty: panels.filter((p: Json) => !(idx.serversByPanel.get(p.id) || []).length).length + full,
      emptyText: 'بدون سرور یا ظرفیت پر',
    },
    groups: {
      n: groups.length,
      bad: groups.filter((g: Json) => g.is_enabled && !(g.panels || []).length).length,
      badText: 'بدون پنل',
      empty: groups.filter((g: Json) => !(idx.productsByGroup.get(g.id) || []).length).length,
      emptyText: 'بدون پکیج',
    },
    products: {
      n: products.length,
      bad: products.filter((p: Json) => p.is_active && !idx.reach(p).ok).length,
      badText: 'بدون مسیر تخصیص',
      empty: 0,
      emptyText: '',
    },
  };
}

/** Sellable-readiness of the whole chain: share of active products the core could allocate right now. */
export function readiness(infra: Json) {
  const { idx } = infra;
  const prods = (infra.products.rows || []).filter((p: Json) => p.is_active);
  const ok = prods.filter((p: Json) => idx.reach(p).ok).length;
  let freeSlots = 0;
  (infra.servers.rows || []).forEach((s: Json) => {
    if (serverState(s, idx.panelById.get(s.panel_id)).ok) freeSlots += free(s);
  });
  return { total: prods.length, ok, freeSlots, value: prods.length ? ok / prods.length : 0 };
}

export function InfraChain({ current, infra }: { current?: Json; infra?: Json }) {
  const st = useMemo(
    () => issuesOf(infra),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
    [infra.panels.rows, infra.servers.rows, infra.groups.rows, infra.products.rows],
  );
  const next = useMemo(
    () => nextStep(infra),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
    [infra.panels.rows, infra.servers.rows, infra.groups.rows, infra.products.rows, infra.loading, infra.failed],
  );
  const rd = useMemo(
    () => readiness(infra),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
    [infra.panels.rows, infra.servers.rows, infra.groups.rows, infra.products.rows],
  );
  const loading = infra.loading;
  const rtone = !rd.total ? 'mu' : rd.value >= 1 ? 'ok' : rd.value >= 0.5 ? 'wn' : 'bd';
  return (
    <div className="space-y-3">
      <nav aria-label="زنجیره زیرساخت" className="card rise pipe gap-2 p-2.5 lg:gap-4">
        <div
          className="flex items-center gap-3.5 rounded-xl bg-[var(--sf2)] px-4 py-3 lg:min-w-[15rem]"
          title="سهم محصولات فعالی که هسته همین الان می‌تواند برایشان اکانت بسازد"
        >
          <Ring
            value={loading ? 0 : rd.value}
            size={58}
            stroke={6}
            tone={rtone}
            label={loading ? undefined : `آمادگی فروش ${Math.round(rd.value * 100)} درصد`}
          >
            {loading ? (
              <span className="skel h-4 w-7" />
            ) : (
              <b className="num text-[13px] font-extrabold">{num(Math.round(rd.value * 100))}٪</b>
            )}
          </Ring>
          <div className="min-w-0">
            <div className="text-[11px] font-bold text-[var(--mu)]">آمادگی فروش</div>
            <div className="mt-0.5 text-sm font-extrabold">
              {loading
                ? '…'
                : !rd.total
                  ? 'محصول فعالی نیست'
                  : rd.ok === rd.total
                    ? 'همه‌چیز آماده است'
                    : `${num(rd.ok)} از ${num(rd.total)} محصول قابل فروش`}
            </div>
            {!loading && (
              <div className="mt-0.5 text-[11px] text-[var(--mu)]">
                <b className="num text-[var(--tx)]">{num(rd.freeSlots)}</b> ظرفیت آزاد
              </div>
            )}
          </div>
        </div>
        <ol className="pipe-steps">
          {CHAIN.map((c, i) => {
            const s = (st as Rec)[c.key],
              on = c.key === current;
            const warn = s.bad > 0;
            return (
              <li key={c.key} className="flex min-w-0 items-stretch">
                <a href={infraHref(c.slug)} aria-current={on ? 'page' : undefined} className="step min-w-0 flex-1">
                  <span className="tile relative h-11 w-11" style={tint(c.tone)}>
                    <c.Icon size={20} />
                    <span className="absolute -right-1.5 -top-1.5 grid h-[18px] w-[18px] place-items-center rounded-full bg-[var(--nav)] text-[10px] font-extrabold text-white ring-2 ring-[var(--sf)]">
                      {num(i + 1)}
                    </span>
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline gap-2">
                      <b className="truncate text-sm">{c.title}</b>
                      {loading ? (
                        <span className="skel inline-block h-4 w-6" />
                      ) : (
                        <span className="num text-lg font-extrabold leading-none">{num(s.n)}</span>
                      )}
                    </span>
                    <span className="mt-1 block truncate text-[11px] text-[var(--mu)]">
                      {!loading && warn ? (
                        <span className="font-bold text-[var(--bd)]">
                          {num(s.bad)} {s.badText}
                        </span>
                      ) : !loading && s.empty > 0 ? (
                        <span className="text-[var(--wn)]">
                          {num(s.empty)} {s.emptyText}
                        </span>
                      ) : (
                        c.hint
                      )}
                    </span>
                  </span>
                </a>
                {i < CHAIN.length - 1 && (
                  <span aria-hidden="true" className="link-arrow hidden px-0.5 lg:grid">
                    <ArrowLeft size={16} />
                  </span>
                )}
              </li>
            );
          })}
        </ol>
      </nav>
      {next && (
        <p
          className="flex flex-wrap items-center gap-3 rounded-xl border border-[color-mix(in_srgb,var(--in)_30%,transparent)] px-4 py-2.5 text-xs font-bold leading-6"
          style={tint('in')}
        >
          <Sparkles size={15} className="shrink-0" />
          <span className="min-w-0 flex-1">قدم بعدی: {next.text}</span>
          <a className="btn !py-1.5 !text-xs" href={next.href}>
            {next.cta}
          </a>
        </p>
      )}
    </div>
  );
}
