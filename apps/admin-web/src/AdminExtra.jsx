import { useEffect, useState } from "react";
import { authFetch } from "./api.js";
const money = (n) => new Intl.NumberFormat("fa-IR").format(n || 0);
const box = "rounded-2xl border border-[#dce0dc] bg-white shadow-sm";
const inp = "w-full rounded-xl border border-[#dce0dc] p-2.5 text-sm outline-none focus:border-[#b55328]";
const btn = "rounded-xl bg-[#11243f] px-4 py-2 text-sm font-bold text-white disabled:opacity-40";
const ghost = "rounded-lg border border-[#dce0dc] px-3 py-1.5 text-xs font-bold";

function useList(api, path, toast) {
  const [rows, setRows] = useState([]); const [tick, setTick] = useState(0);
  const call = (p, o = {}) => authFetch(api.base, p, o);
  useEffect(() => { call(path).then((r) => r.ok ? r.json() : Promise.reject()).then((d) => setRows(Array.isArray(d) ? d : d.items || [])).catch(() => toast("دریافت داده ناموفق بود")); }, [path, tick]);
  return { rows, call, reload: () => setTick((x) => x + 1) };
}
const Table = ({ cols, rows, title, extra }) => <section className={`${box} overflow-hidden`}><div className="flex items-center justify-between border-b border-[#e6e8e5] px-5 py-4"><h3 className="font-extrabold">{title}</h3>{extra}</div><div className="overflow-x-auto"><table className="w-full min-w-[640px] text-right text-sm"><thead className="bg-[#fafbf9] text-xs text-[#55636e]"><tr>{cols.map((c) => <th key={c} className="px-5 py-3 font-medium">{c}</th>)}</tr></thead><tbody>{rows.length ? rows.map((r, i) => <tr key={i} className="border-t border-[#edf0ed]">{r.map((c, j) => <td key={j} className="px-5 py-3">{c ?? "-"}</td>)}</tr>) : <tr><td colSpan={cols.length} className="p-10 text-center text-[#71808b]">داده‌ای وجود ندارد</td></tr>}</tbody></table></div></section>;
const Form = ({ fields, onSubmit, label }) => { const [v, setV] = useState({}); return <div className={`${box} mb-5 grid gap-3 p-5 sm:grid-cols-3`}>{fields.map(([k, l, t]) => <label key={k} className="text-xs font-bold text-[#55636e]">{l}<input type={t || "text"} dir="ltr" className={`${inp} mt-1`} value={v[k] ?? ""} onChange={(e) => setV({ ...v, [k]: e.target.value })} /></label>)}<div className="flex items-end"><button className={btn} onClick={() => onSubmit(v, () => setV({}))}>{label}</button></div></div>; };

function Products({ api, toast }) {
  const { rows, call, reload } = useList(api, "/api/v1/admin/products", toast);
  const create = async (v, done) => { const r = await call("/api/v1/admin/products", { method: "POST", body: JSON.stringify({ code: v.code, name: v.name, duration_days: +v.days, traffic_gb: +v.gb, max_devices: v.dev ? +v.dev : null, main_price: +v.main, reseller_price: +v.res, currency: v.cur || "IRT" }) }); if (r.ok) { toast("محصول ساخته شد"); done(); reload(); } else toast("ساخت محصول ناموفق بود"); };
  const toggle = async (p) => { const r = await call(`/api/v1/admin/products/${p.id}`, { method: "PATCH", body: JSON.stringify({ is_active: !p.is_active }) }); r.ok ? reload() : toast("تغییر ناموفق بود"); };
  return <><Form label="افزودن محصول" onSubmit={create} fields={[["code", "کد"], ["name", "نام"], ["days", "روز", "number"], ["gb", "ترافیک GB", "number"], ["dev", "دستگاه", "number"], ["main", "قیمت اصلی", "number"], ["res", "قیمت نماینده", "number"], ["cur", "ارز (IRT)"]]} />
    <Table title="محصولات" cols={["کد", "نام", "مدت", "ترافیک", "قیمت", "وضعیت", ""]} rows={rows.map((p) => [p.code, p.name, `${p.duration_days} روز`, `${p.traffic_gb} GB`, `${money(p.main_price)} ${p.currency}`, p.is_active ? "فعال" : "غیرفعال", <button className={ghost} onClick={() => toggle(p)}>{p.is_active ? "غیرفعال‌سازی" : "فعال‌سازی"}</button>])} /></>;
}

function Panels({ api, toast }) {
  const { rows, call, reload } = useList(api, "/api/v1/admin/panels", toast);
  const create = async (v, done) => { let credentials = {}, config = {}; try { credentials = v.cred ? JSON.parse(v.cred) : {}; } catch { return toast("JSON اعتبارنامه نامعتبر است"); } try { config = v.cfg ? JSON.parse(v.cfg) : {}; } catch { return toast("JSON تنظیمات پنل نامعتبر است"); } const r = await call("/api/v1/admin/panels", { method: "POST", body: JSON.stringify({ name: v.name, kind: v.kind, base_url: v.url, credentials, config }) }); if (r.ok) { toast("پنل ثبت شد"); done(); reload(); } else toast("ثبت پنل ناموفق بود"); };
  const check = async (p) => { const r = await call(`/api/v1/admin/panels/${p.id}/health`, { method: "POST" }); toast(r.ok ? "بررسی سلامت انجام شد" : "بررسی ناموفق بود"); reload(); };
  return <><Form label="افزودن پنل" onSubmit={create} fields={[["name", "نام"], ["kind", "نوع (sanaei|pasarguard|mock)"], ["url", "Base URL (با web base path)"], ["cred", 'Credentials JSON — سنایی: {"api_token":"..."}'], ["cfg", 'Config JSON — سنایی: {"inbound_ids":[1],"sub_base_url":"https://sub.example.com:2096/sub"}']]} />
    <Table title="پنل‌ها" cols={["نام", "نوع", "آدرس", "سلامت", "آخرین بررسی", ""]} rows={rows.map((p) => [p.name, p.kind, <span dir="ltr">{p.base_url}</span>, p.health_status, p.last_health_at ? new Date(p.last_health_at).toLocaleString("fa-IR") : "-", <button className={ghost} onClick={() => check(p)}>بررسی سلامت</button>])} /></>;
}

function Coupons({ api, toast }) {
  const { rows, call, reload } = useList(api, "/api/v1/admin/coupons", toast);
  const stores = useList(api, "/api/v1/admin/stores", toast).rows;
  const create = async (v, done) => { const main = stores.find((s) => s.kind === "main") || stores[0]; const r = await call("/api/v1/admin/coupons", { method: "POST", body: JSON.stringify({ code: v.code, percent_bp: Math.round((+v.pct || 0) * 100), fixed: +v.fixed || 0, max_redemptions: v.max ? +v.max : null, scope: "store", store_id: main?.id }) }); if (r.ok) { toast("کوپن ساخته شد"); done(); reload(); } else toast("ساخت کوپن ناموفق بود"); };
  const toggle = async (c) => { const r = await call(`/api/v1/admin/coupons/${c.id}`, { method: "PATCH", body: JSON.stringify({ status: c.status === "active" ? "disabled" : "active" }) }); r.ok ? reload() : toast("تغییر ناموفق بود"); };
  return <><Form label="افزودن کوپن" onSubmit={create} fields={[["code", "کد"], ["pct", "درصد تخفیف", "number"], ["fixed", "تخفیف ثابت", "number"], ["max", "سقف استفاده", "number"]]} />
    <Table title="کوپن‌ها" cols={["کد", "درصد", "ثابت", "استفاده", "وضعیت", ""]} rows={rows.map((c) => [c.code, c.percent_bp != null ? `${c.percent_bp / 100}%` : "-", money(c.fixed), `${c.redeemed ?? c.redemptions ?? 0}/${c.max_redemptions ?? "∞"}`, c.status, <button className={ghost} onClick={() => toggle(c)}>{c.status === "active" ? "غیرفعال" : "فعال"}</button>])} /></>;
}

function SettingRow({ k, v, save }) {
  const [t, setT] = useState(JSON.stringify(v));
  useEffect(() => setT(JSON.stringify(v)), [v]);
  const dirty = t !== JSON.stringify(v);
  return <div className="flex items-center gap-3 border-t border-[#edf0ed] px-5 py-3"><code dir="ltr" className="w-60 shrink-0 text-xs font-bold">{k}</code><input dir="ltr" className={inp} value={t} onChange={(e) => setT(e.target.value)} /><button disabled={!dirty} className={btn} onClick={() => save(k, t)}>ذخیره</button></div>;
}
function Settings({ api, toast }) {
  const flags = useList(api, "/api/v1/admin/feature-flags", toast);
  const settings = useList(api, "/api/v1/admin/settings", toast);
  const [obj, setObj] = useState({});
  const [tick, setTick] = useState(0);
  useEffect(() => { flags.call("/api/v1/admin/settings").then((r) => r.ok ? r.json() : {}).then(setObj); }, [tick]);
  const setFlag = async (f) => { const r = await flags.call(`/api/v1/admin/feature-flags/${encodeURIComponent(f.key)}`, { method: "PUT", body: JSON.stringify({ enabled: !f.enabled, scope_type: f.scope_type, scope_id: f.scope_id, note: f.note }) }); r.ok ? flags.reload() : toast("تغییر ناموفق بود"); };
  const save = async (key, text) => {
    let value; try { value = JSON.parse(text); } catch { return toast("مقدار باید JSON معتبر باشد"); }
    if (!window.confirm(`مقدار ${key} تغییر کند؟`)) return;
    const r = await flags.call(`/api/v1/admin/settings/${key}`, { method: "PUT", body: JSON.stringify({ value }) });
    if (r.ok) { toast("تنظیم ذخیره شد"); setTick((x) => x + 1); } else toast("ذخیره ناموفق بود");
  };
  return <div className="space-y-5"><Table title="Feature Flags" cols={["کلید", "محدوده", "فعال", ""]} rows={flags.rows.map((f) => [f.key, `${f.scope_type}:${f.scope_id}`, f.enabled ? "بله" : "خیر", <button className={ghost} onClick={() => setFlag(f)}>{f.enabled ? "خاموش" : "روشن"}</button>])} />
    <section className={`${box} overflow-hidden`}><h3 className="px-5 py-4 font-extrabold">تنظیمات سیستم <span className="text-xs font-normal text-[#71808b]">(مقدار به‌صورت JSON)</span></h3>{Object.entries(obj).map(([k, v]) => <SettingRow key={k} k={k} v={v} save={save} />)}</section></div>;
}

function Audit({ api, toast }) {
  const { rows } = useList(api, "/api/v1/admin/audit", toast);
  return <Table title="لاگ ممیزی" cols={["زمان", "عملیات", "نقش", "موجودیت", "Correlation"]} rows={rows.map((a) => [a.created_at ? new Date(a.created_at).toLocaleString("fa-IR") : "-", a.action, a.actor_type, `${a.entity_type || ""} ${String(a.entity_id || "").slice(0, 8)}`, <span className="text-xs">{String(a.correlation_id || "").slice(0, 8)}</span>])} />;
}

function Reviews({ api, toast }) {
  const { rows, call, reload } = useList(api, "/api/v1/admin/identity-link-reviews", toast);
  const dismiss = async (id) => { const r = await call(`/api/v1/admin/identity-link-reviews/${id}/dismiss`, { method: "POST" }); r.ok ? (toast("رد شد"), reload()) : toast("ناموفق"); };
  return <Table title="بررسی لینک هویت" cols={["ایمیل", "ارائه‌دهنده", "دلیل", "وضعیت", ""]} rows={rows.map((r) => [r.email, r.provider, r.reason, r.status, <button className={ghost} onClick={() => dismiss(r.id)}>رد کردن</button>])} />;
}


const ask = (m) => { const r = window.prompt(m, ""); return r === null ? null : r; };
function Orders({ api, toast }) {
  const { rows, call, reload } = useList(api, "/api/v1/admin/orders", toast);
  const act = async (o, kind, label) => {
    const reason = kind === "retry" ? "" : ask(`دلیل ${label}:`); if (reason === null) return;
    if (kind === "refund" && !window.confirm("استرداد این سفارش انجام شود؟")) return;
    const r = await call(`/api/v1/admin/orders/${o.id}/${kind}`, { method: "POST", body: JSON.stringify({ reason }) });
    if (r.ok) { toast(`${label} ثبت شد`); reload(); } else toast(`${label} ناموفق بود`);
  };
  return <Table title="سفارش‌ها" cols={["شماره", "Store", "مبلغ", "وضعیت", "بررسی", "اقدام"]} rows={rows.map((o) => [o.number, String(o.store_id || "").slice(0, 8), `${money(o.total)} ${o.currency || ""}`, o.status, o.needs_review ? "بله" : "خیر",
    <div className="flex gap-1.5"><button className={ghost} onClick={() => act(o, "retry", "تلاش مجدد")}>تلاش مجدد</button><button className={ghost} onClick={() => act(o, "manual-review", "بررسی دستی")}>بررسی دستی</button><button className={`${ghost} text-[#91390c]`} onClick={() => act(o, "refund", "استرداد")}>استرداد</button></div>])} />;
}

function Payments({ api, toast }) {
  const { rows, call, reload } = useList(api, "/api/v1/admin/payments", toast);
  const review = async (p, approve) => {
    const reason = approve ? "" : ask("دلیل رد پرداخت:"); if (reason === null) return;
    const r = await call(`/api/v1/admin/payments/${p.id}/review`, { method: "POST", body: JSON.stringify({ approve, reason }) });
    if (r.ok) { toast(approve ? "پرداخت تأیید شد" : "پرداخت رد شد"); reload(); } else toast("بررسی ناموفق بود");
  };
  const view = async (p) => { const r = await call(`/api/v1/admin/payments/${p.id}/receipt`); if (!r.ok) return toast("نمایش رسید ناموفق بود"); const url = URL.createObjectURL(await r.blob()); window.open(url, "_blank", "noopener"); setTimeout(() => URL.revokeObjectURL(url), 60000); };
  const pending = (p) => ["pending", "review", "receipt_submitted", "awaiting_review"].includes(p.status) && p.has_receipt;
  return <Table title="پرداخت‌ها" cols={["مبلغ", "درگاه", "وضعیت", "رسید", "اقدام"]} rows={rows.map((p) => [`${money(p.amount)} ${p.currency}`, p.provider, p.status, p.has_receipt ? <button className={ghost} onClick={() => view(p)}>مشاهده رسید</button> : "ندارد",
    pending(p) ? <div className="flex gap-1.5"><button className={ghost} onClick={() => review(p, true)}>تأیید</button><button className={`${ghost} text-[#91390c]`} onClick={() => review(p, false)}>رد</button></div> : "-"])} />;
}

function Tickets({ api, toast }) {
  const { rows, call, reload } = useList(api, "/api/v1/admin/tickets", toast);
  const [sel, setSel] = useState(null); const [msgs, setMsgs] = useState([]); const [text, setText] = useState("");
  const open = async (t) => { setSel(t); const r = await call(`/api/v1/tickets/${t.id}/messages`); setMsgs(r.ok ? await r.json() : []); };
  const send = async () => { const r = await call(`/api/v1/tickets/${sel.id}/messages`, { method: "POST", body: JSON.stringify({ body: text }) }); if (r.ok) { setText(""); open(sel); reload(); } else toast("ارسال پاسخ ناموفق بود"); };
  if (!sel) return <Table title="تیکت‌ها" cols={["موضوع", "Store", "وضعیت", "آخرین تغییر", ""]} rows={rows.map((t) => [t.subject, String(t.store_id || "").slice(0, 8), t.status, t.updated_at ? new Date(t.updated_at).toLocaleString("fa-IR") : "-", <button className={ghost} onClick={() => open(t)}>مشاهده و پاسخ</button>])} />;
  return <section className={`${box} p-5`}><button className="text-sm font-bold text-[#b55328]" onClick={() => setSel(null)}>→ بازگشت</button><h3 className="mt-2 font-extrabold">{sel.subject}</h3>
    <div className="mt-4 space-y-3">{msgs.map((m) => <div key={m.id} className={`max-w-[80%] rounded-2xl p-3 text-sm leading-7 ${m.is_staff ? "mr-auto bg-[#dcefe4]" : "bg-[#f3f4f1]"}`}>{m.body}<div className="mt-1 text-[10px] text-[#71808b]">{m.is_staff ? "پشتیبانی" : "مشتری"} · {new Date(m.created_at).toLocaleString("fa-IR")}</div></div>)}</div>
    <div className="mt-4 flex gap-2"><input className={inp} value={text} onChange={(e) => setText(e.target.value)} placeholder="پاسخ پشتیبانی…" /><button disabled={!text.trim()} className={btn} onClick={send}>ارسال</button></div></section>;
}

export const extraRoutes = { "سفارش‌ها": Orders, "پرداخت‌ها": Payments, "تیکت‌ها": Tickets, "محصولات": Products, "پنل‌ها": Panels, "کوپن‌ها": Coupons, "تنظیمات": Settings, "ممیزی": Audit, "بررسی هویت": Reviews };
