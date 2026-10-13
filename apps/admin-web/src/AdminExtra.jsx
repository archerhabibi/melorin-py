import { useEffect, useState } from "react";
import { authFetch } from "./api.js";
import { Plus, Search, X } from "lucide-react";
import { Badge, confirmDialog, dt, isStatus, promptDialog } from "./ui.jsx";
import PanelsView from "./PanelsView.jsx";
const money = (n) => new Intl.NumberFormat("fa-IR").format(n || 0);
const box = "card";
const inp = "inp";
const btn = "btn";
const ghost = "btn btn-g";

function useList(api, path, toast) {
  const [rows, setRows] = useState([]); const [tick, setTick] = useState(0);
  const call = (p, o = {}) => authFetch(api.base, p, o);
  useEffect(() => { call(path).then((r) => r.ok ? r.json() : Promise.reject()).then((d) => setRows(Array.isArray(d) ? d : d.items || [])).catch(() => toast("دریافت داده ناموفق بود")); }, [path, tick]);
  return { rows, call, reload: () => setTick((x) => x + 1) };
}
const Table = ({ cols, rows, title, extra }) => {
  const [q, setQ] = useState("");
  const show = q ? rows.filter((r) => r.some((c) => typeof c === "string" && c.toLowerCase().includes(q.toLowerCase()))) : rows;
  return <section className={`${box} rise overflow-hidden`}>
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--ln)] px-5 py-4"><h3 className="font-extrabold">{title} <span className="text-xs font-medium text-[var(--mu)]">({show.length.toLocaleString("fa-IR")})</span></h3>
      <div className="flex items-center gap-2">{extra}<label className="relative"><Search size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[var(--mu)]" /><input aria-label="جستجو" value={q} onChange={(e) => setQ(e.target.value)} placeholder="جستجو…" className={`${inp} w-44 pr-9`} /></label></div></div>
    <div className="max-h-[70vh] overflow-auto"><table className="tbl min-w-[640px]"><thead><tr>{cols.map((c, i) => <th key={i}>{c}</th>)}</tr></thead><tbody>{show.length ? show.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{isStatus(c) ? <Badge s={c} /> : (c ?? "-")}</td>)}</tr>) : <tr><td colSpan={cols.length} className="p-12 text-center text-[var(--mu)]">{q ? "نتیجه‌ای پیدا نشد" : "داده‌ای وجود ندارد"}</td></tr>}</tbody></table></div>
  </section>;
};
const JSONK = new Set(["cred", "cfg"]);
const Form = ({ fields, onSubmit, label }) => {
  const [v, setV] = useState({}); const [open, setOpen] = useState(false);
  if (!open) return <div className="mb-5"><button className="btn" onClick={() => setOpen(true)}><Plus size={16} />{label}</button></div>;
  return <section className="card rise mb-5 p-5">
    <div className="mb-4 flex items-center justify-between"><h3 className="font-extrabold">{label}</h3><button aria-label="بستن فرم" className="btn btn-g" onClick={() => setOpen(false)}><X size={15} /></button></div>
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{fields.map(([k, l, t]) => JSONK.has(k)
      ? <label key={k} className="text-xs font-bold text-[var(--mu)] sm:col-span-2 lg:col-span-4">{l}<textarea rows={3} dir="ltr" spellCheck={false} className={`${inp} mt-1.5 font-mono text-xs`} value={v[k] ?? ""} onChange={(e) => setV({ ...v, [k]: e.target.value })} /></label>
      : <label key={k} className="text-xs font-bold text-[var(--mu)]">{l}{t === "select"
        ? <select dir="ltr" className={`${inp} mt-1.5`} value={v[k] ?? "IRT"} onChange={(e) => setV({ ...v, [k]: e.target.value })}><option value="IRT">IRT</option><option value="USD">USD</option><option value="USDT">USDT</option><option value="XTR">XTR</option></select>
        : <input type={t || "text"} dir="ltr" className={`${inp} mt-1.5`} value={v[k] ?? ""} onChange={(e) => setV({ ...v, [k]: e.target.value })} />}</label>)}</div>
    <div className="mt-5 flex gap-2"><button className={btn} onClick={() => onSubmit(v, () => { setV({}); setOpen(false); })}>{label}</button><button className="btn btn-g" onClick={() => setOpen(false)}>انصراف</button></div>
  </section>;
};

function Products({ api, toast }) {
  const { rows, call, reload } = useList(api, "/api/v1/admin/products", toast);
  const stores = useList(api, "/api/v1/admin/stores", toast).rows;
  const create = async (v, done) => { const r = await call("/api/v1/admin/products", { method: "POST", body: JSON.stringify({ code: v.code, name: v.name, duration_days: +v.days, traffic_gb: +v.gb, max_devices: v.dev ? +v.dev : null, main_price: +v.main, reseller_price: +v.res, currency: v.cur || "IRT" }) }); if (r.ok) { toast("محصول ساخته شد"); done(); reload(); } else { const d = await r.json().catch(() => ({})); toast(d?.error?.message || "ساخت محصول ناموفق بود"); } };
  const toggle = async (p) => { const r = await call(`/api/v1/admin/products/${p.id}`, { method: "PATCH", body: JSON.stringify({ is_active: !p.is_active }) }); r.ok ? reload() : toast("تغییر ناموفق بود"); };
  return <><Form label="افزودن محصول VPN" onSubmit={create} fields={[["code", "کد"], ["name", "نام"], ["days", "روز", "number"], ["gb", "ترافیک GB", "number"], ["dev", "دستگاه", "number"], ["main", "قیمت اصلی", "number"], ["res", "قیمت نماینده", "number"], ["cur", "ارز", "select"]]} />
    <Table title="محصولات VPN" cols={["کد", "نام", "مدت", "ترافیک", "قیمت", "وضعیت", ""]} rows={rows.map((p) => [p.code, p.name, `${p.duration_days} روز`, `${p.traffic_gb} GB`, `${money(p.main_price)} ${p.currency}`, p.is_active ? "فعال" : "غیرفعال", <button className={ghost} onClick={() => toggle(p)}>{p.is_active ? "غیرفعال‌سازی" : "فعال‌سازی"}</button>])} />
    <ProductAvailability api={api} toast={toast} products={rows} stores={stores} /></>;
}

function ProductAvailability({ api, toast, products, stores }) {
  const [productId, setProductId] = useState("");
  const [storeId, setStoreId] = useState("");
  const [price, setPrice] = useState("");
  const [listed, setListed] = useState(true);
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const main = stores.find((s) => s.kind === "main");
  const selected = products.find((p) => String(p.id) === productId);
  useEffect(() => {
    if (!productId && products[0]) setProductId(String(products[0].id));
    if (!storeId && (main || stores[0])) setStoreId(String((main || stores[0]).id));
  }, [products, stores]);
  useEffect(() => {
    const p = products.find((x) => String(x.id) === productId);
    const s = stores.find((x) => String(x.id) === storeId);
    if (p && s) setPrice(String(s.kind === "main" ? p.main_price : (p.reseller_price || p.main_price)));
  }, [productId, storeId, products, stores]);
  const publish = async () => {
    if (!productId || !storeId) return toast("محصول و فروشگاه را انتخاب کنید");
    setBusy(true);
    const s = stores.find((x) => String(x.id) === storeId);
    const r = await authFetch(api.base, `/api/v1/admin/products/${productId}/availability`, {
      method: "POST",
      body: JSON.stringify({ store_id: storeId, enabled, listed, customer_price: s?.kind === "reseller" ? Number(price || 0) : null }),
    });
    setBusy(false);
    if (!r.ok) return toast("انتشار محصول در فروشگاه ناموفق بود");
    toast(`«${selected?.name || "محصول"}» در «${s?.name || "فروشگاه"}» منتشر شد`);
  };
  if (!products.length || !stores.length) return <section className="card mt-5 p-5 text-sm text-[var(--mu)]">برای انتشار محصول، ابتدا حداقل یک محصول و فروشگاه بسازید.</section>;
  return <section className="card rise mt-5 p-5">
    <div className="mb-4">
      <h3 className="font-extrabold">انتشار محصول در فروشگاه</h3>
      <p className="mt-1 text-xs leading-6 text-[var(--mu)]">محصول تا وقتی اینجا فعال نشود، در سایت و بات نمایش داده نمی‌شود.</p>
    </div>
    <div className="grid gap-3 md:grid-cols-4">
      <label className="text-xs font-bold text-[var(--mu)]">محصول<select className={`${inp} mt-1.5`} value={productId} onChange={(e) => setProductId(e.target.value)}>{products.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.code})</option>)}</select></label>
      <label className="text-xs font-bold text-[var(--mu)]">فروشگاه<select className={`${inp} mt-1.5`} value={storeId} onChange={(e) => setStoreId(e.target.value)}>{stores.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.kind})</option>)}</select></label>
      <label className="text-xs font-bold text-[var(--mu)]">قیمت نماینده<input className={`${inp} mt-1.5`} type="number" min="0" value={price} onChange={(e) => setPrice(e.target.value)} /></label>
      <div className="flex items-end"><button className={`${btn} w-full`} disabled={busy} onClick={publish}>{busy ? "در حال ذخیره..." : "انتشار / ذخیره"}</button></div>
    </div>
    <div className="mt-4 flex flex-wrap gap-5">
      <Toggle on={enabled} set={setEnabled} label="قابل فروش" />
      <Toggle on={listed} set={setListed} label="نمایش در کاتالوگ" />
    </div>
  </section>;
}

function PanelGroups({ api, toast }) {
  const { rows, call, reload } = useList(api, "/api/v1/admin/panel-groups", toast);
  const panels = useList(api, "/api/v1/admin/panels", toast).rows;
  const create = async (v, done) => {
    const panel_ids = panels.filter((p) => (v.panels || "").split(",").map((x) => x.trim()).includes(String(p.id))).map((p) => p.id);
    const r = await call("/api/v1/admin/panel-groups", { method: "POST", body: JSON.stringify({
      name: v.name, selection_mode: v.mode || "automatic", naming_mode: v.naming || "automatic",
      sales_limit: v.limit ? +v.limit : null, panel_ids,
    })});
    if (r.ok) { toast("گروه پنل VPN ساخته شد"); done(); reload(); } else toast("ساخت گروه ناموفق بود");
  };
  const toggle = async (b) => {
    const r = await call(`/api/v1/admin/panel-groups/${b.id}`, { method: "PATCH", body: JSON.stringify({ is_enabled: !b.is_enabled }) });
    r.ok ? reload() : toast("تغییر وضعیت ناموفق بود");
  };
  return <><Form label="افزودن گروه پنل VPN" onSubmit={create} fields={[
    ["name", "نام گروه"], ["mode", "حالت انتخاب (automatic/manual)"], ["naming", "نام‌گذاری (automatic/custom)"],
    ["limit", "سقف فروش", "number"], ["panels", "شناسه پنل‌ها، با کاما جدا"],
  ]} /><Table title="گروه‌های پنل VPN" cols={["نام", "انتخاب", "نام‌گذاری", "پنل‌ها", "فروش", "وضعیت", ""]} rows={rows.map((b) => [
    b.name, b.selection_mode, b.naming_mode, b.panels?.length || 0, `${b.sold_count}/${b.sales_limit ?? "∞"}`,
    b.is_enabled ? "فعال" : "غیرفعال", <button className={ghost} onClick={() => toggle(b)}>{b.is_enabled ? "غیرفعال‌سازی" : "فعال‌سازی"}</button>
  ])} /></>;
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
  return <div className="flex items-center gap-3 border-t border-[var(--ln)] px-5 py-3"><code dir="ltr" className="w-60 shrink-0 text-xs font-bold text-[var(--tx)]">{k}</code><input dir="ltr" className={inp} value={t} onChange={(e) => setT(e.target.value)} /><button disabled={!dirty} className={btn} onClick={() => save(k, t)}>ذخیره</button></div>;
}

const Field = ({ label, children }) => <label className="block text-xs font-bold text-[var(--mu)]">{label}<div className="mt-1">{children}</div></label>;
const Toggle = ({ on, set, label }) => <label className="flex cursor-pointer items-center gap-2 text-sm font-bold"><input type="checkbox" checked={on} onChange={(e) => set(e.target.checked)} />{label}</label>;

function Integrations({ api, toast }) {
  const call = (p, o = {}) => authFetch(api.base, p, o);
  const [aa, setAa] = useState(null); const [ipText, setIpText] = useState("");
  const [em, setEm] = useState(null); const [s3, setS3] = useState(null); const [local, setLocal] = useState(null);
  const [pw, setPw] = useState(""); const [sk, setSk] = useState(""); const [to, setTo] = useState(""); const [busy, setBusy] = useState("");
  const load = () => call("/api/v1/admin/integrations").then((r) => r.ok ? r.json() : Promise.reject()).then((d) => { setAa(d.admin_access); setIpText((d.admin_access?.ips || []).join("\n")); setEm(d.email); setS3(d.backup.s3); setLocal(d.backup.local); setPw(""); setSk(""); }).catch(() => toast("دریافت تنظیمات ناموفق بود"));
  useEffect(() => { load(); }, []);
  if (!em || !s3 || !aa) return null;
  const send = async (path, body, okMsg, tag) => {
    setBusy(tag);
    const r = await call(path, { method: path.endsWith("/test") ? "POST" : "PUT", body: JSON.stringify(body) });
    setBusy("");
    const d = await r.json().catch(() => ({}));
    if (!r.ok) return toast(d?.error?.message || d?.detail?.message || "ذخیره ناموفق بود");
    if (path.endsWith("/test")) return toast(d.ok ? okMsg : `ناموفق: ${d.error || ""}`);
    toast(okMsg); load();
  };
  const sm = (k) => (v) => setEm({ ...em, [k]: v });
  const s3s = (k) => (v) => setS3({ ...s3, [k]: v });
  return <section className={`${box} space-y-6 p-5`}>
    <h3 className="font-extrabold">یکپارچه‌سازی‌ها <span className="text-xs font-normal text-[var(--mu)]">(اختیاری؛ برای نصب لازم نیستند)</span></h3>
    <div className="space-y-3 rounded-xl border border-[var(--ln)] p-4">
      <div className="flex items-center justify-between"><b>دسترسی ادمین (محدودیت IP)</b><Toggle on={aa.enabled} set={(v) => setAa({ ...aa, enabled: v })} label={aa.enabled ? "فعال" : "غیرفعال"} /></div>
      <p className="text-xs text-[var(--mu)]">به‌طور پیش‌فرض خاموش است. در حالت فعال، API ادمین فقط از IPها/CIDRهای زیر پاسخ می‌دهد (هر خط یک مورد). IP فعلی شما: <code dir="ltr">{aa.your_ip}</code>. اگر قفل شدید، روی سرور: <code dir="ltr">python -m melorin.cli disable-admin-ip-allowlist</code></p>
      <textarea dir="ltr" rows={3} className={inp} value={ipText} onChange={(e) => setIpText(e.target.value)} placeholder={"203.0.113.10/32\n198.51.100.0/24"} />
      <button disabled={busy === "aa"} className={btn} onClick={() => send("/api/v1/admin/integrations/admin-access", { enabled: aa.enabled, ips: ipText.split(/[\s,]+/).filter(Boolean) }, "تنظیمات دسترسی ادمین ذخیره شد", "aa")}>ذخیره</button>
    </div>
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="space-y-3 rounded-xl border border-[var(--ln)] p-4">
        <div className="flex items-center justify-between"><b>ایمیل (SMTP)</b><Toggle on={em.enabled} set={sm("enabled")} label={em.enabled ? "فعال" : "غیرفعال"} /></div>
        <p className="text-xs text-[var(--mu)]">وقتی غیرفعال است، ورود با کد ایمیلی در دسترس نیست؛ بقیه‌ی روش‌های ورود و سیستم عادی کار می‌کنند.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="میزبان SMTP"><input dir="ltr" className={inp} value={em.host} onChange={(e) => sm("host")(e.target.value)} placeholder="smtp.example.com" /></Field>
          <Field label="پورت"><input dir="ltr" type="number" className={inp} value={em.port} onChange={(e) => sm("port")(+e.target.value)} /></Field>
          <Field label="نام کاربری"><input dir="ltr" className={inp} value={em.username} onChange={(e) => sm("username")(e.target.value)} /></Field>
          <Field label={`رمز عبور${em.password_set ? " (ذخیره شده؛ برای تغییر بنویسید)" : ""}`}><input dir="ltr" type="password" autoComplete="new-password" className={inp} value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
          <Field label="آدرس فرستنده"><input dir="ltr" className={inp} value={em.from_addr} onChange={(e) => sm("from_addr")(e.target.value)} placeholder="no-reply@example.com" /></Field>
          <Field label="امنیت اتصال"><select className={inp} value={em.security} onChange={(e) => sm("security")(e.target.value)}><option value="starttls">STARTTLS (۵۸۷)</option><option value="ssl">SSL/TLS (۴۶۵)</option><option value="none">بدون رمزنگاری</option></select></Field>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <button disabled={busy === "em"} className={btn} onClick={() => send("/api/v1/admin/integrations/email", { enabled: em.enabled, host: em.host, port: em.port, username: em.username, password: pw === "" ? null : pw, from_addr: em.from_addr, security: em.security }, "تنظیمات ایمیل ذخیره شد", "em")}>ذخیره</button>
          <input dir="ltr" className={`${inp} max-w-[14rem]`} value={to} onChange={(e) => setTo(e.target.value)} placeholder="ایمیل برای تست" />
          <button disabled={!to || busy === "emt"} className={ghost} onClick={() => send("/api/v1/admin/integrations/email/test", { to }, "ایمیل تست ارسال شد", "emt")}>ارسال تست</button>
        </div>
      </div>
      <div className="space-y-3 rounded-xl border border-[var(--ln)] p-4">
        <div className="flex items-center justify-between"><b>بکاپ</b></div>
        <p className="text-xs text-[var(--mu)]">بکاپ محلی همیشه فعال است (رمزگذاری‌شده، روزانه ۰۲:۰۰ UTC، نگهداری {local?.retention_days} روز در <code dir="ltr">{local?.dir}</code>). کپی خارج از سرور روی S3 اختیاری است.</p>
        <Toggle on={s3.enabled} set={s3s("enabled")} label={s3.enabled ? "کپی روی S3 فعال" : "کپی روی S3 غیرفعال"} />
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Endpoint (برای S3 سازگار)"><input dir="ltr" className={inp} value={s3.endpoint} onChange={(e) => s3s("endpoint")(e.target.value)} placeholder="https://s3.example.com" /></Field>
          <Field label="Region"><input dir="ltr" className={inp} value={s3.region} onChange={(e) => s3s("region")(e.target.value)} placeholder="us-east-1" /></Field>
          <Field label="Bucket"><input dir="ltr" className={inp} value={s3.bucket} onChange={(e) => s3s("bucket")(e.target.value)} /></Field>
          <Field label="Prefix"><input dir="ltr" className={inp} value={s3.prefix} onChange={(e) => s3s("prefix")(e.target.value)} /></Field>
          <Field label="Access Key"><input dir="ltr" className={inp} value={s3.access_key} onChange={(e) => s3s("access_key")(e.target.value)} /></Field>
          <Field label={`Secret Key${s3.secret_key_set ? " (ذخیره شده؛ برای تغییر بنویسید)" : ""}`}><input dir="ltr" type="password" autoComplete="new-password" className={inp} value={sk} onChange={(e) => setSk(e.target.value)} /></Field>
        </div>
        <div className="flex gap-2">
          <button disabled={busy === "s3"} className={btn} onClick={() => send("/api/v1/admin/integrations/backup-s3", { enabled: s3.enabled, endpoint: s3.endpoint, region: s3.region, bucket: s3.bucket, prefix: s3.prefix, access_key: s3.access_key, secret_key: sk === "" ? null : sk }, "تنظیمات S3 ذخیره شد", "s3")}>ذخیره</button>
          <button disabled={busy === "s3t"} className={ghost} onClick={() => send("/api/v1/admin/integrations/backup-s3/test", {}, "اتصال به S3 موفق بود", "s3t")}>تست اتصال</button>
        </div>
      </div>
    </div>
  </section>;
}

function ChangeAdminPassword({ api, toast }) {
  const [v, setV] = useState({ current: "", next: "", confirm: "" });
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (v.next.length < 8) return toast("رمز جدید باید حداقل ۸ کاراکتر باشد");
    if (v.next !== v.confirm) return toast("تکرار رمز جدید یکسان نیست");
    setBusy(true);
    const r = await authFetch(api.base, "/api/v1/auth/admin/password", { method: "POST", body: JSON.stringify({ current_password: v.current, new_password: v.next }) });
    const d = await r.json().catch(() => ({}));
    setBusy(false);
    if (!r.ok) return toast(d?.error?.message || d?.detail?.message || "تغییر رمز ناموفق بود");
    setV({ current: "", next: "", confirm: "" });
    toast("رمز ادمین با موفقیت تغییر کرد");
  };
  return <section className={`${box} space-y-4 p-5`}>
    <div><h3 className="font-extrabold">امنیت حساب ادمین</h3><p className="mt-1 text-xs text-[var(--mu)]">برای تغییر رمز، رمز فعلی لازم است. توکن نشست فعلی حفظ می‌شود.</p></div>
    <div className="grid gap-3 md:grid-cols-3">
      <Field label="رمز فعلی"><input dir="ltr" type="password" autoComplete="current-password" className={inp} value={v.current} onChange={(e) => setV({ ...v, current: e.target.value })} /></Field>
      <Field label="رمز جدید"><input dir="ltr" type="password" autoComplete="new-password" className={inp} value={v.next} onChange={(e) => setV({ ...v, next: e.target.value })} /></Field>
      <Field label="تکرار رمز جدید"><input dir="ltr" type="password" autoComplete="new-password" className={inp} value={v.confirm} onChange={(e) => setV({ ...v, confirm: e.target.value })} /></Field>
    </div>
    <button disabled={busy || !v.current || !v.next || !v.confirm} className={btn} onClick={submit}>{busy ? "در حال ذخیره..." : "تغییر رمز"}</button>
  </section>;
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
    if (!(await confirmDialog(`مقدار «${key}» تغییر کند؟`, { title: "تغییر تنظیم سیستم", ok: "ذخیره" }))) return;
    const r = await flags.call(`/api/v1/admin/settings/${key}`, { method: "PUT", body: JSON.stringify({ value }) });
    if (r.ok) { toast("تنظیم ذخیره شد"); setTick((x) => x + 1); } else toast("ذخیره ناموفق بود");
  };
  return <div className="space-y-5"><ChangeAdminPassword api={api} toast={toast} /><Integrations api={api} toast={toast} /><Table title="Feature Flags" cols={["کلید", "محدوده", "فعال", ""]} rows={flags.rows.map((f) => [f.key, `${f.scope_type}:${f.scope_id}`, f.enabled ? "بله" : "خیر", <button className={ghost} onClick={() => setFlag(f)}>{f.enabled ? "خاموش" : "روشن"}</button>])} />
    <section className={`${box} overflow-hidden`}><h3 className="px-5 py-4 font-extrabold">تنظیمات سیستم <span className="text-xs font-normal text-[var(--mu)]">(مقدار به‌صورت JSON)</span></h3>{Object.entries(obj).map(([k, v]) => <SettingRow key={k} k={k} v={v} save={save} />)}</section></div>;
}

function Audit({ api, toast }) {
  const { rows } = useList(api, "/api/v1/admin/audit", toast);
  return <Table title="لاگ ممیزی" cols={["زمان", "عملیات", "نقش", "موجودیت", "Correlation"]} rows={rows.map((a) => [dt(a.created_at), a.action, a.actor_type, `${a.entity_type || ""} ${String(a.entity_id || "").slice(0, 8)}`, <span className="text-xs">{String(a.correlation_id || "").slice(0, 8)}</span>])} />;
}

function Reviews({ api, toast }) {
  const { rows, call, reload } = useList(api, "/api/v1/admin/identity-link-reviews", toast);
  const dismiss = async (id) => { const r = await call(`/api/v1/admin/identity-link-reviews/${id}/dismiss`, { method: "POST" }); r.ok ? (toast("رد شد"), reload()) : toast("ناموفق"); };
  return <Table title="بررسی لینک هویت" cols={["ایمیل", "ارائه‌دهنده", "دلیل", "وضعیت", ""]} rows={rows.map((r) => [r.email, r.provider, r.reason, r.status, <button className={ghost} onClick={() => dismiss(r.id)}>رد کردن</button>])} />;
}


const ask = (m) => promptDialog(m, { title: "ثبت دلیل" });
function Orders({ api, toast }) {
  const { rows, call, reload } = useList(api, "/api/v1/admin/orders", toast);
  const act = async (o, kind, label) => {
    const reason = kind === "retry" ? "" : await ask(`دلیل ${label} را وارد کنید.`); if (reason === null) return;
    if (kind === "refund" && !(await confirmDialog("استرداد این سفارش انجام شود؟ این عملیات مالی است.", { title: "استرداد سفارش", danger: true, ok: "استرداد" }))) return;
    const r = await call(`/api/v1/admin/orders/${o.id}/${kind}`, { method: "POST", body: JSON.stringify({ reason }) });
    if (r.ok) { toast(`${label} ثبت شد`); reload(); } else toast(`${label} ناموفق بود`);
  };
  return <Table title="سفارش‌ها" cols={["شماره", "Store", "مبلغ", "وضعیت", "بررسی", "اقدام"]} rows={rows.map((o) => [o.number, String(o.store_id || "").slice(0, 8), `${money(o.total)} ${o.currency || ""}`, o.status, o.needs_review ? "بله" : "خیر",
    <div className="flex gap-1.5"><button className={ghost} onClick={() => act(o, "retry", "تلاش مجدد")}>تلاش مجدد</button><button className={ghost} onClick={() => act(o, "manual-review", "بررسی دستی")}>بررسی دستی</button><button className={`${ghost} btn-d`} onClick={() => act(o, "refund", "استرداد")}>استرداد</button></div>])} />;
}

function Payments({ api, toast }) {
  const { rows, call, reload } = useList(api, "/api/v1/admin/payments", toast);
  const review = async (p, approve) => {
    const reason = approve ? "" : await ask("دلیل رد پرداخت را وارد کنید."); if (reason === null) return;
    const r = await call(`/api/v1/admin/payments/${p.id}/review`, { method: "POST", body: JSON.stringify({ approve, reason }) });
    if (r.ok) { toast(approve ? "پرداخت تأیید شد" : "پرداخت رد شد"); reload(); } else toast("بررسی ناموفق بود");
  };
  const view = async (p) => { const r = await call(`/api/v1/admin/payments/${p.id}/receipt`); if (!r.ok) return toast("نمایش رسید ناموفق بود"); const url = URL.createObjectURL(await r.blob()); window.open(url, "_blank", "noopener"); setTimeout(() => URL.revokeObjectURL(url), 60000); };
  const pending = (p) => ["pending", "review", "receipt_submitted", "awaiting_review"].includes(p.status) && p.has_receipt;
  return <Table title="پرداخت‌ها" cols={["مبلغ", "درگاه", "وضعیت", "رسید", "اقدام"]} rows={rows.map((p) => [`${money(p.amount)} ${p.currency}`, p.provider, p.status, p.has_receipt ? <button className={ghost} onClick={() => view(p)}>مشاهده رسید</button> : "ندارد",
    pending(p) ? <div className="flex gap-1.5"><button className={ghost} onClick={() => review(p, true)}>تأیید</button><button className={`${ghost} btn-d`} onClick={() => review(p, false)}>رد</button></div> : "-"])} />;
}

function Tickets({ api, toast }) {
  const { rows, call, reload } = useList(api, "/api/v1/admin/tickets", toast);
  const [sel, setSel] = useState(null); const [msgs, setMsgs] = useState([]); const [text, setText] = useState("");
  const open = async (t) => { setSel(t); const r = await call(`/api/v1/tickets/${t.id}/messages`); setMsgs(r.ok ? await r.json() : []); };
  const send = async () => { const r = await call(`/api/v1/tickets/${sel.id}/messages`, { method: "POST", body: JSON.stringify({ body: text }) }); if (r.ok) { setText(""); open(sel); reload(); } else toast("ارسال پاسخ ناموفق بود"); };
  if (!sel) return <Table title="تیکت‌ها" cols={["موضوع", "Store", "وضعیت", "آخرین تغییر", ""]} rows={rows.map((t) => [t.subject, String(t.store_id || "").slice(0, 8), t.status, dt(t.updated_at), <button className={ghost} onClick={() => open(t)}>مشاهده و پاسخ</button>])} />;
  return <section className={`${box} p-5`}><button className="text-sm font-bold text-[var(--ac)]" onClick={() => setSel(null)}>→ بازگشت</button><h3 className="mt-2 font-extrabold">{sel.subject}</h3>
    <div className="mt-4 space-y-3">{msgs.map((m) => <div key={m.id} className={`max-w-[80%] rounded-2xl p-3 text-sm leading-7 ${m.is_staff ? "mr-auto bg-[var(--okb)] text-[var(--tx)]" : "bg-[var(--mb)]"}`}>{m.body}<div className="mt-1 text-[10px] text-[var(--mu)]">{m.is_staff ? "پشتیبانی" : "مشتری"} · {new Date(m.created_at).toLocaleString("fa-IR")}</div></div>)}</div>
    <div className="mt-4 flex gap-2"><input className={inp} value={text} onChange={(e) => setText(e.target.value)} placeholder="پاسخ پشتیبانی…" /><button disabled={!text.trim()} className={btn} onClick={send}>ارسال</button></div></section>;
}

export const extraRoutes = { "سفارش‌ها": Orders, "پرداخت‌ها": Payments, "تیکت‌ها": Tickets, "محصولات VPN": Products, "پنل‌ها": PanelsView, "گروه‌های پنل VPN": PanelGroups, "کوپن‌ها": Coupons, "تنظیمات": Settings, "ممیزی": Audit, "بررسی هویت": Reviews };
