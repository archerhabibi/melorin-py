import { useEffect, useMemo, useRef, useState } from "react";
import { authFetch } from "./api.js";
import { Badge, confirmDialog } from "./ui.jsx";
import { AlertTriangle, Boxes, CheckCircle2, Clock, Infinity as Inf, LayoutGrid, List, Pencil, PowerOff, Plus, Save, Search, ShieldAlert, Smartphone, Store, Tag, Wallet, X, Zap } from "lucide-react";
import { Drawer, Field, NumInput, Section, Segmented, Stat, Switch, Toggle, errText, num, tint, useAlive, useRows } from "./kit.jsx";

const API = "/api/v1/admin/products";
const CUR = { IRT: "تومان", USD: "دلار", USDT: "تتر", XTR: "ستاره" };
const price = (n, c) => `${num(n)} ${CUR[c] || c}`;
const dur = (d) => (d % 30 === 0 && d >= 30 ? `${num(d / 30)} ماهه` : `${num(d)} روزه`);
const gb = (n) => (n ? `${num(n)} گیگ` : "نامحدود");
const pct = (a, b) => (b > 0 ? Math.round(((a - b) / b) * 100) : null);

const EMPTY = { code: "", name: "", description: "", category: "", duration_days: "30", unlimited_traffic: false, traffic_gb: "", unlimited_devices: true, max_devices: "", currency: "IRT", main_price: "", reseller_price: "", is_active: true, is_test: false, default_panel_group_id: "" };
const fromProduct = (p) => ({ code: p.code, name: p.name, description: p.description || "", category: p.category || "", duration_days: String(p.duration_days), unlimited_traffic: !p.traffic_gb, traffic_gb: p.traffic_gb ? String(p.traffic_gb) : "", unlimited_devices: !p.max_devices, max_devices: p.max_devices ? String(p.max_devices) : "", currency: p.currency, main_price: String(p.main_price), reseller_price: String(p.reseller_price), is_active: p.is_active, is_test: !!p.is_test, default_panel_group_id: p.default_panel_group_id || "" });
const payload = (f) => ({ code: f.code.trim(), name: f.name.trim(), description: f.description.trim() || null, category: f.category.trim() || null, duration_days: +f.duration_days, traffic_gb: f.unlimited_traffic ? 0 : +f.traffic_gb, max_devices: f.unlimited_devices ? null : +f.max_devices, currency: f.currency, main_price: +f.main_price, reseller_price: +f.reseller_price, is_test: f.is_test, default_panel_group_id: f.default_panel_group_id || null });
function validate(f) {
  const e = {};
  if (!/^[A-Za-z0-9_-]{2,50}$/.test(f.code.trim())) e.code = "کد ۲ تا ۵۰ نویسه؛ فقط حروف انگلیسی، عدد، - و _";
  if (f.name.trim().length < 2) e.name = "نام محصول را وارد کنید";
  if (!(+f.duration_days > 0)) e.duration_days = "مدت باید حداقل ۱ روز باشد";
  if (!f.unlimited_traffic && !(+f.traffic_gb > 0)) e.traffic_gb = "حجم را وارد کنید یا «نامحدود» را بزنید";
  if (!f.unlimited_devices && !(+f.max_devices > 0)) e.max_devices = "تعداد دستگاه را وارد کنید";
  if (f.main_price === "") e.main_price = "قیمت فروشگاه اصلی را وارد کنید";
  if (f.reseller_price === "") e.reseller_price = "قیمت نماینده را وارد کنید";
  return e;
}

function PriceHint({ main, res, cur }) {
  if (main === "" || res === "") return null;
  const m = +main, r = +res, d = m - r;
  if (r > m) return <p className="flex items-start gap-2 rounded-lg bg-[var(--wnb)] p-3 text-xs leading-6 text-[var(--wn)]"><AlertTriangle size={15} className="mt-1 shrink-0" />قیمت نماینده از قیمت فروشگاه اصلی بیشتر است؛ مطمئن هستید؟</p>;
  return <p className="rounded-lg bg-[var(--sf2)] px-3 py-2 text-xs leading-6 text-[var(--mu)]">نماینده <b className="text-[var(--tx)]">{pct(m, r) === null ? "—" : `${num(Math.abs(pct(m, r)))}٪`}</b> ارزان‌تر از فروشگاه اصلی می‌خرد ({price(d, cur)} تفاوت).</p>;
}

function StoreAvailability({ product, stores, call, toast }) {
  const [storeId, setStoreId] = useState(""); const [enabled, setEnabled] = useState(true), [listed, setListed] = useState(true), [cp, setCp] = useState(""); const [busy, setBusy] = useState(false);
  const store = stores.find((s) => s.id === storeId);
  useEffect(() => { const m = stores.find((s) => s.kind === "main") || stores[0]; if (m && !storeId) setStoreId(m.id); }, [stores]); // eslint-disable-line
  useEffect(() => { setCp(store?.kind === "reseller" ? String(product.reseller_price) : ""); }, [storeId, product.id]); // eslint-disable-line
  if (!stores.length) return null;
  const publish = async () => {
    setBusy(true);
    const r = await call(`${API}/${product.id}/availability`, { method: "POST", body: JSON.stringify({ store_id: storeId, enabled, listed, customer_price: store?.kind === "reseller" && cp !== "" ? Number(cp) : null }) });
    setBusy(false); toast(r.ok ? `«${product.name}» در «${store?.name}» ذخیره شد` : "ذخیره وضعیت در فروشگاه ناموفق بود");
  };
  return <Section title="انتشار در فروشگاه‌ها" hint="محصول تا زمانی که برای یک فروشگاه فعال نشود در سایت و بات آن دیده نمی‌شود. این بخش جدا از دکمه‌ی ذخیره‌ی محصول عمل می‌کند.">
    <div className="grid gap-3 sm:grid-cols-2">
      <Field label="فروشگاه"><select className="inp" value={storeId} onChange={(e) => setStoreId(e.target.value)}>{stores.map((s) => <option key={s.id} value={s.id}>{s.name} · {s.kind === "main" ? "اصلی" : "نماینده"}</option>)}</select></Field>
      {store?.kind === "reseller" && <Field label="قیمت فروش به مشتری"><NumInput value={cp} onChange={setCp} suffix={CUR[product.currency]} /></Field>}
    </div>
    <div className="flex flex-wrap gap-6"><Toggle checked={enabled} onChange={setEnabled} label="قابل فروش" /><Toggle checked={listed} onChange={setListed} label="نمایش در کاتالوگ" /></div>
    <button className="btn btn-g !py-2 !text-sm" disabled={busy || !storeId} onClick={publish}><Store size={14} />{busy ? "در حال ذخیره…" : "ذخیره وضعیت فروشگاه"}</button>
  </Section>;
}

function ProductDrawer({ product, stores, call, toast, onClose, onSubmit }) {
  const edit = !!product;
  const [f, setF] = useState(() => (product ? fromProduct(product) : EMPTY)); const base = useRef(JSON.stringify(f));
  const [tried, setTried] = useState(false), [busy, setBusy] = useState(false), [srv, setSrv] = useState("");
  const [groups, setGroups] = useState([]);
  useEffect(() => { let on = true; call("/api/v1/admin/panel-groups").then((r) => (r.ok ? r.json() : [])).then((g) => { if (on) setGroups(Array.isArray(g) ? g : []); }).catch(() => {}); return () => { on = false; }; }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k) => (v) => { setSrv(""); setF((x) => ({ ...x, [k]: v })); };
  const err = useMemo(() => validate(f), [f]); const dirty = JSON.stringify(f) !== base.current;
  const submit = async () => { setTried(true); if (Object.keys(err).length) return; setBusy(true); const m = await onSubmit(payload(f), f.is_active, product); setBusy(false); if (m) setSrv(m); };
  const show = (k) => tried && err[k];
  return <Drawer title={edit ? `ویرایش «${product.name}»` : "افزودن محصول VPN"} subtitle={edit ? `کد ${product.code}` : "مشخصات و قیمت پلن جدید"} icon={<span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint("ok")}><Boxes size={20} /></span>} dirty={dirty} busy={busy} onClose={onClose} error={srv}
    footer={<button className="btn !py-2 !text-sm" disabled={busy} onClick={submit}><Save size={15} />{busy ? "در حال ذخیره…" : edit ? "ذخیره تغییرات" : "ساخت محصول"}</button>}>
    <Section title={edit ? "اطلاعات" : "۱ · اطلاعات"}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="نام محصول" error={show("name")}><input autoFocus className="inp" maxLength={200} placeholder="مثلاً: ۳۰ روزه ۵۰ گیگ" value={f.name} onChange={(e) => set("name")(e.target.value)} /></Field>
        <Field label="کد محصول" error={show("code")} hint={edit ? "تغییر کد روی اتصال‌های بیرونی (API/بات) اثر می‌گذارد." : "یکتا و انگلیسی، مثلاً vpn-30d-50g"}><input dir="ltr" spellCheck={false} className="inp font-mono" maxLength={50} value={f.code} onChange={(e) => set("code")(e.target.value)} /></Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="دسته‌بندی" hint="اختیاری؛ برای گروه‌بندی در فروشگاه"><input className="inp" maxLength={100} value={f.category} onChange={(e) => set("category")(e.target.value)} /></Field>
        <Field label="توضیحات" hint="اختیاری"><input className="inp" value={f.description} onChange={(e) => set("description")(e.target.value)} /></Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="گروه پنل پیش‌فرض" hint="هسته برای همه‌ی کانال‌ها (ربات و سایت) از همین گروه اکانت می‌سازد؛ فقط گروه‌های فعال با انتخاب خودکار">
          <select className="inp" value={f.default_panel_group_id} onChange={(e) => set("default_panel_group_id")(e.target.value)}>
            <option value="">بدون گروه (انتخاب مستقیم سرور)</option>
            {groups.filter((g) => g.id === f.default_panel_group_id || (g.is_enabled && g.selection_mode === "automatic")).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
          </select>
        </Field>
      </div>
    </Section>
    <Section title={edit ? "مشخصات پلن" : "۲ · مشخصات پلن"}>
      <Field label="مدت اعتبار" error={show("duration_days")}>
        <div className="space-y-2"><div className="flex flex-wrap gap-1.5">{[7, 30, 60, 90, 180, 365].map((d) => <button key={d} type="button" onClick={() => set("duration_days")(String(d))} className={`btn btn-g ${+f.duration_days === d ? "!border-[var(--ac)] !text-[var(--ac)]" : ""}`}>{dur(d)}</button>)}</div>
          <NumInput value={f.duration_days} onChange={set("duration_days")} suffix="روز" /></div></Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="حجم ترافیک" error={show("traffic_gb")}><div className="space-y-2"><NumInput value={f.unlimited_traffic ? "" : f.traffic_gb} disabled={f.unlimited_traffic} placeholder={f.unlimited_traffic ? "نامحدود" : ""} onChange={set("traffic_gb")} suffix="گیگ" /><Toggle checked={f.unlimited_traffic} onChange={set("unlimited_traffic")} label="نامحدود" /></div></Field>
        <Field label="تعداد دستگاه هم‌زمان" error={show("max_devices")}><div className="space-y-2"><NumInput value={f.unlimited_devices ? "" : f.max_devices} disabled={f.unlimited_devices} placeholder={f.unlimited_devices ? "بدون محدودیت" : ""} onChange={set("max_devices")} suffix="دستگاه" /><Toggle checked={f.unlimited_devices} onChange={set("unlimited_devices")} label="بدون محدودیت" /></div></Field>
      </div>
    </Section>
    <Section title={edit ? "قیمت‌گذاری" : "۳ · قیمت‌گذاری"}>
      <Field label="واحد پول"><Segmented label="واحد پول" value={f.currency} onChange={set("currency")} options={Object.entries(CUR)} /></Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="قیمت فروشگاه اصلی" error={show("main_price")}><NumInput value={f.main_price} onChange={set("main_price")} suffix={CUR[f.currency]} /></Field>
        <Field label="قیمت نماینده (قیمت تمام‌شده)" error={show("reseller_price")}><NumInput value={f.reseller_price} onChange={set("reseller_price")} suffix={CUR[f.currency]} /></Field>
      </div>
      <PriceHint main={f.main_price} res={f.reseller_price} cur={f.currency} />
    </Section>
    <Section title={edit ? "وضعیت" : "۴ · وضعیت"}>
      <Toggle checked={f.is_active} onChange={set("is_active")} label="محصول فعال باشد" hint="محصول غیرفعال برای خرید جدید نمایش داده نمی‌شود." />
      <Toggle checked={f.is_test} onChange={set("is_test")} label="محصول آزمایشی (تست)" hint="برای تست‌ها و اکانت‌های آزمایشی." />
    </Section>
    {edit && <StoreAvailability product={product} stores={stores} call={call} toast={toast} />}
  </Drawer>;
}

function ProductCard({ p, busy, onEdit, onToggle }) {
  const d = pct(p.main_price, p.reseller_price);
  return <article className="card rise flex flex-col gap-4 p-4">
    <div className={`flex items-start gap-3 ${p.is_active ? "" : "opacity-55"}`}>
      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint(p.is_test ? "wn" : "ok")}><Zap size={20} /></span>
      <div className="min-w-0 flex-1"><h3 className="truncate font-extrabold" title={p.name}>{p.name}</h3><p dir="ltr" className="truncate text-right font-mono text-[11px] text-[var(--mu)]">{p.code}</p></div>
      <div className="flex flex-col items-end gap-1"><Badge s={p.is_active ? "active" : "disabled"} />{p.is_test && <span className="badge b-wn">تست</span>}</div>
    </div>
    <div className={`grid grid-cols-3 gap-2 text-center ${p.is_active ? "" : "opacity-55"}`}>{[[Clock, dur(p.duration_days)], [p.traffic_gb ? Zap : Inf, gb(p.traffic_gb)], [Smartphone, p.max_devices ? `${num(p.max_devices)} دستگاه` : "نامحدود"]].map(([I, t], i) => <div key={i} className="rounded-lg bg-[var(--sf2)] px-1 py-2"><I size={14} className="mx-auto text-[var(--mu)]" /><div className="mt-1 text-[11px] font-bold">{t}</div></div>)}</div>
    <div className={`rounded-xl border border-[var(--ln)] p-3 ${p.is_active ? "" : "opacity-55"}`}>
      <div className="flex items-baseline justify-between"><span className="text-[11px] text-[var(--mu)]">فروشگاه اصلی</span><b className="text-lg font-extrabold">{price(p.main_price, p.currency)}</b></div>
      <div className="mt-1 flex items-baseline justify-between"><span className="text-[11px] text-[var(--mu)]">نماینده{d > 0 ? ` · ${num(d)}٪ ارزان‌تر` : ""}</span><span className="text-sm font-bold">{price(p.reseller_price, p.currency)}</span></div>
    </div>
    <div className="mt-auto flex items-center justify-between gap-2 border-t border-[var(--ln)] pt-3">
      <label className="flex cursor-pointer items-center gap-2 text-xs font-bold"><Switch checked={p.is_active} disabled={busy} onChange={(v) => onToggle(p, v)} label={`فعال‌سازی ${p.name}`} />{p.is_active ? "فعال" : "غیرفعال"}</label>
      <button className="btn btn-g" onClick={() => onEdit(p)}><Pencil size={13} />ویرایش</button>
    </div>
  </article>;
}

function ProductTable({ rows, busy, onEdit, onToggle, quick, draft, setDraft }) {
  const cell = (p, k) => quick
    ? <div className="w-36"><NumInput aria-label={`${k === "main_price" ? "قیمت اصلی" : "قیمت نماینده"} ${p.name}`} value={draft[p.id]?.[k] ?? String(p[k])} onChange={(v) => setDraft((d) => ({ ...d, [p.id]: { ...(d[p.id] || {}), [k]: v } }))} /></div>
    : <span className="font-semibold">{price(p[k], p.currency)}</span>;
  return <section className="card rise overflow-hidden"><div className="overflow-auto"><table className="tbl min-w-[860px]"><thead><tr>{["محصول", "مدت", "ترافیک", "دستگاه", "قیمت اصلی", "قیمت نماینده", "وضعیت", ""].map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
    <tbody>{rows.map((p) => { const dirty = quick && draft[p.id] && (draft[p.id].main_price !== undefined && draft[p.id].main_price !== String(p.main_price) || draft[p.id].reseller_price !== undefined && draft[p.id].reseller_price !== String(p.reseller_price));
      return <tr key={p.id} className={`${p.is_active ? "" : "opacity-60"} ${dirty ? "!bg-[var(--wnb)]" : ""}`}>
        <td><div className="font-bold">{p.name}{p.is_test && <span className="badge b-wn mr-2">تست</span>}</div><div dir="ltr" className="text-right font-mono text-[11px] text-[var(--mu)]">{p.code}</div></td>
        <td>{dur(p.duration_days)}</td><td>{gb(p.traffic_gb)}</td><td>{p.max_devices ? num(p.max_devices) : "∞"}</td>
        <td>{cell(p, "main_price")}</td><td>{cell(p, "reseller_price")}</td>
        <td><div className="flex items-center gap-2"><Switch checked={p.is_active} disabled={busy.has(p.id)} onChange={(v) => onToggle(p, v)} label={`فعال‌سازی ${p.name}`} /></div></td>
        <td><button className="btn btn-g" onClick={() => onEdit(p)}><Pencil size={13} />ویرایش</button></td></tr>; })}</tbody></table></div></section>;
}

export default function ProductsView({ api, toast }) {
  const call = (p, o) => authFetch(api.base, p, o);
  const prods = useRows(call, API), storesQ = useRows(call, "/api/v1/admin/stores");
  const [q, setQ] = useState(""), [filter, setFilter] = useState("all"), [layout, setLayout] = useState("grid"), [drawer, setDrawer] = useState(null), [busy, setBusy] = useState(new Set());
  const [quick, setQuick] = useState(false), [draft, setDraft] = useState({}), [saving, setSaving] = useState(false);
  const alive = useAlive(); const rows = prods.rows;
  const counts = useMemo(() => { const c = { all: 0, on: 0, off: 0, test: 0 }; (rows || []).forEach((p) => { c.all++; p.is_active ? c.on++ : c.off++; if (p.is_test) c.test++; }); return c; }, [rows]);
  const shown = useMemo(() => (rows || []).filter((p) => (filter === "all" || (filter === "on" ? p.is_active : filter === "off" ? !p.is_active : p.is_test)) && `${p.name} ${p.code} ${p.category || ""}`.toLowerCase().includes(q.trim().toLowerCase())), [rows, filter, q]);
  const editing = drawer && drawer !== "add" ? (rows || []).find((p) => p.id === drawer) : null;
  const table = layout === "table" || quick;

  const save = async (body, active, product) => {
    const r = await call(product ? `${API}/${product.id}` : API, { method: product ? "PATCH" : "POST", body: JSON.stringify(product ? { ...body, is_active: active } : body) });
    if (!r.ok) return errText(r, product ? "ذخیره تغییرات ناموفق بود" : "ساخت محصول ناموفق بود");
    if (!product && !active) { const c = await r.json().catch(() => null); if (c?.id) await call(`${API}/${c.id}`, { method: "PATCH", body: JSON.stringify({ is_active: false }) }); }
    setDrawer(null); toast(product ? "تغییرات محصول ذخیره شد" : "محصول ساخته شد"); await prods.load(); return "";
  };
  const toggle = async (p, next) => {
    if (!next && !(await confirmDialog(`«${p.name}» غیرفعال شود؟ دیگر برای خرید جدید نمایش داده نمی‌شود.`, { title: "غیرفعال‌سازی محصول", danger: true, ok: "غیرفعال‌سازی" }))) return;
    setBusy((s) => new Set(s).add(p.id));
    let ok = false; try { ok = (await call(`${API}/${p.id}`, { method: "PATCH", body: JSON.stringify({ is_active: next }) })).ok; } catch { /* network */ }
    if (alive.current) setBusy((s) => { const n = new Set(s); n.delete(p.id); return n; });
    toast(ok ? (next ? `«${p.name}» فعال شد` : `«${p.name}» غیرفعال شد`) : "تغییر وضعیت ناموفق بود"); if (ok) await prods.load();
  };
  const changes = (rows || []).flatMap((p) => { const d = draft[p.id]; if (!d) return []; const b = {}; if (d.main_price !== undefined && d.main_price !== "" && d.main_price !== String(p.main_price)) b.main_price = +d.main_price; if (d.reseller_price !== undefined && d.reseller_price !== "" && d.reseller_price !== String(p.reseller_price)) b.reseller_price = +d.reseller_price; return Object.keys(b).length ? [[p, b]] : []; });
  const endQuick = async () => { if (changes.length && !(await confirmDialog("تغییرات قیمت ذخیره‌نشده از بین می‌رود. خارج می‌شوید؟", { title: "خروج از ویرایش سریع", danger: true, ok: "خروج" }))) return; setDraft({}); setQuick(false); };
  const saveQuick = async () => {
    if (!(await confirmDialog(`قیمت ${num(changes.length)} محصول به‌روزرسانی شود؟ قیمت جدید فوراً در فروشگاه اعمال می‌شود.`, { title: "ذخیره‌ی قیمت‌ها", ok: "ذخیره" }))) return;
    setSaving(true); let bad = 0;
    for (const [p, b] of changes) { try { if (!(await call(`${API}/${p.id}`, { method: "PATCH", body: JSON.stringify(b) })).ok) bad++; } catch { bad++; } }
    if (alive.current) setSaving(false);
    toast(bad ? `${num(bad)} مورد از ${num(changes.length)} ذخیره نشد` : "قیمت‌ها به‌روزرسانی شد"); await prods.load(); if (!bad) { setDraft({}); setQuick(false); }
  };

  return <div className="space-y-5">
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Stat label="همه محصولات" value={counts.all} tone="in" Icon={Boxes} active={filter === "all"} onClick={() => setFilter("all")} />
      <Stat label="فعال" value={counts.on} tone="ok" Icon={CheckCircle2} active={filter === "on"} onClick={() => setFilter(filter === "on" ? "all" : "on")} />
      <Stat label="غیرفعال" value={counts.off} tone="mu" Icon={PowerOff} active={filter === "off"} onClick={() => setFilter(filter === "off" ? "all" : "off")} />
      <Stat label="آزمایشی" value={counts.test} tone="wn" Icon={Tag} active={filter === "test"} onClick={() => setFilter(filter === "test" ? "all" : "test")} />
    </div>
    <div className="flex flex-wrap items-center gap-2">
      <label className="relative min-w-[12rem] flex-1 sm:max-w-xs"><Search size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[var(--mu)]" /><input aria-label="جستجوی محصول" className="inp !pr-9" placeholder="جستجوی نام، کد یا دسته…" value={q} onChange={(e) => setQ(e.target.value)} /></label>
      <div className="pv-seg" role="group" aria-label="نحوه نمایش"><button type="button" className={!table ? "on" : ""} aria-label="کارتی" disabled={quick} onClick={() => setLayout("grid")}><LayoutGrid size={14} /></button><button type="button" className={table ? "on" : ""} aria-label="جدولی" onClick={() => setLayout("table")}><List size={14} /></button></div>
      <div className="mr-auto flex flex-wrap items-center gap-2">
        {quick ? <><span className="text-xs text-[var(--mu)]">{changes.length ? `${num(changes.length)} تغییر` : "قیمت‌ها را مستقیم در جدول ویرایش کنید"}</span>
          <button className="btn !py-2 !text-sm" disabled={!changes.length || saving} onClick={saveQuick}><Save size={14} />{saving ? "در حال ذخیره…" : "ذخیره قیمت‌ها"}</button><button className="btn btn-g !py-2 !text-sm" disabled={saving} onClick={endQuick}><X size={14} />خروج</button></>
          : <><button className="btn btn-g !py-2 !text-sm" disabled={!counts.all} onClick={() => { setLayout("table"); setQuick(true); }}><Wallet size={14} />ویرایش سریع قیمت‌ها</button><button className="btn" onClick={() => setDrawer("add")}><Plus size={16} />افزودن محصول</button></>}
      </div>
    </div>
    {prods.failed && <p role="alert" className="flex items-center gap-2 rounded-xl bg-[var(--bdb)] p-3 text-sm text-[var(--bd)]"><ShieldAlert size={16} />دریافت محصولات ناموفق بود. <button className="font-extrabold underline" onClick={prods.load}>تلاش مجدد</button></p>}
    {rows === null ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="card skel h-60" />)}</div>
      : !shown.length ? <div className="card grid place-items-center gap-3 p-14 text-center"><span className="grid h-14 w-14 place-items-center rounded-2xl bg-[var(--mb)] text-[var(--mu)]"><Boxes size={26} /></span>
        <h3 className="font-extrabold">{counts.all ? "محصولی با این فیلتر پیدا نشد" : "هنوز محصولی تعریف نشده"}</h3>
        <p className="max-w-sm text-sm leading-7 text-[var(--mu)]">{counts.all ? "جستجو یا فیلتر را تغییر دهید." : "هر محصول یک پلن قابل فروش با مدت، حجم و قیمت مشخص است."}</p>
        {!counts.all && <button className="btn" onClick={() => setDrawer("add")}><Plus size={16} />ساخت اولین محصول</button>}</div>
      : table ? <ProductTable rows={shown} busy={busy} onEdit={(x) => setDrawer(x.id)} onToggle={toggle} quick={quick} draft={draft} setDraft={setDraft} />
      : <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{shown.map((p) => <ProductCard key={p.id} p={p} busy={busy.has(p.id)} onEdit={(x) => setDrawer(x.id)} onToggle={toggle} />)}</div>}
    {drawer && (drawer === "add" || editing) && <ProductDrawer key={drawer} product={editing} stores={storesQ.rows || []} call={call} toast={toast} onClose={() => setDrawer(null)} onSubmit={save} />}
  </div>;
}
