// Shared model + building blocks for the VPN infrastructure screens.
//
// The four screens form ONE dependency chain that mirrors the allocation core (vpn/allocation.py):
//
//     پنل (Panel)  →  سرور (Server)  →  گروه پنل (Panel group)  →  محصول (Product)
//
// * a server belongs to exactly one panel (and holds capacity / product allow-list);
// * a panel group collects panels (selection + naming + sales limit);
// * a product points at a default panel group, and the core resolves product → group → panel → server.
//
// `useInfra` loads all four lists once per screen and derives the relations so every screen can show
// where an item sits in the chain, what it depends on, and what is broken for sale.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowLeft, Boxes, Layers, PanelTop, ServerCog } from "lucide-react";
import { authFetch } from "./api.js";
import { num, tint, useRows } from "./kit.jsx";

/* ---------- chain definition ---------- */
export const CHAIN = [
  { key: "panels", slug: "panels", title: "پنل‌ها", one: "پنل", Icon: PanelTop, tone: "in", hint: "اتصال به سنایی / پاسارگارد" },
  { key: "servers", slug: "servers", title: "سرورها", one: "سرور", Icon: ServerCog, tone: "ok", hint: "ظرفیت و محدوده فروش روی هر پنل" },
  { key: "groups", slug: "panel-groups", title: "گروه‌های پنل", one: "گروه", Icon: Layers, tone: "wn", hint: "مجموعه پنل‌ها + سیاست انتخاب" },
  { key: "products", slug: "products", title: "محصولات VPN", one: "محصول", Icon: Boxes, tone: "mu", hint: "پلن قابل فروش + گروه پیش‌فرض" },
];

/* ---------- hash routing helpers (#/servers?panel=<id>&add=1) ---------- */
const readParams = () => new URLSearchParams(window.location.hash.split("?")[1] || "");
export function useHashParams() {
  const [p, setP] = useState(readParams);
  useEffect(() => { const f = () => setP(readParams()); window.addEventListener("hashchange", f); return () => window.removeEventListener("hashchange", f); }, []);
  return p;
}
export const infraHref = (slug, params = {}) => {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")).toString();
  return `#/${slug}${qs ? `?${qs}` : ""}`;
};
/** Drop one-shot params (e.g. add=1) without adding a history entry. */
export const clearParam = (name) => {
  const [path, q = ""] = window.location.hash.split("?");
  const p = new URLSearchParams(q); p.delete(name);
  const s = p.toString();
  window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}${path}${s ? `?${s}` : ""}`);
};

/* ---------- semantics ---------- */
export const KIND = { sanaei: "سنایی (3x-ui)", pasarguard: "پاسارگارد", mock: "Mock" };
export const health = (p) => (p?.health_status === "healthy" || p?.health_status === "unhealthy" ? p.health_status : "unknown");
export const HCOLOR = { healthy: "var(--ok)", unhealthy: "var(--bd)", unknown: "var(--mu)" };
export const HLABEL = { healthy: "سالم", unhealthy: "ناسالم", unknown: "بررسی‌نشده" };

export function Dot({ s, ping }) {
  const c = HCOLOR[s] || HCOLOR.unknown;
  return <span className="relative inline-flex h-2.5 w-2.5 shrink-0" title={HLABEL[s]}><span className={`absolute inset-0 rounded-full ${ping && s === "healthy" ? "pv-ping" : ""}`} style={{ background: c }} /><span className="relative h-2.5 w-2.5 rounded-full" style={{ background: c }} /></span>;
}

/** Why a server can / cannot receive a NEW account right now (mirrors allocation._reject_reason, capacity aside). */
export function serverState(s, panel) {
  if (!s.is_enabled) return { key: "off", tone: "mu", label: "سرور غیرفعال", ok: false };
  if (!panel) return { key: "nopanel", tone: "bd", label: "پنل حذف‌شده", ok: false };
  if (!panel.is_enabled) return { key: "panel_off", tone: "wn", label: "پنل غیرفعال", ok: false };
  const h = health(panel);
  if (h === "unhealthy") return { key: "panel_bad", tone: "bd", label: "پنل ناسالم", ok: false };
  if (h === "unknown") return { key: "panel_unknown", tone: "wn", label: "سلامت پنل بررسی نشده", ok: false };
  if (s.capacity && s.active_accounts >= s.capacity) return { key: "full", tone: "bd", label: "ظرفیت پر", ok: false };
  return { key: "ready", tone: "ok", label: "آماده فروش", ok: true };
}
export const free = (s) => Math.max(0, (s.capacity || 0) - (s.active_accounts || 0));
export const usage = (s) => (s.capacity ? s.active_accounts / s.capacity : 0);
export const serves = (s, code) => !s.product_codes?.length || s.product_codes.includes(code);

/* ---------- derived index ---------- */
export function buildIndex(panels, servers, groups, products) {
  const panelById = new Map(panels.map((p) => [p.id, p]));
  const groupById = new Map(groups.map((g) => [g.id, g]));
  const serversByPanel = new Map(), groupsByPanel = new Map(), productsByGroup = new Map();
  servers.forEach((s) => { (serversByPanel.get(s.panel_id) || serversByPanel.set(s.panel_id, []).get(s.panel_id)).push(s); });
  groups.forEach((g) => (g.panels || []).forEach((m) => { const l = groupsByPanel.get(m.panel_id) || groupsByPanel.set(m.panel_id, []).get(m.panel_id); if (!l.includes(g)) l.push(g); }));
  products.forEach((p) => { if (p.default_panel_group_id) (productsByGroup.get(p.default_panel_group_id) || productsByGroup.set(p.default_panel_group_id, []).get(p.default_panel_group_id)).push(p); });

  const panelStat = (id) => {
    const l = serversByPanel.get(id) || [];
    return { n: l.length, enabled: l.filter((s) => s.is_enabled).length, capacity: l.reduce((a, s) => a + (s.capacity || 0), 0), active: l.reduce((a, s) => a + (s.active_accounts || 0), 0) };
  };
  const groupStat = (g) => {
    const ids = (g.panels || []).map((m) => m.panel_id);
    const l = ids.flatMap((id) => serversByPanel.get(id) || []);
    const live = l.filter((s) => serverState(s, panelById.get(s.panel_id)).ok);
    return { panels: ids.length, servers: l.length, live: live.length, capacity: l.reduce((a, s) => a + (s.capacity || 0), 0), active: l.reduce((a, s) => a + (s.active_accounts || 0), 0), free: live.reduce((a, s) => a + free(s), 0) };
  };
  /** What the core could actually allocate for a product: product → default group → enabled members → live servers. */
  const reach = (p) => {
    let panelIds = null, group = null, issue = "";
    if (p.default_panel_group_id) {
      group = groupById.get(p.default_panel_group_id);
      if (!group) issue = "گروه پیش‌فرض حذف شده است";
      else if (!group.is_enabled) issue = "گروه پیش‌فرض غیرفعال است";
      else { panelIds = new Set((group.panels || []).filter((m) => m.is_enabled).map((m) => m.panel_id)); if (!panelIds.size) issue = "گروه پیش‌فرض پنل فعالی ندارد"; }
    }
    const pool = issue ? [] : servers.filter((s) => (!panelIds || panelIds.has(s.panel_id)) && serves(s, p.code));
    const live = pool.filter((s) => serverState(s, panelById.get(s.panel_id)).ok);
    if (!issue && !pool.length) issue = group ? "هیچ سروری روی پنل‌های این گروه این محصول را پوشش نمی‌دهد" : "هیچ سروری این محصول را پوشش نمی‌دهد";
    else if (!issue && !live.length) issue = "سرورهای سازگار همه غیرفعال، پر یا روی پنل ناسالم‌اند";
    return { group, direct: !p.default_panel_group_id, servers: pool, live, free: live.reduce((a, s) => a + free(s), 0), issue, ok: !issue };
  };
  /** Products that can end up on a server of `panelId` whose allow-list is `codes` (null/[] = all). */
  const productsForPanel = (panelId, codes) => products.filter((p) => {
    if (!p.is_active) return false;
    if (codes?.length && !codes.includes(p.code)) return false;
    if (!p.default_panel_group_id) return true;
    const g = groupById.get(p.default_panel_group_id);
    return !!g && g.is_enabled && (g.panels || []).some((m) => m.is_enabled && m.panel_id === panelId);
  });
  return { panelById, groupById, serversByPanel, groupsByPanel, productsByGroup, panelStat, groupStat, reach, productsForPanel };
}

/** All four lists, loaded once per screen. Pages reload the whole chain after a change so relations never go stale. */
export function useInfra(api) {
  const call = useCallback((p, o) => authFetch(api.base, p, o), [api.base]);
  const panels = useRows(call, "/api/v1/admin/panels");
  const servers = useRows(call, "/api/v1/admin/servers");
  const groups = useRows(call, "/api/v1/admin/panel-groups");
  const products = useRows(call, "/api/v1/admin/products");
  const lists = [panels, servers, groups, products];
  const idx = useMemo(() => buildIndex(panels.rows || [], servers.rows || [], groups.rows || [], products.rows || []), [panels.rows, servers.rows, groups.rows, products.rows]);
  // _loaderRef keeps the latest load fns so reload() never captures a stale closure.
  const _loaderRef = useRef(null);
  _loaderRef.current = { panels: panels.load, servers: servers.load, groups: groups.load, products: products.load };
  const reload = useCallback(
    () => Promise.all([
      _loaderRef.current.panels(),
      _loaderRef.current.servers(),
      _loaderRef.current.groups(),
      _loaderRef.current.products(),
    ]),
    [], // stable; ref updated each render above
  );
  return { call, panels, servers, groups, products, idx, reload, loading: lists.some((l) => l.rows === null), failed: lists.some((l) => l.failed) };
}

/* ---------- UI: links ---------- */
export const InfraLink = ({ to, params, className = "", children, title }) => <a href={infraHref(to, params)} title={title} className={`hover:text-[var(--ac)] hover:underline ${className}`}>{children}</a>;

/** Small clickable chip that jumps to a related item in another screen. */
export function RelChip({ to, params, tone = "mu", Icon, children, title, dim }) {
  return <a href={infraHref(to, params)} title={title} className={`inline-flex max-w-full items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] font-bold transition hover:ring-1 hover:ring-[var(--ac)] ${dim ? "opacity-60" : ""}`} style={tint(tone)}>{Icon && <Icon size={12} className="shrink-0" />}<span className="truncate">{children}</span></a>;
}

/** Row "label · chips" used by cards to show a relation. */
export const Rel = ({ label, children, empty }) => <div className="flex items-start gap-2 text-xs"><span className="mt-1 w-14 shrink-0 text-[11px] text-[var(--mu)]">{label}</span><div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">{children || <span className="py-0.5 text-[11px] text-[var(--mu)]">{empty}</span>}</div></div>;

export const Warn = ({ children, tone = "wn" }) => <p className="flex items-start gap-2 rounded-lg px-3 py-2 text-[11px] font-bold leading-5" style={tint(tone)}><AlertTriangle size={13} className="mt-0.5 shrink-0" />{children}</p>;

/* ---------- UI: the chain header shown on top of all four screens ---------- */
function issuesOf(infra) {
  const { idx } = infra;
  const panels = infra.panels.rows || [], servers = infra.servers.rows || [], groups = infra.groups.rows || [], products = infra.products.rows || [];
  return {
    panels: { n: panels.length, bad: panels.filter((p) => p.is_enabled && health(p) !== "healthy").length, badText: "ناسالم/بررسی‌نشده", empty: panels.filter((p) => !(idx.serversByPanel.get(p.id) || []).length).length, emptyText: "بدون سرور" },
    servers: { n: servers.length, bad: servers.filter((s) => s.is_enabled && usage(s) >= 1).length, badText: "ظرفیت پر", empty: servers.filter((s) => s.is_enabled && !serverState(s, idx.panelById.get(s.panel_id)).ok && usage(s) < 1).length, emptyText: "غیرقابل فروش" },
    groups: { n: groups.length, bad: groups.filter((g) => g.is_enabled && !(g.panels || []).length).length, badText: "بدون پنل", empty: groups.filter((g) => !(idx.productsByGroup.get(g.id) || []).length).length, emptyText: "بدون محصول" },
    products: { n: products.length, bad: products.filter((p) => p.is_active && !idx.reach(p).ok).length, badText: "بدون مسیر تخصیص", empty: products.filter((p) => p.is_active && !p.default_panel_group_id).length, emptyText: "بدون گروه" },
  };
}

export function InfraChain({ current, infra }) {
  const st = useMemo(() => issuesOf(infra), [infra.panels.rows, infra.servers.rows, infra.groups.rows, infra.products.rows]); // eslint-disable-line react-hooks/exhaustive-deps
  const loading = infra.loading;
  return <nav aria-label="زنجیره زیرساخت" className="card rise p-3">
    <ol className="flex flex-col gap-2 lg:flex-row lg:items-stretch lg:gap-0">
      {CHAIN.map((c, i) => {
        const s = st[c.key], on = c.key === current;
        const warn = s.bad > 0;
        return <li key={c.key} className="flex min-w-0 flex-1 items-stretch">
          <a href={infraHref(c.slug)} aria-current={on ? "page" : undefined} className={`flex min-w-0 flex-1 items-center gap-3 rounded-xl border px-3 py-2.5 transition ${on ? "border-[var(--ac)] bg-[var(--sf2)] ring-2 ring-[color-mix(in_srgb,var(--ac)_18%,transparent)]" : "border-transparent hover:bg-[var(--sf2)]"}`}>
            <span className="relative grid h-10 w-10 shrink-0 place-items-center rounded-xl" style={tint(c.tone)}><c.Icon size={19} /><span className="absolute -right-1.5 -top-1.5 grid h-4 w-4 place-items-center rounded-full bg-[var(--nav)] text-[9px] font-extrabold text-white">{num(i + 1)}</span></span>
            <span className="min-w-0 flex-1">
              <span className="flex items-baseline gap-2"><b className="truncate text-sm">{c.title}</b>{loading ? <span className="skel inline-block h-4 w-6" /> : <span className="text-lg font-extrabold leading-none">{num(s.n)}</span>}</span>
              <span className="mt-0.5 block truncate text-[11px] text-[var(--mu)]">{!loading && warn ? <span className="font-bold text-[var(--bd)]">{num(s.bad)} {s.badText}</span> : !loading && s.empty > 0 ? <span className="text-[var(--wn)]">{num(s.empty)} {s.emptyText}</span> : c.hint}</span>
            </span>
          </a>
          {i < CHAIN.length - 1 && <span aria-hidden="true" className="hidden shrink-0 items-center px-1.5 text-[var(--mu)] lg:flex"><ArrowLeft size={16} /></span>}
        </li>;
      })}
    </ol>
  </nav>;
}
