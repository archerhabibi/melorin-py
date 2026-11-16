import type { ReactNode } from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Boxes, Layers, PanelTop } from 'lucide-react';
import { useCall } from '../../api/api.ts';
import { tint, useRows } from '../../shared/kit.tsx';
import type { CallFn, Json, Rec } from '../../shared/types.ts';

/* ---------- chain definition ---------- */
export const CHAIN = [
  {
    key: 'panels',
    slug: 'panels',
    title: 'پنل‌ها و سرورها',
    one: 'پنل',
    Icon: PanelTop,
    tone: 'in',
    hint: 'اتصال به سنایی / پاسارگارد + ظرفیت',
  },
  {
    key: 'groups',
    slug: 'bundles',
    title: 'بسته‌های فروش',
    one: 'بسته',
    Icon: Layers,
    tone: 'wn',
    hint: 'مسیر فروش: پنل‌ها + پکیج‌ها و قیمت (الزامی)',
  },
  {
    key: 'products',
    slug: 'products',
    title: 'محصولات VPN',
    one: 'محصول',
    Icon: Boxes,
    tone: 'mu',
    hint: 'پلن پایه؛ در بسته‌ها پکیج می‌شود',
  },
];

/* ---------- hash routing helpers (#/panels?id=<id>&add=server) ---------- */
const readParams = () => new URLSearchParams(window.location.hash.split('?')[1] || '');
export function useHashParams() {
  const [p, setP] = useState(readParams);
  useEffect(() => {
    const f = () => setP(readParams());
    window.addEventListener('hashchange', f);
    return () => window.removeEventListener('hashchange', f);
  }, []);
  return p;
}
export const infraHref = (slug: Json, params: Rec = {}) => {
  const qs = new URLSearchParams(
    Object.entries(params as Rec)
      .filter(([, v]) => v !== undefined && v !== null && v !== '')
      .map(([k, v]): [string, string] => [k, String(v)]),
  ).toString();
  return `#/${slug}${qs ? `?${qs}` : ''}`;
};
/** Drop one-shot params (e.g. add=1) without adding a history entry. */
export const clearParam = (name: Json) => {
  const [path, q = ''] = window.location.hash.split('?');
  const p = new URLSearchParams(q);
  p.delete(name);
  const s = p.toString();
  window.history.replaceState(
    null,
    '',
    `${window.location.pathname}${window.location.search}${path}${s ? `?${s}` : ''}`,
  );
};

/* ---------- semantics ---------- */
export const KIND = { sanaei: 'سنایی (3x-ui)', pasarguard: 'پاسارگارد', mock: 'Mock' };
export const health = (p: Json) =>
  ['healthy', 'degraded', 'unhealthy'].includes(p?.health_status) ? p.health_status : 'unknown';
export const HCOLOR: Rec = {
  healthy: 'var(--ok)',
  degraded: 'var(--wn)',
  unhealthy: 'var(--bd)',
  unknown: 'var(--mu)',
};
export const HLABEL: Rec = { healthy: 'سالم', degraded: 'مختل (نود خراب)', unhealthy: 'ناسالم', unknown: 'بررسی‌نشده' };

export function Dot({ s, ping }: { s?: Json; ping?: Json }) {
  const c = HCOLOR[s] || HCOLOR.unknown;
  return (
    <span className="relative inline-flex h-2.5 w-2.5 shrink-0" title={HLABEL[s]}>
      <span
        className={`absolute inset-0 rounded-full ${ping && s === 'healthy' ? 'pv-ping' : ''}`}
        style={{ background: c }}
      />
      <span className="relative h-2.5 w-2.5 rounded-full" style={{ background: c }} />
    </span>
  );
}

/** Why a server can / cannot receive a NEW account right now (mirrors allocation._reject_reason, capacity aside). */
export function serverState(s: Json, panel: Json) {
  if (!s.is_enabled) return { key: 'off', tone: 'mu', label: 'سرور غیرفعال', ok: false };
  if (!panel) return { key: 'nopanel', tone: 'bd', label: 'پنل حذف‌شده', ok: false };
  if (!panel.is_enabled) return { key: 'panel_off', tone: 'wn', label: 'پنل غیرفعال', ok: false };
  const h = health(panel);
  if (h === 'unhealthy') return { key: 'panel_bad', tone: 'bd', label: 'پنل ناسالم', ok: false };
  if (h === 'unknown') return { key: 'panel_unknown', tone: 'wn', label: 'سلامت پنل بررسی نشده', ok: false };
  if (s.capacity && s.active_accounts >= s.capacity) return { key: 'full', tone: 'bd', label: 'ظرفیت پر', ok: false };
  return { key: 'ready', tone: 'ok', label: 'آماده فروش', ok: true };
}
export const free = (s: Json) => Math.max(0, (s.capacity || 0) - (s.active_accounts || 0));
export const usage = (s: Json) => (s.capacity ? s.active_accounts / s.capacity : 0);

/* ---------- derived index ---------- */
export function buildIndex(panels: Json, servers: Json, groups: Json, products: Json) {
  const panelById = new Map(panels.map((p: Json) => [p.id, p]));
  const groupById = new Map(groups.map((g: Json) => [g.id, g]));
  const serversByPanel = new Map(),
    groupsByPanel = new Map(),
    productsByGroup = new Map();
  servers.forEach((s: Json) => {
    (serversByPanel.get(s.panel_id) || serversByPanel.set(s.panel_id, []).get(s.panel_id)).push(s);
  });
  groups.forEach((g: Json) =>
    (g.panels || []).forEach((m: Json) => {
      const l = groupsByPanel.get(m.panel_id) || groupsByPanel.set(m.panel_id, []).get(m.panel_id);
      if (!l.includes(g)) l.push(g);
    }),
  );
  const productById = new Map(products.map((p: Json) => [p.id, p]));
  const groupsByProduct = new Map();
  groups.forEach((g: Json) =>
    (g.product_ids || []).forEach((pid: Json) => {
      const p = productById.get(pid);
      if (!p) return;
      (productsByGroup.get(g.id) || productsByGroup.set(g.id, []).get(g.id)).push(p);
      (groupsByProduct.get(pid) || groupsByProduct.set(pid, []).get(pid)).push(g);
    }),
  );

  const panelStat = (id: Json) => {
    const l = serversByPanel.get(id) || [];
    return {
      n: l.length,
      enabled: l.filter((s: Json) => s.is_enabled).length,
      capacity: l.reduce((a: Json, s: Json) => a + (s.capacity || 0), 0),
      active: l.reduce((a: Json, s: Json) => a + (s.active_accounts || 0), 0),
    };
  };
  const groupStat = (g: Json) => {
    const ids = (g.panels || []).map((m: Json) => m.panel_id);
    const l = ids.flatMap((id: Json) => serversByPanel.get(id) || []);
    const live = l.filter((s: Json) => serverState(s, panelById.get(s.panel_id)).ok);
    return {
      panels: ids.length,
      servers: l.length,
      live: live.length,
      capacity: l.reduce((a: Json, s: Json) => a + (s.capacity || 0), 0),
      active: l.reduce((a: Json, s: Json) => a + (s.active_accounts || 0), 0),
      free: live.reduce((a: Json, s: Json) => a + free(s), 0),
    };
  };
  /** What the core could actually allocate for a product: bundles listing it → enabled members → live servers. */
  const reach = (p: Json) => {
    let gs = groupsByProduct.get(p.id) || [];
    if (!gs.length && p.default_bundle_id && groupById.get(p.default_bundle_id))
      gs = [groupById.get(p.default_bundle_id)];
    let issue = '';
    const panelIds = new Set();
    if (!gs.length) issue = 'در هیچ بسته فروشی نیست؛ قابل فروش نیست';
    else {
      const on = gs.filter((g: Json) => g.is_enabled);
      if (!on.length) issue = 'همه بسته‌های این محصول غیرفعال‌اند';
      else
        on.forEach((g: Json) =>
          (g.panels || []).filter((m: Json) => m.is_enabled).forEach((m: Json) => panelIds.add(m.panel_id)),
        );
      if (!issue && !panelIds.size) issue = 'بسته‌های این محصول پنل فعالی ندارند';
    }
    const cands = issue ? [] : servers.filter((s: Json) => panelIds.has(s.panel_id));
    const live = cands.filter((s: Json) => serverState(s, panelById.get(s.panel_id)).ok);
    if (!issue && !cands.length) issue = 'هیچ سروری روی پنل‌های این بسته‌ها تعریف نشده است';
    else if (!issue && !live.length) issue = 'سرورهای سازگار همه غیرفعال، پر یا روی پنل ناسالم‌اند';
    return {
      group: gs[0] || null,
      groups: gs,
      direct: false,
      servers: cands,
      live,
      free: live.reduce((a: Json, s: Json) => a + free(s), 0),
      issue,
      ok: !issue,
    };
  };
  /** Products that can end up on a server of `panelId` whose allow-list is `codes` (null/[] = all). */
  const productsForPanel = (panelId: Json, codes: Json) =>
    products.filter((p: Json) => {
      if (!p.is_active) return false;
      if (codes?.length && !codes.includes(p.code)) return false;
      return (groupsByProduct.get(p.id) || []).some(
        (g: Json) => g.is_enabled && (g.panels || []).some((m: Json) => m.is_enabled && m.panel_id === panelId),
      );
    });
  return {
    panelById,
    groupById,
    serversByPanel,
    groupsByPanel,
    productsByGroup,
    panelStat,
    groupStat,
    reach,
    productsForPanel,
  };
}

/** Load only the endpoints a screen needs. Pass `{ needs: ["panels","groups"] }` for lazy-loading (#3).
 * Default (no arg) fetches all four — backward-compatible. */
export function useInfra(api: Json, { needs = ['panels', 'servers', 'groups', 'products'] } = {}) {
  const has = (k: Json) => needs.includes(k);
  const call = useCall(api);
  const panels = useRows(call, '/api/v1/admin/panels', { skip: !has('panels') });
  const servers = useRows(call, '/api/v1/admin/servers', { skip: !has('servers') });
  const groups = useRows(call, '/api/v1/admin/bundles', { skip: !has('groups') });
  const products = useRows(call, '/api/v1/admin/products', { skip: !has('products') });
  // Track loading/failed only for requested endpoints (skip initialises rows to [])
  const needed = [panels, servers, groups, products].filter((_, i) =>
    has(['panels', 'servers', 'groups', 'products'][i]),
  );
  const idx = useMemo(
    () => buildIndex(panels.rows || [], servers.rows || [], groups.rows || [], products.rows || []),
    [panels.rows, servers.rows, groups.rows, products.rows],
  );
  const _loaderRef = useRef<Json>(null);
  _loaderRef.current = { panels: panels.load, servers: servers.load, groups: groups.load, products: products.load };
  const reload = useCallback(
    () => Promise.all(needs.map((k) => _loaderRef.current[k]())),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
    [], // stable; ref updated each render above
  );
  return {
    call,
    panels,
    servers,
    groups,
    products,
    idx,
    reload,
    loading: needed.some((l) => l.rows === null),
    failed: needed.some((l) => l.failed),
  };
}

/* ---------- UI: links ---------- */
/** Small clickable chip that jumps to a related item in another screen. */
export function RelChip({
  to,
  params,
  tone = 'mu',
  Icon,
  children,
  title,
  dim,
}: {
  to?: Json;
  params?: Json;
  tone?: Json;
  Icon?: Json;
  children?: ReactNode;
  title?: Json;
  dim?: Json;
}) {
  return (
    <a
      href={infraHref(to, params)}
      title={title}
      className={`inline-flex max-w-full items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] font-bold transition hover:ring-1 hover:ring-[var(--ac)] ${dim ? 'opacity-60' : ''}`}
      style={tint(tone)}
    >
      {Icon && <Icon size={12} className="shrink-0" />}
      <span className="truncate">{children}</span>
    </a>
  );
}

export const Warn = ({ children, tone = 'wn' }: { children?: ReactNode; tone?: Json }) => (
  <p className="flex items-start gap-2 rounded-lg px-3 py-2 text-[11px] font-bold leading-5" style={tint(tone)}>
    <AlertTriangle size={13} className="mt-0.5 shrink-0" />
    {children}
  </p>
);

/* ---------- group membership (one API, used by the panel screen AND the group screen) ---------- */
/** Panel ids of a group in priority order. */
export const memberIds = (g: Json) =>
  (g?.panels || [])
    .slice()
    .sort((a: Json, b: Json) => a.sort - b.sort)
    .map((m: Json) => m.panel_id);
/** PATCH the member list of a group. Returns "" on success or an error text. */
export async function saveGroupPanels(call: CallFn, group: Json, panelIds: Json) {
  const r = await call(`/api/v1/admin/bundles/${group.id}`, {
    method: 'PATCH',
    body: JSON.stringify({ panel_ids: panelIds }),
  });
  if (r.ok) return '';
  try {
    const d = await r.json();
    return d?.error?.message || (typeof d?.detail === 'string' ? d.detail : '') || 'تغییر پنل‌های بسته ناموفق بود';
  } catch {
    return 'تغییر پنل‌های بسته ناموفق بود';
  }
}
