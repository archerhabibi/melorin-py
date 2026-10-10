import { useEffect, useState } from "react";
import { extraRoutes } from "./AdminExtra.jsx";
import { authFetch } from "./api.js";

const money = (n) => new Intl.NumberFormat("fa-IR").format(n || 0);

export function AdminSectionView({ section, api, toast }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
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
    authFetch(api.base, path)
      .then((r) => r.ok ? r.json() : Promise.reject(new Error(String(r.status))))
      .then((data) => setItems(Array.isArray(data) ? data : data.items || []))
      .catch(() => toast(`دریافت ${section} ناموفق بود`))
      .finally(() => setLoading(false));
  }, [section, api.base]);

  if (Extra) return <Extra api={api} toast={toast} />;
  if (section === "پرداخت‌ها") return <DataTable title="پرداخت‌ها" loading={loading} columns={["مبلغ", "ارز", "درگاه", "وضعیت", "رسید"]} rows={items.map((x) => [money(x.amount), x.currency, x.provider, x.status, x.has_receipt ? "دارد" : "ندارد"])} />;
  if (section === "سفارش‌ها") return <DataTable title="سفارش‌ها" loading={loading} columns={["شماره", "Store", "مبلغ", "وضعیت", "نیازمند بررسی"]} rows={items.map((x) => [x.number, String(x.store_id || "").slice(0, 8), `${money(x.total)} ${x.currency || ""}`, x.status, x.needs_review ? "بله" : "خیر"])} />;
  if (section === "اکانت‌های VPN") return <DataTable title="اکانت‌های VPN" loading={loading} columns={["کاربر", "نام کاربری", "وضعیت", "انقضا", "ترافیک"]} rows={items.map((x) => [String(x.user_id || "").slice(0, 8), x.username, x.status, x.expires_at || "نامحدود", `${money(x.traffic_used_bytes)} / ${money(x.traffic_limit_bytes)}`])} />;
  if (section === "کاربران") return <DataTable title="کاربران" loading={loading} columns={["ایمیل", "نام", "فعال", "ادمین"]} rows={items.map((x) => [x.email || "-", x.display_name || "-", x.is_active ? "بله" : "خیر", x.is_super_admin ? "بله" : "خیر"])} />;
  if (section === "تیکت‌ها") return <DataTable title="تیکت‌ها" loading={loading} columns={["موضوع", "Store", "وضعیت", "آخرین تغییر"]} rows={items.map((x) => [x.subject, String(x.store_id || "").slice(0, 8), x.status, x.updated_at])} />;
  if (section === "فروشگاه‌ها") return <DataTable title="فروشگاه‌ها" loading={loading} columns={["نام", "Slug", "نوع", "ارز", "وضعیت"]} rows={items.map((x) => [x.name, x.slug, x.kind, x.currency, x.status])} />;
  return <div className="rounded-2xl border border-[#dce0dc] bg-white p-6 shadow-sm"><h3 className="font-extrabold">داده‌ای برای این بخش تعریف نشده</h3><p className="mt-2 text-sm text-[#71808b]">از داشبورد یا API مرتبط استفاده کنید.</p></div>;
}

function DataTable({ title, columns, rows, loading }) {
  return <section className="overflow-hidden rounded-2xl border border-[#dce0dc] bg-white shadow-sm">
    <div className="border-b border-[#e6e8e5] px-5 py-4"><h3 className="font-extrabold">{title}</h3><p className="mt-1 text-xs text-[#71808b]">داده زنده از Core API</p></div>
    <div className="overflow-x-auto"><table className="w-full min-w-[680px] text-right text-sm"><thead className="bg-[#fafbf9] text-xs text-[#55636e]"><tr>{columns.map((x) => <th key={x} className="px-5 py-3 font-medium">{x}</th>)}</tr></thead><tbody>{loading ? <tr><td colSpan={columns.length} className="p-10 text-center">در حال دریافت...</td></tr> : rows.length ? rows.map((row, i) => <tr key={i} className="border-t border-[#edf0ed]">{row.map((x, j) => <td key={j} className="px-5 py-4">{String(x ?? "-")}</td>)}</tr>) : <tr><td colSpan={columns.length} className="p-10 text-center text-[#71808b]">داده‌ای وجود ندارد</td></tr>}</tbody></table></div>
  </section>;
}
