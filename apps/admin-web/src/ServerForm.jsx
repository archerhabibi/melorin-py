import { useState } from "react";
import { authFetch } from "./api.js";
import { Save, X } from "lucide-react";

const EMPTY = { name: "", panel_id: "", location: "", capacity: "", product_codes: "", allow_test: true };

// Creates a VPN server under an existing panel (POST /api/v1/admin/servers).
export function ServerForm({ api, panels, toast, onClose, onSaved }) {
  const [f, setF] = useState({ ...EMPTY, panel_id: panels[0]?.id || "" });
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  const valid = f.name.trim() && f.panel_id && Number(f.capacity) > 0;

  const submit = async () => {
    if (!valid || busy) return;
    setBusy(true);
    const body = {
      name: f.name.trim(),
      panel_id: f.panel_id,
      location: f.location.trim() || null,
      capacity: Number(f.capacity),
      product_codes: f.product_codes.split(",").map((s) => s.trim()).filter(Boolean),
      allow_test: f.allow_test,
    };
    try {
      const r = await authFetch(api.base, "/api/v1/admin/servers", { method: "POST", body: JSON.stringify(body) });
      if (r.ok) {
        toast?.("سرور ثبت شد");
        onSaved?.();
        onClose();
      } else {
        let msg = "ثبت سرور ناموفق بود";
        try { const d = await r.json(); msg = d?.error?.message || (typeof d?.detail === "string" ? d.detail : msg); } catch { /* keep default */ }
        toast?.(msg);
      }
    } catch {
      toast?.("ارتباط با سرور برقرار نشد");
    } finally {
      setBusy(false);
    }
  };

  if (!panels.length) {
    return <section className="card space-y-3 p-4">
      <div className="flex items-center justify-between"><h3 className="font-extrabold">افزودن سرور</h3><button className="btn btn-g !py-2 !text-sm" onClick={onClose}><X size={14} />بستن</button></div>
      <p className="text-sm text-[var(--mu)]">ابتدا یک پنل اضافه کنید؛ سرور باید زیر یک پنل ثبت شود.</p>
    </section>;
  }

  return <section className="card space-y-4 p-4">
    <div className="flex items-center justify-between"><h3 className="font-extrabold">افزودن سرور</h3><button className="btn btn-g !py-2 !text-sm" onClick={onClose}><X size={14} />بستن</button></div>
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="space-y-1"><span className="text-xs font-bold text-[var(--mu)]">نام سرور *</span>
        <input className="inp" value={f.name} onChange={set("name")} placeholder="مثلاً Germany-1" /></label>
      <label className="space-y-1"><span className="text-xs font-bold text-[var(--mu)]">پنل *</span>
        <select className="inp" value={f.panel_id} onChange={set("panel_id")}>
          {panels.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select></label>
      <label className="space-y-1"><span className="text-xs font-bold text-[var(--mu)]">موقعیت (اختیاری)</span>
        <input className="inp" value={f.location} onChange={set("location")} placeholder="مثلاً آلمان" /></label>
      <label className="space-y-1"><span className="text-xs font-bold text-[var(--mu)]">ظرفیت *</span>
        <input className="inp" inputMode="numeric" value={f.capacity} onChange={set("capacity")} placeholder="مثلاً 100" /></label>
      <label className="space-y-1 sm:col-span-2"><span className="text-xs font-bold text-[var(--mu)]">کدهای محصول (با کاما جدا کنید، اختیاری)</span>
        <input className="inp" dir="ltr" value={f.product_codes} onChange={set("product_codes")} placeholder="vpn-1m, vpn-3m" /></label>
    </div>
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.allow_test} onChange={set("allow_test")} />اکانت تست برای این سرور مجاز باشد</label>
    <div className="flex justify-end">
      <button className="btn" disabled={!valid || busy} onClick={submit}><Save size={15} />{busy ? "در حال ثبت..." : "ثبت سرور"}</button>
    </div>
  </section>;
}
