// Subscription link + QR code, always shown together (account cards and the post-purchase result).
import { useEffect, useState } from "react";
import { Copy, Loader2 } from "lucide-react";

// The CSP allows `data:` images but not `blob:`, so the PNG is turned into a data URL.
const toDataUrl = (blob) => new Promise((ok, fail) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = fail; r.readAsDataURL(blob); });
export const linkOf = (a) => a?.subscription_url || (Array.isArray(a?.links) ? a.links[0] : null) || null;

export function SubscriptionCard({ account, coreFetch, notify }) {
  const link = linkOf(account);
  const [qr, setQr] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    setQr(null); setFailed(false);
    if (!account?.id || !link) return undefined;
    coreFetch(`/api/v1/vpn-accounts/${account.id}/qr.png`)
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status)))))
      .then(toDataUrl)
      .then((u) => live && setQr(u))
      .catch(() => live && setFailed(true));
    return () => { live = false; };
  }, [account?.id, link]);
  if (!link) return <p className="mt-4 text-xs text-muted">لینک اشتراک در حال آماده‌سازی است.</p>;
  const copy = () => navigator.clipboard?.writeText(link).then(() => notify?.("کپی شد"));
  return <div className="mt-4 space-y-3">
    <div className="mx-auto grid h-48 w-48 place-items-center rounded-2xl bg-white p-2" aria-label="QR کد اشتراک">
      {qr ? <img src={qr} alt="QR کد اشتراک" className="h-full w-full" /> : failed ? <span className="px-3 text-center text-xs text-muted">QR کد در دسترس نیست؛ از لینک زیر استفاده کنید.</span> : <Loader2 size={22} className="animate-spin text-muted" />}
    </div>
    <p className="text-center text-xs text-muted">برای اتصال سریع، QR کد را در برنامه اسکن کنید.</p>
    <input readOnly value={link} dir="ltr" onFocus={(e) => e.target.select()} className="input latin w-full text-xs" aria-label="لینک اشتراک" />
    <button onClick={copy} className="btn-primary w-full"><Copy size={16} />کپی لینک اشتراک</button>
  </div>;
}

// Shown right after a successful purchase: waits for provisioning, then shows link + QR at the same time.
export function PurchaseResult({ orderId, coreFetch, notify }) {
  const [state, setState] = useState({ phase: "wait" });
  useEffect(() => {
    let live = true, timer;
    const t0 = Date.now();
    const tick = async () => {
      try {
        const o = await (await coreFetch(`/api/v1/orders/${orderId}`)).json();
        if (!live) return;
        if (o.status === "completed" && o.vpn_account_id) {
          const r = await coreFetch(`/api/v1/vpn-accounts/${o.vpn_account_id}`);
          const account = r.ok ? await r.json() : null;
          if (!live) return;
          if (account && linkOf(account)) return setState({ phase: "done", account, order: o });
        } else if (["provisioning_failed", "payment_failed", "cancelled", "refund_pending", "refunded", "manual_review"].includes(o.status)) {
          return setState({ phase: "failed", order: o });
        }
      } catch { /* transient: keep polling */ }
      if (Date.now() - t0 > 90000) return live && setState({ phase: "late" });
      timer = setTimeout(tick, 2000);
    };
    tick();
    return () => { live = false; clearTimeout(timer); };
  }, [orderId]);
  if (state.phase === "done") return <div>
    <p className="mt-2 text-sm font-bold text-mint">✓ خرید شما با موفقیت انجام شد</p>
    <div className="mt-1 text-xs text-muted">اکانت: <b className="latin">{state.account.username}</b> · سفارش: <b className="latin">{state.order.number}</b></div>
    <SubscriptionCard account={state.account} coreFetch={coreFetch} notify={notify} />
  </div>;
  if (state.phase === "failed") return <p className="mt-4 text-sm leading-7 text-danger">ساخت اکانت انجام نشد. اگر مبلغی کسر شده باشد، به‌صورت خودکار به کیف پول برگردانده می‌شود.</p>;
  if (state.phase === "late") return <p className="mt-4 text-sm leading-7 text-muted">ساخت اکانت کمی طول کشیده است. لینک و QR کد به‌محض آماده‌شدن در بخش «اکانت‌های VPN» نمایش داده می‌شود.</p>;
  return <div className="mt-6 flex items-center gap-3 text-sm text-muted"><Loader2 size={18} className="animate-spin" />در حال ساخت اکانت شما…</div>;
}
