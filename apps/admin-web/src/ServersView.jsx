import { useEffect, useMemo, useState } from "react";
import { Badge, confirmDialog } from "./ui.jsx";
import { ServerForm } from "./ServerForm.jsx";
import { Stat, Switch, num, tint, useAlive } from "./kit.jsx";
import { Dot, InfraChain, InfraLink, Rel, RelChip, Warn, clearParam, free, health, infraHref, serverState, usage, useHashParams, useInfra } from "./infra.jsx";
import { AlertTriangle, CheckCircle2, FlaskConical, Gauge, Layers, LayoutGrid, List, MapPin, PanelTop, Pencil, Plus, Rows3, Search, ServerCog, ServerOff } from "lucide-react";

const usageTone = (u) => (u >= 1 ? "bd" : u >= 0.8 ? "wn" : "ok");

function Meter({ s, slim }) {
  const u = usage(s), t = usageTone(u);
  return <div>
    <div className="mb-1.5 flex items-baseline justify-between text-xs"><span className="text-[var(--mu)]">ظرفیت</span><span className="font-bold"><span style={{ color: `var(--${t})` }}>{num(s.active_accounts)}</span> از {num(s.capacity)}<span className="mr-1.5 font-normal text-[var(--mu)]">({num(Math.round(u * 100))}٪)</span></span></div>
    <div className={`${slim ? "h-1.5" : "h-2"} overflow-hidden rounded-full bg-[var(--mb)]`} role="meter" aria-valuemin={0} aria-valuemax={s.capacity} aria-valuenow={s.active_accounts} aria-label="میزان استفاده از ظرفیت"><div className="h-full rounded-full transition-[width] duration-500" style={{ width: `${Math.min(100, u * 100)}%`, background: `var(--${t})` }} /></div>
  </div>;
}

/** Effective sale state of the server (own flag + panel flag + panel health + capacity). */
const StatePill = ({ st }) => <span className={`badge b-${st.tone}`}>{st.label}</span>;

function Products({ s, byCode, max = 3 }) {
  const list = s.product_codes || [];
  if (!list.length) return <RelChip to="products" tone="in" Icon={Layers} title="این سرور برای همه محصولات استفاده می‌شود">همه محصولات</RelChip>;
  return <>{list.slice(0, max).map((c) => <RelChip key={c} to="products" params={{ q: c }} tone={byCode.has(c) ? "mu" : "wn"} title={byCode.get(c)?.name || "محصول ناشناخته"}>{byCode.get(c)?.name || c}</RelChip>)}
    {list.length > max && <span className="text-[11px] text-[var(--mu)]" title={list.slice(max).map((c) => byCode.get(c)?.name || c).join("، ")}>+{num(list.length - max)}</span>}</>;
}

/* ---------- one server inside its panel section ---------- */
function ServerRow({ s, panel, byCode, busy, onEdit, onToggle }) {
  const st = serverState(s, panel), dim = s.is_enabled ? "" : "opacity-60";
  return <li className="grid gap-3 px-4 py-3.5 md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1.4fr)_auto] md:items-center">
    <div className={`min-w-0 ${dim}`}><div className="flex items-center gap-2"><b className="truncate" title={s.name}>{s.name}</b>{s.allow_test && <span title="اکانت تست مجاز" className="text-[var(--ok)]"><FlaskConical size={13} /></span>}</div>
      <div className="mt-0.5 flex items-center gap-2 text-[11px] text-[var(--mu)]">{s.location ? <span className="flex items-center gap-1"><MapPin size={11} />{s.location}</span> : <span>بدون موقعیت</span>}<StatePill st={st} /></div></div>
    <div className={dim}><Meter s={s} slim /></div>
    <div className={`flex min-w-0 flex-wrap items-center gap-1.5 ${dim}`}><Products s={s} byCode={byCode} max={2} /></div>
    <div className="flex items-center justify-end gap-2"><Switch checked={s.is_enabled} disabled={busy} onChange={(v) => onToggle(s, v)} label={`${s.is_enabled ? "غیرفعال‌سازی" : "فعال‌سازی"} ${s.name}`} /><button className="btn btn-g" onClick={() => onEdit(s)}><Pencil size={13} />ویرایش</button></div>
  </li>;
}

/* ---------- panel section (servers are children of their panel) ---------- */
function PanelSection({ panel, list, groups, stat, byCode, busy, onAdd, onEdit, onToggle, filtered }) {
  const h = health(panel), u = stat.capacity ? stat.active / stat.capacity : 0, t = usageTone(u);
  return <section className="card rise overflow-hidden">
    <header className={`flex flex-wrap items-center gap-3 border-b border-[var(--ln)] bg-[var(--sf2)] px-4 py-3 ${panel.is_enabled ? "" : "opacity-70"}`}>
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl" style={tint(h === "healthy" ? "ok" : h === "unhealthy" ? "bd" : "mu")}><PanelTop size={18} /></span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2"><Dot s={h} ping /><InfraLink to="panels" params={{ id: panel.id }} className="truncate font-extrabold">{panel.name}</InfraLink>{!panel.is_enabled && <Badge s="disabled" />}{h !== "healthy" && panel.is_enabled && <Badge s={h} />}</div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">{groups.length ? groups.slice(0, 3).map((g) => <RelChip key={g.id} to="panel-groups" params={{ q: g.name }} tone="wn" Icon={Layers} dim={!g.is_enabled}>{g.name}</RelChip>) : <span className="text-[11px] text-[var(--wn)]">در هیچ گروهی نیست</span>}{groups.length > 3 && <span className="text-[11px] text-[var(--mu)]">+{num(groups.length - 3)}</span>}</div>
      </div>
      {stat.n > 0 && <div className="hidden w-44 sm:block"><div className="mb-1 flex justify-between text-[11px] text-[var(--mu)]"><span>{num(stat.n)} سرور</span><b style={{ color: `var(--${t})` }}>{num(stat.active)} / {num(stat.capacity)}</b></div><div className="h-1.5 overflow-hidden rounded-full bg-[var(--mb)]"><div className="h-full rounded-full" style={{ width: `${Math.min(100, u * 100)}%`, background: `var(--${t})` }} /></div></div>}
      <button className="btn btn-g !py-1.5" onClick={() => onAdd(panel.id)}><Plus size={14} />سرور جدید</button>
    </header>
    {list.length ? <ul className="divide-y divide-[var(--ln)]">{list.map((s) => <ServerRow key={s.id} s={s} panel={panel} byCode={byCode} busy={busy.has(s.id)} onEdit={onEdit} onToggle={onToggle} />)}</ul>
      : <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-5 text-sm"><span className="flex items-center gap-2 text-[var(--wn)]"><AlertTriangle size={15} />{filtered ? "سروری با این فیلتر روی این پنل نیست" : "این پنل هنوز سرور ندارد؛ تا سرور اضافه نشود اکانتی روی آن ساخته نمی‌شود."}</span>{!filtered && <button className="btn" onClick={() => onAdd(panel.id)}><Plus size={15} />افزودن اولین سرور</button>}</div>}
  </section>;
}

/* ---------- card + table layouts ---------- */
function ServerCard({ s, panel, groups, byCode, busy, onEdit, onToggle }) {
  const st = serverState(s, panel), dim = s.is_enabled ? "" : "opacity-55";
  return <article className="card rise flex flex-col gap-4 p-4">
    <div className={`flex items-start gap-3 ${dim}`}>
      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint(st.ok ? "ok" : st.tone)}><ServerCog size={20} /></span>
      <div className="min-w-0 flex-1"><h3 className="truncate font-extrabold" title={s.name}>{s.name}</h3><p className="mt-0.5 flex items-center gap-1 text-xs text-[var(--mu)]">{s.location ? <><MapPin size={12} />{s.location}</> : "بدون موقعیت"}</p></div>
      <StatePill st={st} />
    </div>
    <div className={`space-y-2 rounded-xl bg-[var(--sf2)] p-3 ${dim}`}>
      <Rel label="پنل"><span className="flex items-center gap-1.5"><Dot s={health(panel)} /><RelChip to="panels" params={{ id: s.panel_id }} tone="in" Icon={PanelTop}>{s.panel_name}</RelChip></span></Rel>
      <Rel label="گروه‌ها" empty="پنل در هیچ گروهی نیست">{groups.length ? groups.slice(0, 3).map((g) => <RelChip key={g.id} to="panel-groups" params={{ q: g.name }} tone="wn" Icon={Layers} dim={!g.is_enabled}>{g.name}</RelChip>) : null}</Rel>
      <Rel label="محصول"><Products s={s} byCode={byCode} /></Rel>
    </div>
    <div className={dim}><Meter s={s} /></div>
    <div className="mt-auto flex items-center justify-between gap-2 border-t border-[var(--ln)] pt-3">
      <label className="flex items-center gap-2 text-xs text-[var(--mu)]"><Switch checked={s.is_enabled} disabled={busy} onChange={(v) => onToggle(s, v)} label={`${s.is_enabled ? "غیرفعال‌سازی" : "فعال‌سازی"} ${s.name}`} />{s.is_enabled ? "فعال" : "غیرفعال"}</label>
      <button className="btn btn-g" onClick={() => onEdit(s)}><Pencil size={13} />ویرایش</button>
    </div>
  </article>;
}

function ServerTable({ rows, idx, byCode, busy, onEdit, onToggle }) {
  return <section className="card rise overflow-hidden"><div className="overflow-auto"><table className="tbl min-w-[980px]"><thead><tr>{["سرور", "پنل", "گروه‌ها", "ظرفیت", "محصولات", "وضعیت", "فعال", ""].map((c, i) => <th key={i}>{c}</th>)}</tr></thead>
    <tbody>{rows.map((s) => { const panel = idx.panelById.get(s.panel_id), gs = idx.groupsByPanel.get(s.panel_id) || [];
      return <tr key={s.id} className={s.is_enabled ? "" : "opacity-60"}>
        <td><div className="font-bold">{s.name}</div><div className="text-[11px] text-[var(--mu)]">{s.location || "—"}</div></td>
        <td><span className="flex items-center gap-2"><Dot s={health(panel)} /><InfraLink to="panels" params={{ id: s.panel_id }} className="font-semibold">{s.panel_name}</InfraLink></span></td>
        <td><div className="flex flex-wrap gap-1">{gs.length ? gs.slice(0, 2).map((g) => <RelChip key={g.id} to="panel-groups" params={{ q: g.name }} tone="wn" dim={!g.is_enabled}>{g.name}</RelChip>) : <span className="text-[11px] text-[var(--wn)]">—</span>}{gs.length > 2 && <span className="text-[11px] text-[var(--mu)]">+{num(gs.length - 2)}</span>}</div></td>
        <td className="min-w-[170px]"><Meter s={s} slim /></td>
        <td><div className="flex flex-wrap gap-1"><Products s={s} byCode={byCode} max={2} /></div></td>
        <td><StatePill st={serverState(s, panel)} /></td>
        <td><Switch checked={s.is_enabled} disabled={busy.has(s.id)} onChange={(v) => onToggle(s, v)} label={`${s.is_enabled ? "غیرفعال‌سازی" : "فعال‌سازی"} ${s.name}`} /></td>
        <td><button className="btn btn-g" onClick={() => onEdit(s)}><Pencil size={13} />ویرایش</button></td></tr>; })}</tbody></table></div></section>;
}

/* ---------- page ---------- */
// Deep links: #/servers?panel=<id>  ·  ?group=<id>  ·  ?product=<code>  ·  ?add=1[&panel=<id>]
export default function ServersView({ api, toast }) {
  const infra = useInfra(api);
  const { idx } = infra;
  const params = useHashParams();
  const alive = useAlive();
  const [q, setQ] = useState(""); const [filter, setFilter] = useState("all");
  const [panelF, setPanelF] = useState(params.get("panel") || "all"); const [groupF, setGroupF] = useState(params.get("group") || "all"); const [productF, setProductF] = useState(params.get("product") || "all");
  const [layout, setLayout] = useState("panel"); const [drawer, setDrawer] = useState(null); const [preset, setPreset] = useState(""); const [busy, setBusy] = useState(new Set());

  useEffect(() => { setPanelF(params.get("panel") || "all"); setGroupF(params.get("group") || "all"); setProductF(params.get("product") || "all"); }, [params]);
  useEffect(() => { if (params.get("add")) { setPreset(params.get("panel") || ""); setDrawer("add"); clearParam("add"); } }, [params]);

  const panelRows = infra.panels.rows, rows = infra.servers.rows, productRows = infra.products.rows, groupRows = infra.groups.rows;
  const byCode = useMemo(() => new Map((productRows || []).map((p) => [p.code, p])), [productRows]);
  const stateOf = (s) => serverState(s, idx.panelById.get(s.panel_id));
  const counts = useMemo(() => {
    const c = { all: 0, ready: 0, near: 0, blocked: 0 };
    (rows || []).forEach((s) => { c.all++; const st = serverState(s, idx.panelById.get(s.panel_id)); if (st.ok) { c.ready++; if (usage(s) >= 0.8) c.near++; } else c.blocked++; });
    return c;
  }, [rows, idx]);
  const groupPanels = useMemo(() => (groupF === "all" ? null : new Set((idx.groupById.get(groupF)?.panels || []).map((m) => m.panel_id))), [groupF, idx]);
  const productObj = productF === "all" ? null : byCode.get(productF);
  const shown = useMemo(() => (rows || []).filter((s) => {
    const st = serverState(s, idx.panelById.get(s.panel_id));
    if (filter === "ready" && !st.ok) return false;
    if (filter === "near" && !(st.ok && usage(s) >= 0.8)) return false;
    if (filter === "blocked" && st.ok) return false;
    if (panelF !== "all" && s.panel_id !== panelF) return false;
    if (groupPanels && !groupPanels.has(s.panel_id)) return false;
    if (productF !== "all" && !(!s.product_codes?.length || s.product_codes.includes(productF))) return false;
    return `${s.name} ${s.location || ""} ${s.panel_name} ${(s.product_codes || []).join(" ")}`.toLowerCase().includes(q.trim().toLowerCase());
  }), [rows, filter, panelF, groupPanels, productF, q, idx]);
  const hasFilter = filter !== "all" || panelF !== "all" || groupF !== "all" || productF !== "all" || q.trim();
  const locations = useMemo(() => [...new Set((rows || []).map((s) => s.location).filter(Boolean))].sort(), [rows]);
  const editing = drawer && drawer !== "add" ? (rows || []).find((s) => s.id === drawer) : null;
  const loading = infra.loading;
  const reset = () => { setQ(""); setFilter("all"); setPanelF("all"); setGroupF("all"); setProductF("all"); if (window.location.hash.includes("?")) window.history.replaceState(null, "", window.location.pathname + window.location.search + window.location.hash.split("?")[0]); };
  const openAdd = (panelId) => { setPreset(panelId || (panelF !== "all" ? panelF : "")); setDrawer("add"); };

  const toggle = async (s, next) => {
    if (!next && !(await confirmDialog(`«${s.name}» غیرفعال شود؟ برای ساخت اکانت جدید انتخاب نمی‌شود؛ اکانت‌های موجود حذف نمی‌شوند.`, { title: "غیرفعال‌سازی سرور", danger: true, ok: "غیرفعال کن" }))) return;
    setBusy((x) => new Set(x).add(s.id));
    let ok = false;
    try { ok = (await infra.call(`/api/v1/admin/servers/${s.id}/state`, { method: "POST", body: JSON.stringify({ is_enabled: next }) })).ok; } catch { /* network */ }
    if (alive.current) setBusy((x) => { const n = new Set(x); n.delete(s.id); return n; });
    toast(ok ? (next ? `«${s.name}» فعال شد` : `«${s.name}» غیرفعال شد`) : "تغییر وضعیت ناموفق بود");
    if (ok) await infra.servers.load();
  };

  // panel sections: every panel (so empty panels are visible) unless a filter narrows the list
  const sections = useMemo(() => {
    const by = new Map(); shown.forEach((s) => (by.get(s.panel_id) || by.set(s.panel_id, []).get(s.panel_id)).push(s));
    return (panelRows || []).filter((p) => (by.has(p.id) || (!hasFilter) || (panelF === p.id && !q.trim() && filter === "all" && productF === "all")) && (panelF === "all" || panelF === p.id) && (!groupPanels || groupPanels.has(p.id))).map((p) => [p, by.get(p.id) || []]);
  }, [shown, panelRows, hasFilter, panelF, groupPanels, q, filter, productF]);

  const emptyNoPanels = !loading && !(panelRows || []).length;

  return <div className="space-y-5">
    <InfraChain current="servers" infra={infra} />

    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Stat label="همه سرورها" value={counts.all} tone="in" Icon={ServerCog} active={filter === "all"} onClick={() => setFilter("all")} />
      <Stat label="آماده فروش" value={counts.ready} tone="ok" Icon={CheckCircle2} active={filter === "ready"} onClick={() => setFilter(filter === "ready" ? "all" : "ready")} />
      <Stat label="نزدیک پر شدن (۸۰٪+)" value={counts.near} tone="wn" Icon={Gauge} active={filter === "near"} onClick={() => setFilter(filter === "near" ? "all" : "near")} />
      <Stat label="غیرقابل فروش" value={counts.blocked} tone="bd" Icon={ServerOff} active={filter === "blocked"} onClick={() => setFilter(filter === "blocked" ? "all" : "blocked")} />
    </div>

    <div className="flex flex-wrap items-center gap-2">
      <label className="relative min-w-[12rem] flex-1 sm:max-w-xs"><Search size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[var(--mu)]" /><input aria-label="جستجوی سرور" className="inp pr-9" placeholder="جستجو در نام، موقعیت یا پنل…" value={q} onChange={(e) => setQ(e.target.value)} /></label>
      <select aria-label="فیلتر پنل" className="inp !w-auto" value={panelF} onChange={(e) => setPanelF(e.target.value)}><option value="all">همه پنل‌ها</option>{(panelRows || []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
      <select aria-label="فیلتر گروه پنل" className="inp !w-auto" value={groupF} onChange={(e) => setGroupF(e.target.value)}><option value="all">همه گروه‌ها</option>{(groupRows || []).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</select>
      <select aria-label="فیلتر محصول" className="inp !w-auto" value={productF} onChange={(e) => setProductF(e.target.value)}><option value="all">همه محصولات</option>{(productRows || []).map((p) => <option key={p.id} value={p.code}>{p.name}</option>)}</select>
      <div className="pv-seg" role="group" aria-label="نحوه نمایش">
        <button type="button" className={layout === "panel" ? "on" : ""} aria-label="بر اساس پنل" title="بر اساس پنل" onClick={() => setLayout("panel")}><Rows3 size={15} /></button>
        <button type="button" className={layout === "grid" ? "on" : ""} aria-label="کارتی" title="کارتی" onClick={() => setLayout("grid")}><LayoutGrid size={15} /></button>
        <button type="button" className={layout === "list" ? "on" : ""} aria-label="جدولی" title="جدولی" onClick={() => setLayout("list")}><List size={15} /></button></div>
      {hasFilter && <button className="text-xs font-bold text-[var(--ac)] underline" onClick={reset}>پاک‌کردن فیلترها</button>}
      <button className="btn mr-auto" onClick={() => openAdd("")} disabled={emptyNoPanels}><Plus size={16} />افزودن سرور</button>
    </div>

    {(productObj || groupF !== "all") && <p className="flex flex-wrap items-center gap-2 rounded-xl bg-[var(--inb)] px-3 py-2 text-xs font-bold text-[var(--in)]">
      {groupF !== "all" && <>نمایش سرورهای پنل‌های گروه «{idx.groupById.get(groupF)?.name || "؟"}»</>}{groupF !== "all" && productObj && " · "}{productObj && <>سرورهایی که «{productObj.name}» را پوشش می‌دهند</>}</p>}

    {infra.failed && <p role="alert" className="flex items-center gap-2 rounded-xl bg-[var(--bdb)] p-3 text-sm text-[var(--bd)]"><AlertTriangle size={16} />دریافت اطلاعات ناموفق بود. <button className="underline" onClick={infra.reload}>تلاش دوباره</button></p>}

    {loading ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="card skel h-52" />)}</div>
      : emptyNoPanels ? <div className="card grid place-items-center gap-3 p-14 text-center"><span className="grid h-14 w-14 place-items-center rounded-2xl bg-[var(--mb)] text-[var(--mu)]"><PanelTop size={26} /></span>
        <h3 className="font-extrabold">ابتدا یک پنل اضافه کنید</h3><p className="max-w-sm text-sm leading-7 text-[var(--mu)]">هر سرور زیر یک پنل ثبت می‌شود؛ مرحله‌ی اول زنجیره، اتصال پنل است.</p><a className="btn" href={infraHref("panels")}>رفتن به پنل‌ها</a></div>
      : layout === "panel" ? (sections.length ? <div className="space-y-4">{sections.map(([p, list]) => <PanelSection key={p.id} panel={p} list={list} groups={idx.groupsByPanel.get(p.id) || []} stat={idx.panelStat(p.id)} byCode={byCode} busy={busy} filtered={!!hasFilter} onAdd={openAdd} onEdit={(x) => setDrawer(x.id)} onToggle={toggle} />)}</div>
        : <EmptyFiltered total={counts.all} onReset={reset} onAdd={() => openAdd("")} />)
      : !shown.length ? <EmptyFiltered total={counts.all} onReset={reset} onAdd={() => openAdd("")} />
        : layout === "grid" ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{shown.map((s) => <ServerCard key={s.id} s={s} panel={idx.panelById.get(s.panel_id)} groups={idx.groupsByPanel.get(s.panel_id) || []} byCode={byCode} busy={busy.has(s.id)} onEdit={(x) => setDrawer(x.id)} onToggle={toggle} />)}</div>
          : <ServerTable rows={shown} idx={idx} byCode={byCode} busy={busy} onEdit={(x) => setDrawer(x.id)} onToggle={toggle} />}

    {drawer && (drawer === "add" || editing) && <ServerForm key={`${drawer}:${preset}`} api={api} toast={toast} infra={infra} presetPanel={preset} locations={locations}
      server={drawer === "add" ? null : editing} toggling={editing ? busy.has(editing.id) : false} onToggle={toggle} onSaved={infra.reload} onClose={() => { setDrawer(null); setPreset(""); }} />}
  </div>;
}

function EmptyFiltered({ total, onReset, onAdd }) {
  return <div className="card grid place-items-center gap-3 p-14 text-center"><span className="grid h-14 w-14 place-items-center rounded-2xl bg-[var(--mb)] text-[var(--mu)]"><ServerCog size={26} /></span>
    <h3 className="font-extrabold">{total ? "سروری با این فیلتر پیدا نشد" : "هنوز سروری اضافه نشده"}</h3>
    <p className="max-w-sm text-sm leading-7 text-[var(--mu)]">{total ? "جستجو یا فیلترها را تغییر دهید." : "سرور مشخص می‌کند اکانت‌های جدید روی کدام پنل و با چه ظرفیتی ساخته شوند."}</p>
    {total ? <button className="btn btn-g" onClick={onReset}>پاک‌کردن فیلترها</button> : <button className="btn" onClick={onAdd}><Plus size={16} />افزودن اولین سرور</button>}</div>;
}
