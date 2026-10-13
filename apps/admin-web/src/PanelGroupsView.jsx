import { useMemo, useRef, useState } from "react";
import { authFetch } from "./api.js";
import { Badge, confirmDialog } from "./ui.jsx";
import { ArrowDown, ArrowUp, Layers, Pencil, Plus, Search, ShieldAlert, ShoppingBag, Wand2, Hand, X, AlertTriangle, PowerOff, CheckCircle2 } from "lucide-react";
import { Drawer, Field, NumInput, Section, Segmented, Stat, Switch, Toggle, errText, num, tint, useAlive, useRows } from "./kit.jsx";

const API = "/api/v1/admin/panel-groups";
const MODES = { automatic: ["خودکار", "سیستم بهترین پنل را انتخاب می‌کند", Wand2], manual: ["دستی", "فقط پنل‌های انتخاب‌شده، به ترتیب اولویت", Hand] };
const NAMING = { automatic: "خودکار", custom: "نام دلخواه کاربر" };
const hs = (p) => (p?.health_status === "healthy" || p?.health_status === "unhealthy" ? p.health_status : "unknown");
const hcolor = { healthy: "var(--ok)", unhealthy: "var(--bd)", unknown: "var(--mu)" };
const KIND = { sanaei: "سنایی", pasarguard: "پاسارگارد", mock: "Mock" };
const Dot = ({ s }) => <span className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: hcolor[s] }} title={{ healthy: "سالم", unhealthy: "ناسالم", unknown: "بررسی‌نشده" }[s]} />;

function Quota({ sold, limit }) {
  const pct = limit ? Math.min(100, Math.round((sold / limit) * 100)) : 0;
  const full = limit && sold >= limit, warn = limit && pct >= 80;
  return <div>
    <div className="mb-1.5 flex items-center justify-between text-[11px]"><span className="text-[var(--mu)]">فروش</span><b className={full ? "text-[var(--bd)]" : ""}>{num(sold)} / {limit ? num(limit) : "نامحدود"}{full ? " · پر شده" : ""}</b></div>
    <div className="h-1.5 overflow-hidden rounded-full bg-[var(--mb)]" role="progressbar" aria-valuenow={limit ? pct : undefined} aria-label="سهمیه فروش"><div className="h-full rounded-full transition-all" style={{ width: limit ? `${Math.max(pct, 3)}%` : "100%", background: limit ? (full ? "var(--bd)" : warn ? "var(--wn)" : "var(--ok)") : "var(--mb)", opacity: limit ? 1 : .6 }} /></div>
  </div>;
}

function GroupCard({ g, panelById, busy, onEdit, onToggle }) {
  const ms = g.panels || [];
  return <article className="card rise flex flex-col gap-4 p-4">
    <div className={`flex items-start gap-3 ${g.is_enabled ? "" : "opacity-55"}`}>
      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint("in")}><Layers size={20} /></span>
      <div className="min-w-0 flex-1"><h3 className="truncate font-extrabold" title={g.name}>{g.name}</h3>
        <p className="mt-0.5 text-xs text-[var(--mu)]">انتخاب {MODES[g.selection_mode]?.[0] || g.selection_mode} · نام‌گذاری {NAMING[g.naming_mode] || g.naming_mode}</p></div>
      <Badge s={g.is_enabled ? "active" : "disabled"} />
    </div>
    <div className={g.is_enabled ? "" : "opacity-55"}><Quota sold={g.sold_count || 0} limit={g.sales_limit} /></div>
    <div className={`space-y-1.5 ${g.is_enabled ? "" : "opacity-55"}`}>
      <div className="flex items-center justify-between text-[11px] text-[var(--mu)]"><span>پنل‌ها ({num(ms.length)})</span>{!g.reseller_enabled && <span className="badge b-mu">بدون نمایندگی</span>}</div>
      {ms.length ? <div className="flex flex-wrap gap-1.5">{ms.slice(0, 5).map((m) => { const p = panelById[m.panel_id]; return <span key={m.id} className={`inline-flex max-w-[11rem] items-center gap-1.5 rounded-lg bg-[var(--sf2)] px-2 py-1 text-xs ${m.is_enabled ? "" : "line-through opacity-60"}`}><Dot s={hs(p)} /><span className="truncate">{p?.name || "پنل حذف‌شده"}</span></span>; })}{ms.length > 5 && <span className="rounded-lg bg-[var(--mb)] px-2 py-1 text-xs font-bold">+{num(ms.length - 5)}</span>}</div>
        : <p className="flex items-center gap-1.5 text-xs text-[var(--wn)]"><AlertTriangle size={13} />هنوز پنلی به این گروه اضافه نشده</p>}
    </div>
    <div className="mt-auto flex items-center justify-between gap-2 border-t border-[var(--ln)] pt-3">
      <label className="flex cursor-pointer items-center gap-2 text-xs font-bold"><Switch checked={g.is_enabled} disabled={busy} onChange={(v) => onToggle(g, v)} label={`فعال‌سازی ${g.name}`} />{g.is_enabled ? "فعال" : "غیرفعال"}</label>
      <button className="btn btn-g" onClick={() => onEdit(g)}><Pencil size={13} />ویرایش</button>
    </div>
  </article>;
}

const EMPTY = { name: "", selection_mode: "automatic", naming_mode: "automatic", sales_limit: "", is_enabled: true, reseller_enabled: true, panel_ids: [] };
const fromGroup = (g) => ({ name: g.name, selection_mode: g.selection_mode, naming_mode: g.naming_mode, sales_limit: g.sales_limit ? String(g.sales_limit) : "", is_enabled: g.is_enabled, reseller_enabled: g.reseller_enabled, panel_ids: (g.panels || []).slice().sort((a, b) => a.sort - b.sort).map((m) => m.panel_id) });

function GroupDrawer({ group, panels, onClose, onSubmit }) {
  const edit = !!group;
  const [f, setF] = useState(() => (group ? fromGroup(group) : EMPTY));
  const base = useRef(JSON.stringify(f));
  const [tried, setTried] = useState(false), [busy, setBusy] = useState(false), [srv, setSrv] = useState(""), [pq, setPq] = useState("");
  const set = (k) => (v) => { setSrv(""); setF((x) => ({ ...x, [k]: v })); };
  const dirty = JSON.stringify(f) !== base.current;
  const byId = useMemo(() => Object.fromEntries(panels.map((p) => [p.id, p])), [panels]);
  const soldInGroup = group?.sold_count || 0;
  const err = {};
  if (f.name.trim().length < 2) err.name = "نام گروه حداقل ۲ نویسه باشد";
  if (f.selection_mode === "manual" && !f.panel_ids.length) err.panels = "گروه دستی باید حداقل یک پنل داشته باشد";
  if (f.sales_limit !== "" && Number(f.sales_limit) < 1) err.limit = "سقف باید عدد مثبت باشد یا خالی بماند";
  const toggleP = (id) => set("panel_ids")(f.panel_ids.includes(id) ? f.panel_ids.filter((x) => x !== id) : [...f.panel_ids, id]);
  const move = (i, d) => { const a = [...f.panel_ids]; const j = i + d; if (j < 0 || j >= a.length) return; [a[i], a[j]] = [a[j], a[i]]; set("panel_ids")(a); };
  const avail = panels.filter((p) => !f.panel_ids.includes(p.id) && `${p.name} ${KIND[p.kind] || p.kind}`.toLowerCase().includes(pq.trim().toLowerCase()));
  const submit = async () => {
    setTried(true); if (Object.keys(err).length) return;
    setBusy(true); const msg = await onSubmit({ ...f, name: f.name.trim(), sales_limit: f.sales_limit === "" ? null : Number(f.sales_limit) }, group); setBusy(false); if (msg) setSrv(msg);
  };
  return <Drawer title={edit ? `ویرایش «${group.name}»` : "افزودن گروه پنل VPN"} subtitle={edit ? `${num(soldInGroup)} فروش ثبت‌شده` : "مجموعه‌ای از پنل‌ها با سیاست انتخاب، نام‌گذاری و سقف فروش"} icon={<span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint("in")}><Layers size={20} /></span>} dirty={dirty} busy={busy} onClose={onClose} error={srv}
    footer={<button className="btn !py-2 !text-sm" disabled={busy} onClick={submit}>{busy ? "در حال ذخیره…" : edit ? "ذخیره تغییرات" : "ساخت گروه"}</button>}>
    <Section title={edit ? "اطلاعات کلی" : "۱ · اطلاعات کلی"}>
      <Field label="نام گروه" error={tried && err.name}><input autoFocus className="inp" maxLength={120} value={f.name} placeholder="مثلاً: آلمان - پرسرعت" onChange={(e) => set("name")(e.target.value)} /></Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="سقف فروش گروه" error={tried && err.limit} hint="خالی = نامحدود"><NumInput value={f.sales_limit} onChange={set("sales_limit")} placeholder="نامحدود" suffix="اکانت" /></Field>
        <Field label="نام‌گذاری اکانت‌ها" hint={f.naming_mode === "custom" ? "مشتری هنگام خرید نام کاربری انتخاب می‌کند" : "نام کاربری به‌صورت خودکار ساخته می‌شود"}><Segmented label="نام‌گذاری" value={f.naming_mode} onChange={set("naming_mode")} options={[["automatic", "خودکار"], ["custom", "دلخواه"]]} /></Field>
      </div>
    </Section>
    <Section title={edit ? "نحوه‌ی انتخاب پنل" : "۲ · نحوه‌ی انتخاب پنل"}>
      <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="نحوه‌ی انتخاب پنل">{Object.entries(MODES).map(([k, [t, d, I]]) => <button key={k} type="button" role="radio" aria-checked={f.selection_mode === k} onClick={() => set("selection_mode")(k)} className={`card p-3 text-right transition ${f.selection_mode === k ? "!border-[var(--ac)] ring-2 ring-[color-mix(in_srgb,var(--ac)_20%,transparent)]" : "hover:-translate-y-0.5"}`}>
        <span className="grid h-8 w-8 place-items-center rounded-lg" style={tint(k === "automatic" ? "ok" : "in")}><I size={16} /></span><span className="mt-2 block text-sm font-extrabold">{t}</span><span className="mt-0.5 block text-[11px] leading-5 text-[var(--mu)]">{d}</span></button>)}</div>
    </Section>
    <Section title={edit ? "پنل‌های گروه" : "۳ · پنل‌های گروه"} hint={f.selection_mode === "manual" ? "ترتیب فهرست = اولویت انتخاب." : "در حالت خودکار انتخاب پنل‌ها اختیاری است."}>
      {f.panel_ids.length > 0 && <ol className="space-y-1.5">{f.panel_ids.map((id, i) => { const p = byId[id]; return <li key={id} className="flex items-center gap-2 rounded-xl border border-[var(--ln)] bg-[var(--sf2)] px-3 py-2">
        <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-[var(--mb)] text-[11px] font-extrabold">{num(i + 1)}</span><Dot s={hs(p)} />
        <div className="min-w-0 flex-1"><div className="truncate text-sm font-bold">{p?.name || "پنل حذف‌شده"}</div><div className="text-[11px] text-[var(--mu)]">{KIND[p?.kind] || p?.kind || ""}{p && !p.is_enabled ? " · غیرفعال" : ""}</div></div>
        <button type="button" className="btn btn-g !px-1.5" aria-label="بالاتر" disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp size={13} /></button>
        <button type="button" className="btn btn-g !px-1.5" aria-label="پایین‌تر" disabled={i === f.panel_ids.length - 1} onClick={() => move(i, 1)}><ArrowDown size={13} /></button>
        <button type="button" className="btn btn-g btn-d !px-1.5" aria-label="حذف از گروه" onClick={() => toggleP(id)}><X size={13} /></button></li>; })}</ol>}
      {tried && err.panels && <p className="text-[11px] text-[var(--bd)]">{err.panels}</p>}
      <div>
        <label className="relative block"><Search size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[var(--mu)]" /><input aria-label="جستجوی پنل" className="inp !pr-9" placeholder="افزودن پنل… (جستجو)" value={pq} onChange={(e) => setPq(e.target.value)} /></label>
        <div className="mt-2 max-h-52 space-y-1 overflow-y-auto">{!panels.length ? <p className="p-4 text-center text-xs text-[var(--mu)]">هنوز پنلی ساخته نشده؛ ابتدا از بخش «پنل‌ها» یک پنل اضافه کنید.</p>
          : !avail.length ? <p className="p-3 text-center text-xs text-[var(--mu)]">{pq ? "پنلی پیدا نشد" : "همه‌ی پنل‌ها به گروه اضافه شده‌اند"}</p>
          : avail.map((p) => <button key={p.id} type="button" onClick={() => toggleP(p.id)} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-right text-sm transition hover:bg-[var(--mb)]"><Dot s={hs(p)} /><span className="min-w-0 flex-1 truncate font-bold">{p.name}</span><span className="text-[11px] text-[var(--mu)]">{KIND[p.kind] || p.kind}{!p.is_enabled ? " · غیرفعال" : ""}</span><Plus size={14} className="text-[var(--ac)]" /></button>)}</div>
      </div>
      {edit && <p className="text-[11px] leading-5 text-[var(--mu)]">حذف یا تغییر ترتیب پنل‌ها، آمار فروش پنل‌های باقی‌مانده را حفظ می‌کند.</p>}
    </Section>
    <Section title={edit ? "وضعیت و دسترسی" : "۴ · وضعیت و دسترسی"}>
      <Toggle checked={f.is_enabled} onChange={set("is_enabled")} label="گروه فعال باشد" hint="گروه غیرفعال در فروشگاه و بات نمایش داده نمی‌شود." />
      <Toggle checked={f.reseller_enabled} onChange={set("reseller_enabled")} label="در دسترس نمایندگان" hint="خاموش = فقط فروشگاه اصلی از این گروه استفاده می‌کند." />
    </Section>
  </Drawer>;
}

export default function PanelGroupsView({ api, toast }) {
  const call = (p, o) => authFetch(api.base, p, o);
  const groups = useRows(call, API), panelsQ = useRows(call, "/api/v1/admin/panels");
  const [q, setQ] = useState(""), [filter, setFilter] = useState("all"), [drawer, setDrawer] = useState(null), [busy, setBusy] = useState(new Set());
  const alive = useAlive();
  const rows = groups.rows, panels = panelsQ.rows || [];
  const panelById = useMemo(() => Object.fromEntries(panels.map((p) => [p.id, p])), [panels]);
  const counts = useMemo(() => { const c = { all: 0, on: 0, off: 0, sold: 0 }; (rows || []).forEach((g) => { c.all++; g.is_enabled ? c.on++ : c.off++; c.sold += g.sold_count || 0; }); return c; }, [rows]);
  const shown = useMemo(() => (rows || []).filter((g) => (filter === "all" || (filter === "on" ? g.is_enabled : !g.is_enabled)) && g.name.toLowerCase().includes(q.trim().toLowerCase())), [rows, filter, q]);
  const editing = drawer && drawer !== "add" ? (rows || []).find((g) => g.id === drawer) : null;

  const save = async (f, group) => {
    const same = group && JSON.stringify(fromGroup(group).panel_ids) === JSON.stringify(f.panel_ids);
    const body = group ? { name: f.name, selection_mode: f.selection_mode, naming_mode: f.naming_mode, is_enabled: f.is_enabled, reseller_enabled: f.reseller_enabled, sales_limit: f.sales_limit, ...(same ? {} : { panel_ids: f.panel_ids }) } : f;
    const r = await call(group ? `${API}/${group.id}` : API, { method: group ? "PATCH" : "POST", body: JSON.stringify(body) });
    if (!r.ok) return errText(r, group ? "ذخیره تغییرات ناموفق بود" : "ساخت گروه ناموفق بود");
    setDrawer(null); toast(group ? "تغییرات گروه ذخیره شد" : "گروه پنل VPN ساخته شد"); await groups.load(); return "";
  };
  const toggle = async (g, next) => {
    if (!next && !(await confirmDialog(`«${g.name}» غیرفعال شود؟ تا فعال‌سازی مجدد برای فروش جدید استفاده نمی‌شود.`, { title: "غیرفعال‌سازی گروه", danger: true, ok: "غیرفعال‌سازی" }))) return;
    setBusy((s) => new Set(s).add(g.id));
    let ok = false; try { ok = (await call(`${API}/${g.id}`, { method: "PATCH", body: JSON.stringify({ is_enabled: next }) })).ok; } catch { /* network */ }
    if (alive.current) setBusy((s) => { const n = new Set(s); n.delete(g.id); return n; });
    toast(ok ? (next ? `«${g.name}» فعال شد` : `«${g.name}» غیرفعال شد`) : "تغییر وضعیت ناموفق بود"); if (ok) await groups.load();
  };

  return <div className="space-y-5">
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Stat label="همه گروه‌ها" value={counts.all} tone="in" Icon={Layers} active={filter === "all"} onClick={() => setFilter("all")} />
      <Stat label="فعال" value={counts.on} tone="ok" Icon={CheckCircle2} active={filter === "on"} onClick={() => setFilter(filter === "on" ? "all" : "on")} />
      <Stat label="غیرفعال" value={counts.off} tone="mu" Icon={PowerOff} active={filter === "off"} onClick={() => setFilter(filter === "off" ? "all" : "off")} />
      <div className="card flex items-center gap-3 p-4"><span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl" style={tint("wn")}><ShoppingBag size={19} /></span><span><span className="block text-2xl font-extrabold leading-none">{num(counts.sold)}</span><span className="mt-1 block text-xs text-[var(--mu)]">مجموع فروش گروه‌ها</span></span></div>
    </div>
    <div className="flex flex-wrap items-center gap-2">
      <label className="relative min-w-[12rem] flex-1 sm:max-w-xs"><Search size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[var(--mu)]" /><input aria-label="جستجوی گروه" className="inp !pr-9" placeholder="جستجوی نام گروه…" value={q} onChange={(e) => setQ(e.target.value)} /></label>
      <button className="btn mr-auto" onClick={() => setDrawer("add")}><Plus size={16} />افزودن گروه</button>
    </div>
    {groups.failed && <p role="alert" className="flex items-center gap-2 rounded-xl bg-[var(--bdb)] p-3 text-sm text-[var(--bd)]"><ShieldAlert size={16} />دریافت گروه‌ها ناموفق بود. <button className="font-extrabold underline" onClick={groups.load}>تلاش مجدد</button></p>}
    {rows === null ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="card skel h-52" />)}</div>
      : !shown.length ? <div className="card grid place-items-center gap-3 p-14 text-center"><span className="grid h-14 w-14 place-items-center rounded-2xl bg-[var(--mb)] text-[var(--mu)]"><Layers size={26} /></span>
        <h3 className="font-extrabold">{counts.all ? "گروهی با این فیلتر پیدا نشد" : "هنوز گروه پنلی ساخته نشده"}</h3>
        <p className="max-w-sm text-sm leading-7 text-[var(--mu)]">{counts.all ? "جستجو یا فیلتر را تغییر دهید." : "گروه پنل مشخص می‌کند اکانت‌های فروشی روی کدام پنل‌ها ساخته شوند."}</p>
        {!counts.all && <button className="btn" onClick={() => setDrawer("add")}><Plus size={16} />ساخت اولین گروه</button>}</div>
      : <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{shown.map((g) => <GroupCard key={g.id} g={g} panelById={panelById} busy={busy.has(g.id)} onEdit={(x) => setDrawer(x.id)} onToggle={toggle} />)}</div>}
    {drawer && (drawer === "add" || editing) && <GroupDrawer key={drawer} group={editing} panels={panels} onClose={() => setDrawer(null)} onSubmit={save} />}
  </div>;
}
