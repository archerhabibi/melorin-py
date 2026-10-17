import { useEffect, useMemo, useRef, useState } from "react";
import { authFetch } from "./api.js";
import { Badge, confirmDialog } from "./ui.jsx";
import { AlertTriangle, Boxes, ChevronDown, Layers, ServerCog, CheckCircle2, Clock, Infinity as Inf, LayoutGrid, List, Pencil, PowerOff, Plus, Save, Search, ShieldAlert, Smartphone, Store, Tag, Wallet, X, Zap } from "lucide-react";
import { Drawer, Empty, ErrorBar, Field, KpiBar, NumInput, Paginator, Pills, SearchBox, Section, Segmented, SortSelect, Stat, Switch, Toggle, ViewToggle, DeleteButton, errText, num, removeEntity, tint, useAlive, useRows } from "./kit.jsx"; // #4
import { Dot, InfraChain, RelChip, Warn, clearParam, health, infraHref, useHashParams, useInfra } from "./infra.jsx";

const API = "/api/v1/admin/products";
const CUR = { IRT: "تومان", USD: "دلار", USDT: "تتر", XTR: "ستاره" };
const price = (n, c) => `${num(n)} ${CUR[c] || c}`;
const dur = (d) => (d % 30 === 0 && d >= 30 ? `${num(d / 30)} ماهه` : `${num(d)} روزه`);
const gb = (n) => (n ? `${num(n)} گیگ` : "نامحدود");

// A product here is only the plan itself: specs + the store's own price. The cooperation price (what resellers pay),
// the per-bundle price and "hide in this bundle" live on the bundles screen. A package is sold in every bundle by default.
const EMPTY = { code: "", name: "", description: "", category: "", duration_days: "30", unlimited_traffic: false, traffic_gb: "", unlimited_devices: true, max_devices: "", currency: "IRT", main_price: "", is_active: true, reseller_enabled: true, is_test: false };
const fromProduct = (p) => ({ code: p.code, name: p.name, description: p.description || "", category: p.category || "", duration_days: String(p.duration_days), unlimited_traffic: !p.traffic_gb, traffic_gb: p.traffic_gb ? String(p.traffic_gb) : "", unlimited_devices: !p.max_devices, max_devices: p.max_devices ? String(p.max_devices) : "", currency: p.currency, main_price: String(p.main_price), is_active: p.is_active, reseller_enabled: p.reseller_enabled !== false, is_test: !!p.is_test });
const payload = (f) => ({ code: f.code.trim(), name: f.name.trim(), description: f.description.trim() || null, category: f.category.trim() || null, duration_days: +f.duration_days, traffic_gb: f.unlimited_traffic ? 0 : +f.traffic_gb, max_devices: f.unlimited_devices ? null : +f.max_devices, currency: f.currency, main_price: +f.main_price, is_test: f.is_test, reseller_enabled: f.reseller_enabled });
function validate(f) {
  const e = {};
  if (!/^[A-Za-z0-9_-]{2,50}$/.test(f.code.trim())) e.code = "کد ۲ تا ۵۰ نویسه؛ فقط حروف انگلیسی، عدد، - و _";
  if (f.name.trim().length < 2) e.name = "نام محصول را وارد کنید";
  if (!(+f.duration_days > 0)) e.duration_days = "مدت باید حداقل ۱ روز باشد";
  if (!f.unlimited_traffic && !(+f.traffic_gb > 0)) e.traffic_gb = "حجم را وارد کنید یا «نامحدود» را بزنید";
  if (!f.unlimited_devices && !(+f.max_devices > 0)) e.max_devices = "تعداد دستگاه را وارد کنید";
  if (f.main_price === "") e.main_price = "قیمت فروشگاه را وارد کنید";
  return e;
}

/** One line: in how many bundles the package is sold and whether a server can take it (or why not). */
function Route({ p, idx }) {
  const r = idx.reach(p), n = (r.groups || []).filter((g) => g.is_enabled).length;
  if (!r.ok) return <p className="flex items-start gap-1.5 text-[11px] font-bold leading-5 text-[var(--bd)]"><AlertTriangle size={12} className="mt-0.5 shrink-0" />{r.issue}</p>;
  return <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-[var(--mu)]">
    <Layers size={12} />در {num(n)} بسته فروش
    <span>·</span>
    <a href={infraHref("panels", { product: p.code })} className="inline-flex items-center gap-1 font-bold hover:text-[var(--ac)]"><ServerCog size={12} />{num(r.live.length)} سرور آماده · {num(r.free)} ظرفیت آزاد</a>
  </div>;
}

function ProductDrawer({ product, products, hasResellers, onClose, onSubmit, onDelete }) {
  const edit = !!product;
  const taken = useMemo(() => new Set((products || []).filter((x) => x.id !== product?.id).map((x) => x.code)), [products, product]);
  const suggestCode = (f) => {
    const base = `vpn-${+f.duration_days || 0}d-${f.unlimited_traffic ? "unl" : `${+f.traffic_gb || 0}g`}`;
    let code = base, n = 2; while (taken.has(code)) code = `${base}-${n++}`;
    return code;
  };
  const [f, setF] = useState(() => (product ? fromProduct(product) : { ...EMPTY, code: suggestCode(EMPTY) })); const base = useRef(JSON.stringify(f));
  const [tried, setTried] = useState(false), [busy, setBusy] = useState(false), [srv, setSrv] = useState("");
  const [codeTouched, setCodeTouched] = useState(edit), [more, setMore] = useState(false);
  const set = (k) => (v) => { setSrv(""); setF((x) => ({ ...x, [k]: v })); };
  // New product: the code follows the plan (duration + traffic) until the admin edits it by hand.
  useEffect(() => { if (!edit && !codeTouched) setF((x) => ({ ...x, code: suggestCode(x) })); }, [f.duration_days, f.traffic_gb, f.unlimited_traffic, codeTouched, edit, taken]); // eslint-disable-line react-hooks/exhaustive-deps
  const err = useMemo(() => validate(f), [f]); const dirty = JSON.stringify(f) !== base.current;
  const submit = async () => { setTried(true); if (Object.keys(err).length) { if (err.code) setMore(true); return; } setBusy(true); const m = await onSubmit(payload(f), f.is_active, product); setBusy(false); if (m) setSrv(m); };
  const show = (k) => tried && err[k];
  return <Drawer title={edit ? `ویرایش «${product.name}»` : "افزودن محصول"} subtitle={edit ? `کد ${product.code}` : "مدت، حجم و قیمت فروشگاه"} icon={<span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint("ok")}><Boxes size={20} /></span>} dirty={dirty} busy={busy} onClose={onClose} error={srv}
    footer={<button className="btn !py-2 !text-sm" disabled={busy} onClick={submit}><Save size={15} />{busy ? "در حال ذخیره…" : edit ? "ذخیره تغییرات" : "ساخت محصول"}</button>} danger={edit && <DeleteButton label="حذف محصول" busy={busy} onClick={() => onDelete(product)} />}>
    <Section title="مشخصات">
      <Field label="نام محصول" error={show("name")}><input autoFocus className="inp" maxLength={200} placeholder="مثلاً: ۳۰ روزه ۵۰ گیگ" value={f.name} onChange={(e) => set("name")(e.target.value)} /></Field>
      <Field label="مدت اعتبار" error={show("duration_days")}>
        <div className="space-y-2"><div className="flex flex-wrap gap-1.5">{[7, 30, 60, 90, 180, 365].map((d) => <button key={d} type="button" onClick={() => set("duration_days")(String(d))} className={`btn btn-g ${+f.duration_days === d ? "!border-[var(--ac)] !text-[var(--ac)]" : ""}`}>{dur(d)}</button>)}</div>
          <NumInput value={f.duration_days} onChange={set("duration_days")} suffix="روز" /></div></Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="حجم ترافیک" error={show("traffic_gb")}><div className="space-y-2"><NumInput value={f.unlimited_traffic ? "" : f.traffic_gb} disabled={f.unlimited_traffic} placeholder={f.unlimited_traffic ? "نامحدود" : ""} onChange={set("traffic_gb")} suffix="گیگ" /><Toggle checked={f.unlimited_traffic} onChange={set("unlimited_traffic")} label="نامحدود" /></div></Field>
        <Field label="تعداد دستگاه هم‌زمان" error={show("max_devices")}><div className="space-y-2"><NumInput value={f.unlimited_devices ? "" : f.max_devices} disabled={f.unlimited_devices} placeholder={f.unlimited_devices ? "بدون محدودیت" : ""} onChange={set("max_devices")} suffix="دستگاه" /><Toggle checked={f.unlimited_devices} onChange={set("unlimited_devices")} label="بدون محدودیت" /></div></Field>
      </div>
    </Section>
    <Section title="قیمت فروشگاه" hint={hasResellers ? "قیمت نماینده و قیمت هر بسته از صفحه‌ی «بسته‌های فروش» تنظیم می‌شود؛ قیمت فروش هر نماینده را خودش تعیین می‌کند." : "قیمت هر بسته را هم می‌توانید از صفحه‌ی «بسته‌های فروش» جدا تنظیم کنید."}>
      <div className="grid gap-4 sm:grid-cols-[auto_1fr]">
        <Field label="واحد پول"><Segmented label="واحد پول" value={f.currency} onChange={set("currency")} options={Object.entries(CUR)} /></Field>
        <Field label="قیمت فروشگاه" error={show("main_price")}><NumInput value={f.main_price} onChange={set("main_price")} suffix={CUR[f.currency]} /></Field>
      </div>
    </Section>
    <Section title="وضعیت" hint="این محصول به‌صورت پیش‌فرض در همه‌ی بسته‌های فروش فعال است. هر بسته را می‌توانید از صفحه‌ی همان بسته پنهان کنید.">
      <Toggle checked={f.is_active} onChange={set("is_active")} label="فعال در فروشگاه اصلی" hint={hasResellers ? "با غیرفعال‌کردن، برای نمایندگان هم نمایش داده نمی‌شود." : "محصول غیرفعال برای خرید جدید نمایش داده نمی‌شود."} />
      {hasResellers && <div className={f.is_active ? "" : "pointer-events-none opacity-50"}><Toggle checked={f.is_active && f.reseller_enabled} onChange={set("reseller_enabled")} label="فعال برای نمایندگان" hint={f.is_active ? "خاموش = فقط فروشگاه اصلی این محصول را می‌فروشد." : "ابتدا محصول را در فروشگاه اصلی فعال کنید."} /></div>}
    </Section>
    <section>
      <button type="button" className="flex items-center gap-1.5 text-xs font-bold text-[var(--mu)]" aria-expanded={more} onClick={() => setMore(!more)}><ChevronDown size={14} className={more ? "" : "-rotate-90"} />کد، دسته‌بندی و توضیح<span dir="ltr" className="font-mono font-normal">{f.code}</span>{f.is_test && <span className="badge b-wn">تست</span>}</button>
      {more && <div className="mt-3 space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="کد محصول" error={show("code")} hint={edit ? "تغییر کد روی اتصال‌های بیرونی (API/بات) اثر می‌گذارد." : "خودکار از مدت و حجم ساخته می‌شود؛ در صورت نیاز ویرایش کنید."}><input dir="ltr" spellCheck={false} className="inp font-mono" maxLength={50} value={f.code} onChange={(e) => { setCodeTouched(true); set("code")(e.target.value); }} /></Field>
          <Field label="دسته‌بندی" hint="اختیاری"><input className="inp" maxLength={100} value={f.category} onChange={(e) => set("category")(e.target.value)} /></Field>
        </div>
        <Field label="توضیحات" hint="اختیاری"><input className="inp" value={f.description} onChange={(e) => set("description")(e.target.value)} /></Field>
        <Toggle checked={f.is_test} onChange={set("is_test")} label="محصول آزمایشی (تست)" hint="برای اکانت‌های آزمایشی؛ برای فروش عادی خاموش بماند." />
      </div>}
    </section>
  </Drawer>;
}

function Switches({ p, busy, hasResellers, onToggle, onToggleReseller }) {
  return <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
    <label className="flex cursor-pointer items-center gap-2 text-xs font-bold"><Switch checked={p.is_active} disabled={busy} onChange={(v) => onToggle(p, v)} label={`فعال‌سازی ${p.name} در فروشگاه اصلی`} />{hasResellers ? "فروشگاه اصلی" : p.is_active ? "فعال" : "غیرفعال"}</label>
    {hasResellers && <label className={`flex cursor-pointer items-center gap-2 text-xs font-bold ${p.is_active ? "" : "opacity-50"}`} title={p.is_active ? "" : "ابتدا در فروشگاه اصلی فعال کنید"}><Switch checked={p.is_active && p.reseller_enabled !== false} disabled={busy || !p.is_active} onChange={(v) => onToggleReseller(p, v)} label={`فعال‌سازی ${p.name} برای نمایندگان`} />نمایندگان</label>}
  </div>;
}

function ProductCard({ p, idx, busy, hasResellers, onEdit, onToggle, onToggleReseller, onDelete }) {
  const r = idx.reach(p), dim = p.is_active ? "" : "opacity-55";
  const state = !p.is_active ? "off" : r.ok ? "ok" : "bd";
  return <article className={`card card-i rise stripe flex flex-col gap-4 p-5 ${state === "off" ? "off" : ""}`} style={{ "--stripe": state === "ok" ? "var(--ok)" : state === "bd" ? "var(--bd)" : "var(--ln)" }}>
    <div className={`flex items-start gap-3 ${dim}`}>
      <span className="tile h-12 w-12" style={tint(p.is_test ? "wn" : "ok")}><Zap size={22} /></span>
      <div className="min-w-0 flex-1"><h3 className="truncate text-base font-extrabold" title={p.name}>{p.name}</h3><p dir="ltr" className="mt-0.5 truncate text-right font-mono text-[11px] text-[var(--mu)]">{p.code}</p></div>
      {p.is_test && <span className="badge b-wn">تست</span>}
    </div>
    <div className={`flex flex-wrap gap-1.5 ${dim}`}>{[[Clock, dur(p.duration_days)], [p.traffic_gb ? Zap : Inf, gb(p.traffic_gb)], [Smartphone, p.max_devices ? `${num(p.max_devices)} دستگاه` : "دستگاه نامحدود"]].map(([I, t], i) => <span key={i} className="spec"><I size={13} className="text-[var(--mu)]" />{t}</span>)}{p.category && <span className="spec"><Tag size={13} className="text-[var(--mu)]" />{p.category}</span>}</div>
    <div className={`price num ${dim}`}>{num(p.main_price)}<span className="mr-1.5 text-xs font-bold text-[var(--mu)]">{CUR[p.currency] || p.currency}</span></div>
    {p.is_active && <Route p={p} idx={idx} />}
    <div className="mt-auto flex items-center justify-between gap-2 border-t border-[var(--ln)] pt-3">
      <Switches p={p} busy={busy} hasResellers={hasResellers} onToggle={onToggle} onToggleReseller={onToggleReseller} />
      <div className="flex items-center gap-1.5"><DeleteButton compact label={`حذف ${p.name}`} busy={busy} onClick={() => onDelete(p)} /><button className="btn btn-g" onClick={() => onEdit(p)}><Pencil size={13} />ویرایش</button></div>
    </div>
  </article>;
}

function ProductTable({ rows, idx, busy, hasResellers, onEdit, onToggle, onToggleReseller, onDelete, quick, draft, setDraft }) {
  return <section className="card rise overflow-hidden"><div className="overflow-auto"><table className="tbl2 min-w-[760px]"><thead><tr>{["محصول", "مدت", "ترافیک", "دستگاه", "قیمت فروشگاه", "فروش", "فروشگاه اصلی", ...(hasResellers ? ["نمایندگان"] : []), ""].map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
    <tbody>{rows.map((p) => { const d = draft[p.id]?.main_price, dirty = quick && d !== undefined && d !== String(p.main_price); const r = idx.reach(p);
      return <tr key={p.id} className={`${p.is_active ? "" : "opacity-60"} ${dirty ? "!bg-[var(--wnb)]" : ""}`}>
        <td><div className="font-bold">{p.name}{p.is_test && <span className="badge b-wn mr-2">تست</span>}</div><div dir="ltr" className="text-right font-mono text-[11px] text-[var(--mu)]">{p.code}</div></td>
        <td>{dur(p.duration_days)}</td><td>{gb(p.traffic_gb)}</td><td>{p.max_devices ? num(p.max_devices) : "∞"}</td>
        <td>{quick ? <div className="w-36"><NumInput aria-label={`قیمت ${p.name}`} value={d ?? String(p.main_price)} onChange={(v) => setDraft((x) => ({ ...x, [p.id]: { main_price: v } }))} /></div> : <span className="font-semibold">{price(p.main_price, p.currency)}</span>}</td>
        <td className="min-w-[130px]">{r.ok ? <span className="badge b-ok" title={(r.groups || []).map((x) => x.name).join("، ")}>{num(r.live.length)} سرور · {num(r.free)} آزاد</span> : <span className="badge b-bd" title={r.issue}>مسیر ندارد</span>}</td>
        <td><Switch checked={p.is_active} disabled={busy.has(p.id)} onChange={(v) => onToggle(p, v)} label={`فعال‌سازی ${p.name}`} /></td>
        {hasResellers && <td><Switch checked={p.is_active && p.reseller_enabled !== false} disabled={busy.has(p.id) || !p.is_active} onChange={(v) => onToggleReseller(p, v)} label={`فعال‌سازی ${p.name} برای نمایندگان`} /></td>}
        <td><div className="flex items-center gap-1.5"><button className="btn btn-g" onClick={() => onEdit(p)}><Pencil size={13} />ویرایش</button>{!quick && <DeleteButton compact label={`حذف ${p.name}`} busy={busy.has(p.id)} onClick={() => onDelete(p)} />}</div></td></tr>; })}</tbody></table></div></section>;
}

export default function ProductsView({ api, toast }) {
  const infra = useInfra(api);
  const { call, idx } = infra;
  const prods = infra.products, storesQ = useRows(call, "/api/v1/admin/stores");
  const params = useHashParams();
  const [q, setQ] = useState(params.get("q") || "")
  // #4 Pagination
  const PAGE_SIZE = 20;
  const [page, setPage] = useState(0);
  useEffect(() => { setPage(0); }, [q]); // eslint-disable-line react-hooks/exhaustive-deps
  const [filter, setFilter] = useState(["on", "off", "broken", "test"].includes(params.get("filter")) ? params.get("filter") : "all"), [layout, setLayout] = useState("grid"), [sort, setSort] = useState("attention"), [drawer, setDrawer] = useState(null), [busy, setBusy] = useState(new Set());
  const [quick, setQuick] = useState(false), [draft, setDraft] = useState({}), [saving, setSaving] = useState(false);
  const alive = useAlive(); const rows = prods.rows;
  const hasResellers = (storesQ.rows || []).some((s) => s.kind === "reseller"); // no resellers yet = no cooperation switches at all
  useEffect(() => {
    setQ(params.get("q") || ""); if (params.get("filter")) setFilter(["on", "off", "broken", "test"].includes(params.get("filter")) ? params.get("filter") : "all");
    if (params.get("add") === "1") { setDrawer("add"); clearParam("add"); }
  }, [params]);
  const counts = useMemo(() => { const c = { all: 0, on: 0, off: 0, test: 0, broken: 0 }; (rows || []).forEach((p) => { c.all++; p.is_active ? c.on++ : c.off++; if (p.is_test) c.test++; if (p.is_active && !idx.reach(p).ok) c.broken++; }); return c; }, [rows, idx]);
  const shown = useMemo(() => (rows || []).filter((p) => (filter === "all" || (filter === "on" ? p.is_active : filter === "off" ? !p.is_active : filter === "broken" ? p.is_active && !idx.reach(p).ok : p.is_test)) && `${p.name} ${p.code} ${p.category || ""}`.toLowerCase().includes(q.trim().toLowerCase())), [rows, filter, q, idx]);
  const ordered = useMemo(() => {
    const by = { attention: (a, b) => Number(b.is_active && !idx.reach(b).ok) - Number(a.is_active && !idx.reach(a).ok) || Number(b.is_active) - Number(a.is_active) || a.duration_days - b.duration_days || a.main_price - b.main_price,
      price: (a, b) => a.main_price - b.main_price, price_desc: (a, b) => b.main_price - a.main_price, duration: (a, b) => a.duration_days - b.duration_days || a.main_price - b.main_price,
      traffic: (a, b) => (a.traffic_gb || 1e9) - (b.traffic_gb || 1e9), name: (a, b) => a.name.localeCompare(b.name, "fa") };
    return [...shown].sort(by[sort]);
  }, [shown, sort, idx]); // eslint-disable-line react-hooks/exhaustive-deps
  const editing = drawer && drawer !== "add" ? (rows || []).find((p) => p.id === drawer) : null;
  const table = layout === "table" || quick;

  const save = async (body, active, product) => {
    const r = await call(product ? `${API}/${product.id}` : API, { method: product ? "PATCH" : "POST", body: JSON.stringify(product ? { ...body, is_active: active } : body) });
    if (!r.ok) return errText(r, product ? "ذخیره تغییرات ناموفق بود" : "ساخت محصول ناموفق بود");
    if (!product && !active) { const c = await r.json().catch(() => null); if (c?.id) await call(`${API}/${c.id}`, { method: "PATCH", body: JSON.stringify({ is_active: false }) }); }
    setDrawer(null); toast(product ? "تغییرات محصول ذخیره شد" : "محصول ساخته شد"); await infra.reload(); return "";
  };
  const toggle = async (p, next) => {
    if (!next && !(await confirmDialog(`«${p.name}» غیرفعال شود؟ دیگر برای خرید جدید نمایش داده نمی‌شود${hasResellers ? " و برای نمایندگان هم غیرفعال می‌شود" : ""}.`, { title: "غیرفعال‌سازی محصول", danger: true, ok: "غیرفعال‌سازی" }))) return;
    setBusy((s) => new Set(s).add(p.id));
    let ok = false; try { ok = (await call(`${API}/${p.id}`, { method: "PATCH", body: JSON.stringify({ is_active: next }) })).ok; } catch { /* network */ }
    if (alive.current) setBusy((s) => { const n = new Set(s); n.delete(p.id); return n; });
    toast(ok ? (next ? `«${p.name}» فعال شد` : `«${p.name}» غیرفعال شد`) : "تغییر وضعیت ناموفق بود"); if (ok) await infra.reload();
  };
  const toggleReseller = async (p, next) => {
    setBusy((s) => new Set(s).add(p.id));
    let ok = false; try { ok = (await call(`${API}/${p.id}`, { method: "PATCH", body: JSON.stringify({ reseller_enabled: next }) })).ok; } catch { /* network */ }
    if (alive.current) setBusy((s) => { const n = new Set(s); n.delete(p.id); return n; });
    toast(ok ? (next ? `«${p.name}» برای نمایندگان فعال شد` : `«${p.name}» برای نمایندگان غیرفعال شد`) : "تغییر وضعیت ناموفق بود"); if (ok) await infra.reload();
  };
  const remove = async (p) => {
    setBusy((s) => new Set(s).add(p.id));
    const ok = await removeEntity(call, `${API}/${p.id}`, { toast, title: "حذف محصول", done: `«${p.name}» حذف شد`,
      message: `«${p.name}» برای همیشه حذف شود؟ این کار قابل بازگشت نیست. اگر برای این محصول سفارش یا اکانتی ثبت شده باشد حذف انجام نمی‌شود و باید آن را غیرفعال کنید.` });
    if (alive.current) setBusy((s) => { const n = new Set(s); n.delete(p.id); return n; });
    if (ok) { setDrawer(null); await infra.reload(); }
  };
  const changes = (rows || []).flatMap((p) => { const d = draft[p.id]; if (!d || d.main_price === undefined || d.main_price === "" || d.main_price === String(p.main_price)) return []; return [[p, { main_price: +d.main_price }]]; });
  const endQuick = async () => { if (changes.length && !(await confirmDialog("تغییرات قیمت ذخیره‌نشده از بین می‌رود. خارج می‌شوید؟", { title: "خروج از ویرایش سریع", danger: true, ok: "خروج" }))) return; setDraft({}); setQuick(false); };
  const saveQuick = async () => {
    if (!(await confirmDialog(`قیمت ${num(changes.length)} محصول به‌روزرسانی شود؟ قیمت جدید فوراً در فروشگاه اعمال می‌شود.`, { title: "ذخیره‌ی قیمت‌ها", ok: "ذخیره" }))) return;
    setSaving(true); let bad = 0;
    for (const [p, b] of changes) { try { if (!(await call(`${API}/${p.id}`, { method: "PATCH", body: JSON.stringify(b) })).ok) bad++; } catch { bad++; } }
    if (alive.current) setSaving(false);
    toast(bad ? `${num(bad)} مورد از ${num(changes.length)} ذخیره نشد` : "قیمت‌ها به‌روزرسانی شد"); await infra.reload(); if (!bad) { setDraft({}); setQuick(false); }
  };

  return <div className="space-y-5">
    <InfraChain current="products" infra={infra} />
    <KpiBar cols={5}>
      <Stat label="همه محصولات" value={counts.all} tone="in" Icon={Boxes} active={filter === "all"} onClick={() => setFilter("all")} />
      <Stat label="فعال" value={counts.on} tone="ok" Icon={CheckCircle2} active={filter === "on"} onClick={() => setFilter(filter === "on" ? "all" : "on")} />
      <Stat label="غیرفعال" value={counts.off} tone="mu" Icon={PowerOff} active={filter === "off"} onClick={() => setFilter(filter === "off" ? "all" : "off")} />
      <Stat label="بدون مسیر تخصیص" value={counts.broken} tone={counts.broken ? "bd" : "mu"} Icon={AlertTriangle} active={filter === "broken"} onClick={() => setFilter(filter === "broken" ? "all" : "broken")} />
      <Stat label="آزمایشی" value={counts.test} tone="wn" Icon={Tag} active={filter === "test"} onClick={() => setFilter(filter === "test" ? "all" : "test")} />
    </KpiBar>
    <div className="tool">
      <SearchBox label="جستجوی محصول" placeholder="جستجوی نام، کد یا دسته…" value={q} onChange={setQ} />
      <SortSelect value={sort} onChange={setSort} options={[["attention", "مشکل‌دارها اول"], ["price", "ارزان‌ترین"], ["price_desc", "گران‌ترین"], ["duration", "کم‌ترین مدت"], ["traffic", "کم‌ترین حجم"], ["name", "نام"]]} />
      <ViewToggle value={table ? "table" : "grid"} onChange={setLayout} disabled={quick} options={[["grid", "کارتی"], ["table", "جدولی"]]} />
      <div className="mr-auto flex flex-wrap items-center gap-2">
        {quick ? <><span className="text-xs text-[var(--mu)]">{changes.length ? `${num(changes.length)} تغییر` : "قیمت فروشگاه را مستقیم در جدول ویرایش کنید"}</span>
          <button className="btn !py-2 !text-sm" disabled={!changes.length || saving} onClick={saveQuick}><Save size={14} />{saving ? "در حال ذخیره…" : "ذخیره قیمت‌ها"}</button><button className="btn btn-g !py-2 !text-sm" disabled={saving} onClick={endQuick}><X size={14} />خروج</button></>
          : <><button className="btn btn-g !py-2 !text-sm" disabled={!counts.all} onClick={() => { setLayout("table"); setQuick(true); }}><Wallet size={14} />ویرایش سریع قیمت‌ها</button><button className="btn" onClick={() => setDrawer("add")}><Plus size={16} />افزودن محصول</button></>}
      </div>
    </div>
    {prods.failed && <ErrorBar onRetry={prods.load}><ShieldAlert size={16} />دریافت محصولات ناموفق بود.</ErrorBar>}
    {(rows === null || infra.loading) ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="card skel h-80" />)}</div>
      : !ordered.length ? <Empty Icon={Boxes} title={counts.all ? "محصولی با این فیلتر پیدا نشد" : "هنوز محصولی تعریف نشده"} text={counts.all ? "جستجو یا فیلتر را تغییر دهید." : "هر محصول یک پلن قابل فروش با مدت، حجم و قیمت مشخص است. ابتدا باید حداقل یک پنل سالم با سرور داشته باشید."}>
        {!counts.all && <button className="btn" onClick={() => setDrawer("add")}><Plus size={16} />ساخت اولین محصول</button>}</Empty>
      : table ? <ProductTable idx={idx} rows={ordered} busy={busy} hasResellers={hasResellers} onEdit={(x) => setDrawer(x.id)} onToggle={toggle} onToggleReseller={toggleReseller} onDelete={remove} quick={quick} draft={draft} setDraft={setDraft} />
      : <><div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{ordered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE).map((p) => <ProductCard key={p.id} p={p} idx={idx} busy={busy.has(p.id)} hasResellers={hasResellers} onEdit={(x) => setDrawer(x.id)} onToggle={toggle} onToggleReseller={toggleReseller} onDelete={remove} />)}</div>
        <Paginator page={page} setPage={setPage} total={ordered.length} pageSize={PAGE_SIZE} /></>}
    {drawer && (drawer === "add" || editing) && <ProductDrawer key={drawer} product={editing} products={rows || []} hasResellers={hasResellers} onClose={() => setDrawer(null)} onSubmit={save} onDelete={remove} />}
  </div>;
}
