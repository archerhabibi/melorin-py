import { Suspense, useEffect, useState } from "react";
import { extraRoutes } from "./AdminExtra.jsx";
import { authFetch } from "./api.js";
import { Badge, isStatus } from "./ui.jsx";

function SectionFallback() {
  return <div className="card p-6" role="status" aria-live="polite" aria-label="در حال بارگذاری بخش"><div className="skel h-5 w-full" /><div className="skel mt-3 h-5 w-2/3" /></div>;
}

const money = (n) => new Intl.NumberFormat("fa-IR").format(n || 0);

export function AdminSectionView({ section, api, toast }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [term, setTerm] = useState("");
  const Extra = extraRoutes[section];
  const routes = {
    "کاربران": "/api/v1/admin/users",
    "تیکت‌ها": "/api/v1/admin/tickets",
    "فروشگاه‌ها": "/api/v1/admin/stores",
    "پرداخت‌ها": "/api/v1/admin/payments",
    "سفارش‌ها": "/api/v1/admin/orders",
    "اکانت‌های VPN": "/api/v1/admin/vpn-accounts",
  };
  useEffect(() => {
    const path = routes[section];
    if (!path) return;
    setLoading(true);
    const query = section === "اکانت‌های VPN" && term.trim() ? `?q=${encodeURIComponent(term.trim())}` : "";
    const timer = setTimeout(() => authFetch(api.base, path + query)
      .then((r) => r.ok ? r.json() : Promise.reject(new Error(String(r.status))))
      .then((data) => setItems(Array.isArray(data) ? data : data.items || []))
      .catch(() => toast(`دریافت ${section} ناموفق بود`))
      .finally(() => setLoading(false)), term ? 300 : 0);
    return () => clearTimeout(timer);
  }, [section, api.base, term]);

  if (Extra) return <Suspense fallback={<SectionFallback />}><Extra api={api} toast={toast} /></Suspense>;
  if (section === "پرداخت‌ها") return <DataTable title="پرداخت‌ها" loading={loading} columns={["مبلغ", "ارز", "درگاه", "وضعیت", "رسید"]} rows={items.map((x) => [money(x.amount), x.currency, x.provider, x.status, x.has_receipt ? "دارد" : "ندارد"])} />;
  if (section === "سفارش‌ها") return <DataTable title="سفارش‌ها" loading={loading} columns={["شماره", "Store", "مبلغ", "وضعیت", "نیازمند بررسی"]} rows={items.map((x) => [x.number, String(x.store_id || "").slice(0, 8), `${money(x.total)} ${x.currency || ""}`, x.status, x.needs_review ? "بله" : "خیر"])} />;
  if (section === "اکانت‌های VPN") return <div className="space-y-3"><input className="field w-full" type="search" dir="auto" value={term} onChange={(e) => setTerm(e.target.value)} placeholder="جستجو: نام اکانت، نام یا ایمیل مشتری" aria-label="جستجوی اکانت" /><DataTable title="اکانت‌های VPN" loading={loading} columns={["کاربر", "نام کاربری", "وضعیت", "انقضا", "ترافیک"]} rows={items.map((x) => [String(x.user_id || "").slice(0, 8), x.username, x.status, x.expires_at || "نامحدود", `${money(x.traffic_used_bytes)} / ${money(x.traffic_limit_bytes)}`])} /></div>;
  if (section === "کاربران") return <DataTable title="کاربران" loading={loading} columns={["ایمیل", "نام", "فعال", "ادمین"]} rows={items.map((x) => [x.email || "-", x.display_name || "-", x.is_active ? "بله" : "خیر", x.is_super_admin ? "بله" : "خیر"])} />;
  if (section === "تیکت‌ها") return <DataTable title="تیکت‌ها" loading={loading} columns={["موضوع", "Store", "وضعیت", "آخرین تغییر"]} rows={items.map((x) => [x.subject, String(x.store_id || "").slice(0, 8), x.status, x.updated_at])} />;
  if (section === "فروشگاه‌ها") return <DataTable title="فروشگاه‌ها" loading={loading} columns={["نام", "Slug", "نوع", "ارز", "وضعیت"]} rows={items.map((x) => [x.name, x.slug, x.kind, x.currency, x.status])} />;
  return <div className="rounded-2xl border border-[var(--ln)] bg-[var(--sf)] p-6 shadow-xs"><h3 className="font-extrabold">داده‌ای برای این بخش تعریف نشده</h3><p className="mt-2 text-sm text-[var(--mu)]">از داشبورد یا API مرتبط استفاده کنید.</p></div>;
}

function DataTable({ title, columns, rows, loading }) {
  return <section className="card rise overflow-hidden">
    <div className="border-b border-[var(--ln)] px-5 py-4"><h3 className="font-extrabold">{title}</h3><p className="mt-1 text-xs text-[var(--mu)]">داده زنده از Core API</p></div>
    <div className="max-h-[70vh] overflow-auto"><table className="tbl min-w-[680px]"><thead><tr>{columns.map((x) => <th key={x}>{x}</th>)}</tr></thead><tbody>{loading ? Array.from({ length: 5 }, (_, i) => <tr key={i}><td colSpan={columns.length}><div className="skel h-5 w-full" /></td></tr>) : rows.length ? rows.map((row, i) => <tr key={i}>{row.map((x, j) => <td key={j}>{isStatus(x) ? <Badge s={x} /> : String(x ?? "-")}</td>)}</tr>) : <tr><td colSpan={columns.length} className="p-12 text-center text-[var(--mu)]">داده‌ای وجود ندارد</td></tr>}</tbody></table></div>
  </section>;
}
