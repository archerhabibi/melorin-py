import { useEffect, useState } from "react";
const fa = (n) => new Intl.NumberFormat("fa-IR").format(n || 0);
const J = { "Content-Type": "application/json" };
const card = "rounded-2xl border border-[#d9ddd4] bg-white p-5";
const btn = "rounded-xl bg-[#10233f] px-4 py-2.5 text-sm font-bold text-white disabled:opacity-40";
const ghost = "rounded-lg border border-[#d9ddd4] px-3 py-1.5 text-xs font-bold";
const inp = "w-full rounded-xl border border-[#d9ddd4] p-2.5 text-sm outline-none focus:border-[#db7b54]";
const SCOPES = ["catalog:read", "customers:read", "customers:wallet:write", "orders:read", "wallet:read", "reports:read"];
const EVENTS = ["order.completed", "order.refunded", "order.provisioning_failed", "payment.succeeded", "payment.failed", "wallet.changed", "vpn_account.expired", "vpn_account.near_expiry", "reseller.debt"];

function useGet(coreFetch, path, deps = []) {
  const [d, setD] = useState(null); const [t, setT] = useState(0);
  useEffect(() => { if (!path) return; coreFetch(path).then((r) => r.ok ? r.json() : Promise.reject()).then(setD).catch(() => setD([])); }, [path, t, ...deps]);
  return [d, () => setT((x) => x + 1)];
}

function Overview({ coreFetch, base }) {
  const [p] = useGet(coreFetch, `${base}/profile`); const [rep] = useGet(coreFetch, `${base}/reports`);
  const w = p?.main_wallet;
  return <div className="grid gap-4 md:grid-cols-3">
    <div className="rounded-2xl bg-[#10233f] p-5 text-white"><div className="text-sm text-white/60">اعتبار کیف پول اصلی</div><div className="mt-2 text-2xl font-extrabold" dir="ltr">{fa(w?.balance)} {w?.currency}</div><div className="mt-2 text-xs text-[#f7c85c]">وضعیت بدهی: {w?.debt_state || "—"}</div></div>
    <div className={card}><div className="text-sm text-[#687582]">سقف بدهی</div><div className="mt-2 text-2xl font-extrabold">{fa(p?.debt_limit)}</div><div className="mt-2 text-xs">فروش: {p?.sales_enabled ? "فعال" : "غیرفعال"} · API: {p?.api_enabled ? "فعال" : "غیرفعال"}</div></div>
    <div className={card}><div className="text-sm text-[#687582]">فروشگاه</div><div className="mt-2 text-xl font-extrabold">{p?.store_name || "—"}</div><div className="mt-2 text-xs">ارز: {p?.store_currency}</div></div>
    <div className={`${card} md:col-span-3`}><h4 className="font-extrabold">گزارش سفارش‌ها</h4><table className="mt-3 w-full text-right text-sm"><thead className="text-xs text-[#687582]"><tr><th>وضعیت</th><th>تعداد</th><th>فروش</th><th>بهای تمام‌شده</th></tr></thead><tbody>{(rep?.orders || []).map((o) => <tr key={o.status} className="border-t border-[#ece9de]"><td className="py-2">{o.status}</td><td>{fa(o.count)}</td><td>{fa(o.total)}</td><td>{fa(o.reseller_cost)}</td></tr>)}</tbody></table></div>
  </div>;
}

function Customers({ coreFetch, base, notify }) {
  const [rows, reload] = useGet(coreFetch, `${base}/customers`);
  const adjust = async (c) => {
    const amount = Number(window.prompt("مبلغ (مثبت = شارژ، منفی = اصلاح):", "")); if (!amount) return;
    const reason = window.prompt("دلیل:", ""); if (!reason || reason.length < 3) return;
    const r = await coreFetch(`${base}/customers/${c.user_id}/wallet`, { method: "POST", headers: J, body: JSON.stringify({ amount, reason, idempotency_key: `rs-${crypto.randomUUID()}` }) });
    notify(r.ok ? "کیف پول مشتری به‌روز شد" : "عملیات ناموفق بود"); r.ok && reload();
  };
  return <div className={`${card} overflow-x-auto`}><table className="w-full min-w-[520px] text-right text-sm"><thead className="text-xs text-[#687582]"><tr><th>نام</th><th>ایمیل</th><th>وضعیت</th><th></th></tr></thead><tbody>{(rows || []).map((c) => <tr key={c.user_id} className="border-t border-[#ece9de]"><td className="py-3">{c.display_name || "-"}</td><td className="latin">{c.email || "-"}</td><td>{c.status}</td><td><button className={ghost} onClick={() => adjust(c)}>شارژ/اصلاح کیف پول</button></td></tr>)}{rows && !rows.length && <tr><td colSpan={4} className="p-8 text-center text-[#687582]">مشتری‌ای وجود ندارد</td></tr>}</tbody></table></div>;
}

function Payments({ coreFetch, base, notify }) {
  const [rows, reload] = useGet(coreFetch, `${base}/payments`);
  const review = async (p, approve) => {
    const note = approve ? null : window.prompt("دلیل رد:", ""); if (!approve && note === null) return;
    const r = await coreFetch(`${base}/payments/${p.id}/review`, { method: "POST", headers: J, body: JSON.stringify({ approve, note }) });
    notify(r.ok ? "ثبت شد" : "بررسی ناموفق بود"); r.ok && reload();
  };
  return <div className={`${card} overflow-x-auto`}><table className="w-full min-w-[520px] text-right text-sm"><thead className="text-xs text-[#687582]"><tr><th>مبلغ</th><th>درگاه</th><th>وضعیت</th><th>رسید</th><th></th></tr></thead><tbody>{(rows || []).map((p) => <tr key={p.id} className="border-t border-[#ece9de]"><td className="py-3">{fa(p.amount)} {p.currency}</td><td>{p.provider}</td><td>{p.status}</td><td>{p.has_receipt ? "دارد" : "ندارد"}</td><td>{p.status !== "succeeded" && p.status !== "failed" && p.has_receipt ? <span className="flex gap-1.5"><button className={ghost} onClick={() => review(p, true)}>تأیید</button><button className={ghost} onClick={() => review(p, false)}>رد</button></span> : ""}</td></tr>)}{rows && !rows.length && <tr><td colSpan={5} className="p-8 text-center text-[#687582]">پرداختی وجود ندارد</td></tr>}</tbody></table></div>;
}

function Secret({ title, value, onClose }) {
  return <div className="mb-4 rounded-2xl border border-[#f0c6b7] bg-[#fff2ee] p-4 text-sm"><b>{title}</b> — فقط یک‌بار نمایش داده می‌شود:<code dir="ltr" className="latin mt-2 block break-all rounded-xl bg-white p-3 text-xs">{value}</code><div className="mt-2 flex gap-2"><button className={ghost} onClick={() => navigator.clipboard?.writeText(value)}>کپی</button><button className={ghost} onClick={onClose}>بستن</button></div></div>;
}

function Keys({ coreFetch, base, notify }) {
  const [rows, reload] = useGet(coreFetch, `${base}/api-credentials`);
  const [f, setF] = useState({ name: "", scopes: ["catalog:read", "orders:read"], rate: 120, ips: "" });
  const [secret, setSecret] = useState(null);
  const create = async () => {
    const r = await coreFetch(`${base}/api-credentials`, { method: "POST", headers: J, body: JSON.stringify({ name: f.name, scopes: f.scopes, rate_limit_per_minute: +f.rate, ip_allowlist: f.ips ? f.ips.split(/[\s,]+/).filter(Boolean) : null }) });
    if (r.ok) { const d = await r.json(); setSecret(d.api_key); setF({ ...f, name: "" }); reload(); } else notify("ساخت کلید ناموفق بود");
  };
  const act = async (c, a) => { if (a === "revoke" && !window.confirm("کلید برای همیشه ابطال شود؟")) return; const r = await coreFetch(`${base}/api-credentials/${c.id}/${a}`, { method: "POST" }); if (r.ok) { if (a === "rotate") setSecret((await r.json()).api_key); reload(); } else notify("عملیات ناموفق بود"); };
  const tog = (s) => setF({ ...f, scopes: f.scopes.includes(s) ? f.scopes.filter((x) => x !== s) : [...f.scopes, s] });
  return <div>{secret && <Secret title="کلید API" value={secret} onClose={() => setSecret(null)} />}
    <div className={`${card} mb-4`}><h4 className="font-extrabold">کلید جدید</h4><div className="mt-3 grid gap-3 md:grid-cols-3"><input className={inp} placeholder="نام" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /><input className={inp} type="number" placeholder="محدودیت در دقیقه" value={f.rate} onChange={(e) => setF({ ...f, rate: e.target.value })} /><input dir="ltr" className={inp} placeholder="IP allowlist (اختیاری)" value={f.ips} onChange={(e) => setF({ ...f, ips: e.target.value })} /></div>
      <div className="mt-3 flex flex-wrap gap-2">{SCOPES.map((s) => <label key={s} className="latin flex items-center gap-1 rounded-full bg-[#f4f1e8] px-3 py-1 text-xs"><input type="checkbox" checked={f.scopes.includes(s)} onChange={() => tog(s)} />{s}</label>)}</div><button disabled={f.name.length < 2 || !f.scopes.length} onClick={create} className={`${btn} mt-4`}>ساخت کلید</button></div>
    <div className={`${card} overflow-x-auto`}><table className="w-full min-w-[560px] text-right text-sm"><thead className="text-xs text-[#687582]"><tr><th>نام</th><th>پیشوند</th><th>وضعیت</th><th>آخرین استفاده</th><th></th></tr></thead><tbody>{(rows || []).map((c) => <tr key={c.id} className="border-t border-[#ece9de]"><td className="py-3">{c.name}</td><td className="latin">{c.key_prefix}…</td><td>{c.status}</td><td>{c.last_used_at ? new Date(c.last_used_at).toLocaleString("fa-IR") : "—"}</td><td className="flex flex-wrap gap-1.5 py-2">{c.status !== "revoked" && <><button className={ghost} onClick={() => act(c, "rotate")}>چرخش</button><button className={ghost} onClick={() => act(c, c.status === "active" ? "disable" : "activate")}>{c.status === "active" ? "غیرفعال" : "فعال"}</button><button className={ghost} onClick={() => act(c, "revoke")}>ابطال</button></>}</td></tr>)}</tbody></table></div></div>;
}

function Hooks({ coreFetch, base, notify }) {
  const [rows, reload] = useGet(coreFetch, `${base}/webhooks`);
  const [f, setF] = useState({ url: "", events: ["order.completed"] });
  const [secret, setSecret] = useState(null); const [dl, setDl] = useState(null);
  const create = async () => { const r = await coreFetch(`${base}/webhooks`, { method: "POST", headers: J, body: JSON.stringify(f) }); if (r.ok) { const d = await r.json(); d.secret && setSecret(d.secret); setF({ ...f, url: "" }); reload(); } else notify("ساخت وبهوک ناموفق بود (URL باید عمومی و HTTPS باشد)"); };
  const call = async (e, p, m = "POST", ok = "انجام شد") => { const r = await coreFetch(`${base}/webhooks/${e.id}${p}`, { method: m, headers: J }); if (r.ok) { notify(ok); if (p === "/rotate-secret") { const d = await r.json(); d.secret && setSecret(d.secret); } reload(); } else notify("ناموفق بود"); };
  const toggleStatus = async (e) => { const r = await coreFetch(`${base}/webhooks/${e.id}`, { method: "PATCH", headers: J, body: JSON.stringify({ status: e.status === "active" ? "disabled" : "active" }) }); r.ok ? reload() : notify("ناموفق بود"); };
  const deliveries = async (e) => { const r = await coreFetch(`${base}/webhooks/${e.id}/deliveries`); setDl({ e, rows: r.ok ? await r.json() : [] }); };
  const redeliver = async (d) => { const r = await coreFetch(`${base}/webhooks/${dl.e.id}/deliveries/${d.id}/redeliver`, { method: "POST" }); notify(r.ok ? "در صف ارسال مجدد قرار گرفت" : "ناموفق بود"); };
  const tog = (s) => setF({ ...f, events: f.events.includes(s) ? f.events.filter((x) => x !== s) : [...f.events, s] });
  return <div>{secret && <Secret title="Signing secret" value={secret} onClose={() => setSecret(null)} />}
    <div className={`${card} mb-4`}><h4 className="font-extrabold">وبهوک جدید</h4><input dir="ltr" className={`${inp} mt-3`} placeholder="https://example.com/hook" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} /><div className="mt-3 flex flex-wrap gap-2">{EVENTS.map((s) => <label key={s} className="latin flex items-center gap-1 rounded-full bg-[#f4f1e8] px-3 py-1 text-xs"><input type="checkbox" checked={f.events.includes(s)} onChange={() => tog(s)} />{s}</label>)}</div><button disabled={!f.url || !f.events.length} onClick={create} className={`${btn} mt-4`}>ساخت وبهوک</button></div>
    {dl ? <div className={card}><button className="text-sm font-bold text-[#db7b54]" onClick={() => setDl(null)}>→ بازگشت</button><h4 className="mt-2 font-extrabold latin" dir="ltr">{dl.e.url}</h4><table className="mt-3 w-full text-right text-sm"><thead className="text-xs text-[#687582]"><tr><th>رویداد</th><th>وضعیت</th><th>تلاش</th><th>کد</th><th></th></tr></thead><tbody>{dl.rows.map((d) => <tr key={d.id} className="border-t border-[#ece9de]"><td className="latin py-2">{d.event_type}</td><td>{d.status}</td><td>{d.attempts}</td><td>{d.last_status_code ?? "—"}</td><td><button className={ghost} onClick={() => redeliver(d)}>ارسال مجدد</button></td></tr>)}</tbody></table></div>
      : <div className="space-y-3">{(rows || []).map((e) => <div key={e.id} className={card}><div className="latin break-all font-bold" dir="ltr">{e.url}</div><div className="mt-1 text-xs text-[#687582]">{e.status} · خطاهای پیاپی: {e.consecutive_failures} · {(e.events || []).join(", ")}</div><div className="mt-3 flex flex-wrap gap-1.5"><button className={ghost} onClick={() => call(e, "/test", "POST", "رویداد تست ارسال شد")}>تست</button><button className={ghost} onClick={() => deliveries(e)}>گزارش ارسال‌ها</button><button className={ghost} onClick={() => call(e, "/rotate-secret", "POST", "Secret چرخید")}>چرخش Secret</button><button className={ghost} onClick={() => toggleStatus(e)}>{e.status === "active" ? "غیرفعال" : "فعال"}</button><button className={ghost} onClick={() => window.confirm("حذف شود؟") && call(e, "", "DELETE", "حذف شد")}>حذف</button></div></div>)}{rows && !rows.length && <div className="rounded-2xl border border-dashed border-[#cfd3cc] p-8 text-center text-sm text-[#687582]">وبهوکی تعریف نشده</div>}</div>}</div>;
}


function Branding({ coreFetch, base, storeId, notify }) {
  const [b, setB] = useState({ title: "", primary_color: "#10233f", support_url: "" });
  const [msgs, setMsgs] = useState("{}");
  useEffect(() => { coreFetch(`/api/v1/stores/${storeId}`).then((r) => r.ok ? r.json() : {}).then((s) => s.branding && setB((x) => ({ ...x, ...s.branding }))); }, [storeId]);
  const save = async () => {
    let bot_messages; try { bot_messages = JSON.parse(msgs || "{}"); } catch { return notify("پیام‌های ربات باید JSON معتبر باشند"); }
    const body = { branding: b }; if (msgs.trim() && msgs.trim() !== "{}") body.bot_messages = bot_messages;
    const r = await coreFetch(`${base}/branding`, { method: "PATCH", headers: J, body: JSON.stringify(body) });
    notify(r.ok ? "برندینگ ذخیره شد" : "ذخیره ناموفق بود");
  };
  return <div className={card}><h4 className="font-extrabold">برندینگ فروشگاه</h4><div className="mt-3 grid gap-3 md:grid-cols-3"><label className="text-xs font-bold">عنوان<input className={`${inp} mt-1`} value={b.title || ""} onChange={(e) => setB({ ...b, title: e.target.value })} /></label><label className="text-xs font-bold">رنگ اصلی<input type="color" className={`${inp} mt-1 h-11`} value={b.primary_color || "#10233f"} onChange={(e) => setB({ ...b, primary_color: e.target.value })} /></label><label className="text-xs font-bold">لینک پشتیبانی<input dir="ltr" className={`${inp} mt-1`} value={b.support_url || ""} onChange={(e) => setB({ ...b, support_url: e.target.value })} /></label></div>
    <label className="mt-3 block text-xs font-bold">پیام‌های ربات (JSON، اختیاری)<textarea dir="ltr" rows={3} className={`${inp} mt-1 latin`} value={msgs} onChange={(e) => setMsgs(e.target.value)} /></label><button onClick={save} className={`${btn} mt-4`}>ذخیره</button></div>;
}

function PayConfig({ coreFetch, base, notify }) {
  const [rows, reload] = useGet(coreFetch, `${base}/payment-config`);
  const cur = (rows || []).find((r) => r.provider === "manual_card");
  const [f, setF] = useState({ card_number: "", holder: "", bank: "", min_amount: "", max_amount: "", enabled: true });
  useEffect(() => { if (cur) setF((x) => ({ ...x, ...cur.public_config, enabled: cur.is_enabled })); }, [rows]);
  const save = async () => {
    const { enabled, ...pub } = f; ["min_amount", "max_amount"].forEach((k) => { pub[k] = pub[k] === "" ? undefined : Number(pub[k]); });
    const r = await coreFetch(`${base}/payment-config/manual_card`, { method: "PUT", headers: J, body: JSON.stringify({ is_enabled: enabled, public_config: pub }) });
    notify(r.ok ? "اطلاعات کارت ذخیره شد" : "ذخیره ناموفق بود"); r.ok && reload();
  };
  const [zp, setZp] = useState(""); const zcur = (rows || []).find((r) => r.provider === "zarinpal");
  const saveZp = async () => { const r = await coreFetch(`${base}/payment-config/zarinpal`, { method: "PUT", headers: J, body: JSON.stringify({ is_enabled: true, public_config: {}, secret: { merchant_id: zp } }) }); notify(r.ok ? "درگاه ذخیره شد" : "ذخیره ناموفق بود"); r.ok && (setZp(""), reload()); };
  const fld = (k, l, t) => <label className="text-xs font-bold">{l}<input type={t || "text"} dir="ltr" className={`${inp} mt-1`} value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></label>;
  return <div className="grid gap-4 md:grid-cols-2"><div className={card}><h4 className="font-extrabold">کارت‌به‌کارت</h4><div className="mt-3 grid gap-3">{fld("card_number", "شماره کارت")}{fld("holder", "صاحب کارت")}{fld("bank", "بانک")}<div className="grid grid-cols-2 gap-3">{fld("min_amount", "حداقل مبلغ", "number")}{fld("max_amount", "حداکثر مبلغ", "number")}</div><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.enabled} onChange={(e) => setF({ ...f, enabled: e.target.checked })} />فعال</label></div><button onClick={save} className={`${btn} mt-4`}>ذخیره</button></div>
    <div className={card}><h4 className="font-extrabold">درگاه زرین‌پال</h4><p className="mt-2 text-xs text-[#687582]">وضعیت: {zcur ? (zcur.has_secret ? "merchant ID ثبت شده" : "بدون secret") : "تنظیم نشده"} (مقدار ثبت‌شده هرگز نمایش داده نمی‌شود)</p><input dir="ltr" className={`${inp} mt-3`} placeholder="Merchant ID جدید" value={zp} onChange={(e) => setZp(e.target.value)} /><button disabled={!zp} onClick={saveZp} className={`${btn} mt-3`}>ذخیره</button></div></div>;
}

function Apply({ coreFetch, notify, stores }) {
  const choices = (stores || []).filter((s) => s.status !== "suspended");
  const [f, setF] = useState({ store_name: "", message: "", target_store_id: choices.find((s) => s.kind === "main")?.id || "" });
  const send = async () => { const r = await coreFetch("/api/v1/reseller/applications", { method: "POST", headers: J, body: JSON.stringify(f) }); notify(r.ok ? "درخواست ثبت شد؛ منتظر بررسی بمانید" : "ثبت درخواست ناموفق بود (فقط مشتریان فروشگاه اصلی)"); };
  return <div className={`${card} mx-auto max-w-lg`}><h3 className="text-xl font-extrabold">درخواست نمایندگی</h3><p className="mt-2 text-sm text-[#687582]">فقط برای فروشگاهی درخواست بده که عضو فعال آن هستی. برای چند فروشگاه می‌توانی جداگانه درخواست بدهی.</p><select className={`${inp} mt-4`} value={f.target_store_id} onChange={(e) => setF({ ...f, target_store_id: e.target.value })}>{choices.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.kind === "main" ? "اصلی" : "فروشگاه"})</option>)}</select><input className={`${inp} mt-3`} placeholder="نام فروشگاه نمایندگی" value={f.store_name} onChange={(e) => setF({ ...f, store_name: e.target.value })} /><textarea rows={3} className={`${inp} mt-3`} placeholder="توضیحات" value={f.message} onChange={(e) => setF({ ...f, message: e.target.value })} /><button disabled={f.store_name.length < 2 || !f.target_store_id} onClick={send} className={`${btn} mt-3`}>ارسال درخواست</button></div>;
}

const tabs = [["overview", "نمای کلی"], ["customers", "مشتریان"], ["payments", "پرداخت‌ها"], ["keys", "کلیدهای API"], ["hooks", "وبهوک‌ها"], ["settings", "تنظیمات فروشگاه"]];
export default function Reseller({ coreFetch, notify }) {
  const [stores, setStores] = useState(null); const [tab, setTab] = useState("overview");
  useEffect(() => { coreFetch("/api/v1/me/stores").then((r) => r.ok ? r.json() : []).then(setStores).catch(() => setStores([])); }, []);
  const mine = (stores || []).find((s) => s.kind === "reseller" && s.role === "owner");
  const base = mine ? `/api/v1/stores/${mine.id}/reseller` : "";
  return <div className="mx-auto max-w-6xl px-6 pb-16"><div className="mb-6 flex items-center justify-between"><div><div className="text-sm font-bold text-[#db7b54]">پنل نماینده</div><h2 className="text-3xl font-extrabold">{mine?.name || "فروش همکاری"}</h2></div><a href="#/dashboard" className="rounded-full border border-[#cfd3cc] px-4 py-2 text-sm font-semibold">← حساب من</a></div>
    {stores === null ? <p className="text-sm">در حال دریافت…</p> : !mine ? <Apply coreFetch={coreFetch} notify={notify} stores={stores} /> : <>
      <div className="mb-6 flex gap-2 overflow-x-auto">{tabs.map(([k, l]) => <button key={k} onClick={() => setTab(k)} className={`whitespace-nowrap rounded-full px-5 py-2.5 text-sm font-bold ${tab === k ? "bg-[#10233f] text-white" : "bg-white ring-1 ring-[#d9ddd4]"}`}>{l}</button>)}</div>
      {tab === "overview" && <Overview coreFetch={coreFetch} base={base} />}{tab === "customers" && <Customers coreFetch={coreFetch} base={base} notify={notify} />}{tab === "payments" && <Payments coreFetch={coreFetch} base={base} notify={notify} />}{tab === "keys" && <Keys coreFetch={coreFetch} base={base} notify={notify} />}{tab === "hooks" && <Hooks coreFetch={coreFetch} base={base} notify={notify} />}{tab === "settings" && <div className="space-y-4"><Branding coreFetch={coreFetch} base={base} storeId={mine.id} notify={notify} /><PayConfig coreFetch={coreFetch} base={base} notify={notify} /></div>}</>}</div>;
}
