import { useCallback, useEffect, useMemo, useState } from "react";
import { authFetch } from "./api.js";
import { Badge, confirmDialog } from "./ui.jsx";
import { ServerForm } from "./ServerForm.jsx";
import { Stat, Switch, num, tint, useAlive, useRows } from "./kit.jsx";
import { AlertTriangle, FlaskConical, LayoutGrid, List, MapPin, Pencil, Plus, Search, Server, ServerOff, Gauge, Layers } from "lucide-react";

const usage = (s) => (s.capacity ? s.active_accounts / s.capacity : 0);
const usageTone = (u) => (u >= 1 ? "bd" : u >= 0.8 ? "wn" : "ok");
const health = (p) => (p?.health_status === "healthy" || p?.health_status === "unhealthy" ? p.health_status : "unknown");

function Dot({ s }) {
  const c = { healthy: "var(--ok)", unhealthy: "var(--bd)", unknown: "var(--mu)" }[s];
  return <span className="relative inline-flex h-2.5 w-2.5 shrink-0"><span className={`absolute inset-0 rounded-full ${s === "healthy" ? "pv-ping" : ""}`} style={{ background: c }} /><span className="relative h-2.5 w-2.5 rounded-full" style={{ background: c }} /></span>;
}

function Capacity({ s }) {
  const u = usage(s), t = usageTone(u);
  return <div>
    <div className="mb-1.5 flex items-baseline justify-between text-xs"><span className="text-[var(--mu)]">ظرفیت</span><span className="font-bold"><span style={{ color: `var(--${t})` }}>{num(s.active_accounts)}</span> از {num(s.capacity)}<span className="mr-1.5 font-normal text-[var(--mu)]">({num(Math.round(u * 100))}٪)</span></span></div>
    <div className="h-2 overflow-hidden rounded-full bg-[var(--mb)]" role="meter" aria-valuemin={0} aria-valuemax={s.capacity} aria-valuenow={s.active_accounts} aria-label="میزان استفاده از ظرفیت"><div className="h-full rounded-full transition-[width] duration-500" style={{ width: `${Math.min(100, u * 100)}%`, background: `var(--${t})` }} /></div>
  </div>;
}

function Codes({ list, max = 3 }) {
  if (!list?.length) return <span className="badge b-in">همه محصولات</span>;
  return <span className="flex flex-wrap items-center gap-1.5">{list.slice(0, max).map((c) => <code key={c} dir="ltr" className="rounded-md bg-[var(--mb)] px-1.5 py-0.5 text-[11px] font-bold">{c}</code>)}{list.length > max && <span className="text-[11px] text-[var(--mu)]" title={list.slice(max).join("، ")}>+{num(list.length - max)}</span>}</span>;
}

function ServerCard({ s, panel, busy, onEdit, onToggle }) {
  const h = health(panel), dim = s.is_enabled ? "" : "opacity-55";
  return <article className="card rise flex flex-col gap-4 p-4">
    <div className={`flex items-start gap-3 ${dim}`}>
      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint(s.is_enabled ? "in" : "mu")}><Server size={20} /></span>
      <div className="min-w-0 flex-1"><h3 className="truncate font-extrabold" title={s.name}>{s.name}</h3>
        <p className="mt-0.5 flex items-center gap-1 text-xs text-[var(--mu)]">{s.location ? <><MapPin size={12} />{s.location}</> : "بدون موقعیت"}</p></div>
      <Badge s={s.is_enabled ? "active" : "disabled"} />
    </div>
    <div className={`flex items-center gap-2 rounded-lg bg-[var(--sf2)] px-3 py-2 text-xs ${dim}`}><Dot s={h} /><span className="min-w-0 flex-1 truncate font-bold" title={s.panel_name}>{s.panel_name}</span>
      {panel && !panel.is_enabled ? <Badge s="disabled" /> : <span className="text-[var(--mu)]">{h === "healthy" ? "پنل سالم" : h === "unhealthy" ? "پنل ناسالم" : "بررسی‌نشده"}</span>}</div>
    <div className={dim}><Capacity s={s} /></div>
    <div className={`flex flex-wrap items-center justify-between gap-2 ${dim}`}><Codes list={s.product_codes} />
      <span className={`flex items-center gap-1 text-[11px] ${s.allow_test ? "text-[var(--ok)]" : "text-[var(--mu)]"}`}><FlaskConical size={13} />{s.allow_test ? "تست مجاز" : "بدون تست"}</span></div>
    <div className="mt-auto flex items-center justify-between gap-2 border-t border-[var(--ln)] pt-3">
      <label className="flex items-center gap-2 text-xs text-[var(--mu)]"><Switch checked={s.is_enabled} disabled={busy} onChange={(v) => onToggle(s, v)} label={`${s.is_enabled ? "غیرفعال‌سازی" : "فعال‌سازی"} ${s.name}`} />{s.is_enabled ? "فعال" : "غیرفعال"}</label>
      <button className="btn btn-g" onClick={() => onEdit(s)}><Pencil size={13} />ویرایش</button>
    </div>
  </article>;
}

function ServerTable({ rows, panels, busy, onEdit, onToggle }) {
  return <section className="card rise overflow-hidden"><div className="overflow-auto"><table className="tbl min-w-[900px]"><thead><tr>{["نام", "موقعیت", "پنل", "ظرفیت", "محصولات", "تست", "فعال", ""].map((c, i) => <th key={i}>{c}</th>)}</tr></thead>
    <tbody>{rows.map((s) => <tr key={s.id} className={s.is_enabled ? "" : "opacity-60"}>
      <td className="font-bold">{s.name}</td><td className="text-[var(--mu)]">{s.location || "-"}</td>
      <td><span className="flex items-center gap-2"><Dot s={health(panels.get(s.panel_id))} />{s.panel_name}</span></td>
      <td className="min-w-[170px]"><Capacity s={s} /></td><td><Codes list={s.product_codes} max={2} /></td>
      <td>{s.allow_test ? <span className="text-[var(--ok)]">مجاز</span> : <span className="text-[var(--mu)]">خیر</span>}</td>
      <td><Switch checked={s.is_enabled} disabled={busy.has(s.id)} onChange={(v) => onToggle(s, v)} label={`${s.is_enabled ? "غیرفعال‌سازی" : "فعال‌سازی"} ${s.name}`} /></td>
      <td><button className="btn btn-g" onClick={() => onEdit(s)}><Pencil size={13} />ویرایش</button></td></tr>)}</tbody></table></div></section>;
}

// startAdd: bump to open the add drawer from outside; initialPanel: pre-filter by panel id.
export default function ServersView({ api, toast, startAdd, initialPanel, onGoPanels }) {
  const call = useCallback((p, o) => authFetch(api.base, p, o), [api.base]);
  const servers = useRows(call, "/api/v1/admin/servers");
  const panelRows = useRows(call, "/api/v1/admin/panels");
  const products = useRows(call, "/api/v1/admin/products");
  const alive = useAlive();
  const [q, setQ] = useState(""); const [filter, setFilter] = useState("all"); const [panelF, setPanelF] = useState(initialPanel || "all");
  const [layout, setLayout] = useState("grid"); const [drawer, setDrawer] = useState(startAdd ? "add" : null); const [busy, setBusy] = useState(new Set());
  useEffect(() => { if (startAdd) setDrawer("add"); }, [startAdd]);

  const panels = useMemo(() => new Map((panelRows.rows || []).map((p) => [p.id, p])), [panelRows.rows]);
  const rows = servers.rows;
  const counts = useMemo(() => {
    const c = { all: 0, enabled: 0, near: 0, disabled: 0 };
    (rows || []).forEach((s) => { c.all++; if (!s.is_enabled) c.disabled++; else { c.enabled++; if (usage(s) >= 0.8) c.near++; } });
    return c;
  }, [rows]);
  const shown = useMemo(() => (rows || []).filter((s) => {
    if (filter === "enabled" && !s.is_enabled) return false;
    if (filter === "disabled" && s.is_enabled) return false;
    if (filter === "near" && !(s.is_enabled && usage(s) >= 0.8)) return false;
    if (panelF !== "all" && s.panel_id !== panelF) return false;
    return `${s.name} ${s.location || ""} ${s.panel_name} ${(s.product_codes || []).join(" ")}`.toLowerCase().includes(q.trim().toLowerCase());
  }), [rows, filter, panelF, q]);
  const locations = useMemo(() => [...new Set((rows || []).map((s) => s.location).filter(Boolean))].sort(), [rows]);
  const editing = drawer && drawer !== "add" ? (rows || []).find((s) => s.id === drawer) : null;
  const loading = rows === null || panelRows.rows === null;
  const reloadAll = async () => { await Promise.all([servers.load(), panelRows.load()]); };

  const toggle = async (s, next) => {
    if (!next && !(await confirmDialog(`«${s.name}» غیرفعال شود؟ برای ساخت اکانت جدید انتخاب نمی‌شود؛ اکانت‌های موجود حذف نمی‌شوند.`, { title: "غیرفعال‌سازی سرور", danger: true, ok: "غیرفعال کن" }))) return;
    setBusy((x) => new Set(x).add(s.id));
    let ok = false;
    try { ok = (await call(`/api/v1/admin/servers/${s.id}/state`, { method: "POST", body: JSON.stringify({ is_enabled: next }) })).ok; } catch { /* network */ }
    if (alive.current) setBusy((x) => { const n = new Set(x); n.delete(s.id); return n; });
    toast(ok ? (next ? `«${s.name}» فعال شد` : `«${s.name}» غیرفعال شد`) : "تغییر وضعیت ناموفق بود");
    if (ok) await servers.load();
  };

  return <div className="space-y-5">
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Stat label="همه سرورها" value={counts.all} tone="in" Icon={Layers} active={filter === "all"} onClick={() => setFilter("all")} />
      <Stat label="فعال" value={counts.enabled} tone="ok" Icon={Server} active={filter === "enabled"} onClick={() => setFilter(filter === "enabled" ? "all" : "enabled")} />
      <Stat label="نزدیک پر شدن (۸۰٪+)" value={counts.near} tone="wn" Icon={Gauge} active={filter === "near"} onClick={() => setFilter(filter === "near" ? "all" : "near")} />
      <Stat label="غیرفعال" value={counts.disabled} tone="mu" Icon={ServerOff} active={filter === "disabled"} onClick={() => setFilter(filter === "disabled" ? "all" : "disabled")} />
    </div>

    <div className="flex flex-wrap items-center gap-2">
      <label className="relative min-w-[12rem] flex-1 sm:max-w-xs"><Search size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[var(--mu)]" /><input aria-label="جستجوی سرور" className="inp pr-9" placeholder="جستجو در نام، موقعیت، پنل یا کد محصول…" value={q} onChange={(e) => setQ(e.target.value)} /></label>
      <select aria-label="فیلتر پنل" className="inp !w-auto" value={panelF} onChange={(e) => setPanelF(e.target.value)}><option value="all">همه پنل‌ها</option>{(panelRows.rows || []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
      <div className="pv-seg" role="group" aria-label="نحوه نمایش"><button type="button" className={layout === "grid" ? "on" : ""} aria-label="کارتی" onClick={() => setLayout("grid")}><LayoutGrid size={15} /></button><button type="button" className={layout === "list" ? "on" : ""} aria-label="جدولی" onClick={() => setLayout("list")}><List size={15} /></button></div>
      <button className="btn mr-auto" onClick={() => setDrawer("add")}><Plus size={16} />افزودن سرور</button>
    </div>

    {(servers.failed || panelRows.failed) && <p role="alert" className="flex items-center gap-2 rounded-xl bg-[var(--bdb)] p-3 text-sm text-[var(--bd)]"><AlertTriangle size={16} />دریافت اطلاعات ناموفق بود. <button className="underline" onClick={reloadAll}>تلاش دوباره</button></p>}

    {loading ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="card skel h-52" />)}</div>
      : !shown.length ? <div className="card grid place-items-center gap-3 p-14 text-center"><span className="grid h-14 w-14 place-items-center rounded-2xl bg-[var(--mb)] text-[var(--mu)]"><Server size={26} /></span>
        <h3 className="font-extrabold">{counts.all ? "سروری با این فیلتر پیدا نشد" : !panels.size ? "ابتدا یک پنل اضافه کنید" : "هنوز سروری اضافه نشده"}</h3>
        <p className="max-w-sm text-sm leading-7 text-[var(--mu)]">{counts.all ? "جستجو یا فیلترها را تغییر دهید." : !panels.size ? "هر سرور زیر یک پنل ثبت می‌شود." : "سرور مشخص می‌کند اکانت‌های جدید روی کدام پنل و با چه ظرفیتی ساخته شوند."}</p>
        {!counts.all && (panels.size ? <button className="btn" onClick={() => setDrawer("add")}><Plus size={16} />افزودن اولین سرور</button> : onGoPanels && <button className="btn" onClick={onGoPanels}>رفتن به پنل‌ها</button>)}</div>
      : layout === "grid" ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{shown.map((s) => <ServerCard key={s.id} s={s} panel={panels.get(s.panel_id)} busy={busy.has(s.id)} onEdit={(x) => setDrawer(x.id)} onToggle={toggle} />)}</div>
        : <ServerTable rows={shown} panels={panels} busy={busy} onEdit={(x) => setDrawer(x.id)} onToggle={toggle} />}

    {drawer && (drawer === "add" || editing) && <ServerForm key={drawer} api={api} toast={toast} panels={panelRows.rows || []} products={products.failed ? [] : products.rows} locations={locations}
      server={drawer === "add" ? null : editing} toggling={editing ? busy.has(editing.id) : false} onToggle={toggle} onSaved={reloadAll} onClose={() => setDrawer(null)} />}
  </div>;
}
