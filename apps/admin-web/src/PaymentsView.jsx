// Payments screen — review queue, KPIs, filters, detail drawer and gateway settings.
// Data comes only from GET /api/v1/admin/payments (+ /settings); actions use the existing
// /review, /refund and /receipt endpoints, so no backend change is required.
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check, ChevronDown, Clock, Coins, Copy, CreditCard, Download, Globe, Landmark, Receipt, RefreshCw,
  Settings2, ShieldAlert, Star, TrendingUp, Undo2, Wallet, X, XCircle,
} from "lucide-react";
import { authFetch } from "./api.js";
import { Drawer, Empty, ErrorBar, Field, KpiBar, Paginator, Pills, SearchBox, Section, Stat, Switch, errText, num, tint } from "./kit.jsx";
import { Badge, confirmDialog, dt, promptDialog, sid } from "./ui.jsx";

const PAGE = 15;
const REVIEWABLE = ["pending", "review", "receipt_submitted", "awaiting_review"];

const PROVIDERS = {
  manual_card: { label: "کارت‌به‌کارت", Icon: CreditCard },
  zarinpal: { label: "زرین‌پال", Icon: Landmark },
  external_gateway: { label: "درگاه خارجی", Icon: Globe },
  crypto: { label: "ارز دیجیتال", Icon: Coins },
  telegram_stars: { label: "ستاره تلگرام", Icon: Star },
};
const prov = (k) => PROVIDERS[k] || { label: k || "نامشخص", Icon: Wallet };
const CUR = { IRT: "تومان", IRR: "ریال" };
const cur = (c) => CUR[c] || c || "";

const reviewable = (p) => REVIEWABLE.includes(p.status) && p.has_receipt;
const refundable = (p) => p.status === "succeeded";
const FILTERS = {
  all: () => true,
  review: reviewable,
  succeeded: (p) => p.status === "succeeded",
  failed: (p) => p.status === "failed",
  closed: (p) => p.status === "refunded" || p.status === "cancelled",
};

const rtf = new Intl.RelativeTimeFormat("fa", { numeric: "auto" });
function ago(v) {
  if (!v) return "-";
  const s = Math.round((new Date(v).getTime() - Date.now()) / 1000);
  const a = Math.abs(s);
  if (a < 60) return rtf.format(s, "second");
  if (a < 3600) return rtf.format(Math.round(s / 60), "minute");
  if (a < 86400) return rtf.format(Math.round(s / 3600), "hour");
  if (a < 2592000) return rtf.format(Math.round(s / 86400), "day");
  return dt(v);
}
const sumBy = (rows) => {
  const m = new Map();
  rows.forEach((p) => m.set(p.currency, (m.get(p.currency) || 0) + (p.amount || 0)));
  return [...m].map(([c, a]) => `${num(a)} ${cur(c)}`).join(" · ") || "۰";
};
const copy = (text, toast) => navigator.clipboard?.writeText(String(text)).then(() => toast("کپی شد"), () => toast("کپی ناموفق بود"));

// ---------------------------------------------------------------- small parts
/** KpiBar cell for a text value (money per currency); Stat only renders numbers. */
function Metric({ Icon, tone, label, value, sub, loading }) {
  return (
    <div className="kpi">
      <span className="tile h-11 w-11" style={tint(tone)}><Icon size={19} /></span>
      <span className="min-w-0">
        {loading ? <span className="skel block h-6 w-28" /> : <span className="num block truncate text-lg font-extrabold leading-tight">{value}</span>}
        <span className="mt-1 block truncate text-xs text-[var(--mu)]">{label}</span>
        {sub && !loading && <span className="mt-0.5 block truncate text-[11px] text-[var(--mu)]">{sub}</span>}
      </span>
    </div>
  );
}

function ProviderChip({ k, size = 16 }) {
  const { label, Icon } = prov(k);
  return <span className="inline-flex items-center gap-2"><span className="tile h-8 w-8 !rounded-lg bg-[var(--mb)] text-[var(--mu)]"><Icon size={size} /></span><span className="font-bold">{label}</span></span>;
}

function Amount({ p, big = false }) {
  return <span className={`num font-extrabold ${big ? "text-2xl" : ""}`}>{num(p.amount)}<span className="mr-1.5 text-[11px] font-medium text-[var(--mu)]">{cur(p.currency)}</span></span>;
}

function RowActions({ p, busy, on, compact = false }) {
  const b = compact ? "!px-2" : "";
  return (
    <div className="flex items-center justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
      {p.has_receipt && <button className={`btn btn-g ${b}`} title="مشاهده رسید" aria-label="مشاهده رسید" onClick={() => on.receipt(p)}><Receipt size={14} />{!compact && "رسید"}</button>}
      {reviewable(p) && <>
        <button disabled={busy} className={`btn btn-g pay-ok ${b}`} title="تأیید پرداخت" aria-label="تأیید پرداخت" onClick={() => on.approve(p)}><Check size={14} />{!compact && "تأیید"}</button>
        <button disabled={busy} className={`btn btn-g btn-d ${b}`} title="رد پرداخت" aria-label="رد پرداخت" onClick={() => on.reject(p)}><X size={14} />{!compact && "رد"}</button>
      </>}
      {refundable(p) && <button disabled={busy} className={`btn btn-g btn-d ${b}`} title="استرداد" aria-label="استرداد" onClick={() => on.refund(p)}><Undo2 size={14} />{!compact && "استرداد"}</button>}
    </div>
  );
}

// ---------------------------------------------------------------- review queue
function Queue({ items, busy, on, seeAll, total }) {
  if (!items.length) return null;
  return (
    <section className="pay-queue rise">
      <div className="flex items-center justify-between gap-3 px-5 pt-4">
        <div className="flex items-center gap-2.5">
          <span className="tile relative h-10 w-10" style={tint("wn")}>
            <ShieldAlert size={18} /><span className="pv-ping absolute -left-0.5 -top-0.5 h-2.5 w-2.5 rounded-full bg-[var(--wn)]" />
          </span>
          <div><h3 className="font-extrabold">صف بررسی رسیدها</h3><p className="text-xs text-[var(--mu)]">{num(total)} پرداخت منتظر تصمیم شماست</p></div>
        </div>
        {total > items.length && <button className="btn btn-g" onClick={seeAll}>مشاهده همه ({num(total)})</button>}
      </div>
      <div className="pay-queue-row">
        {items.map((p) => (
          <article key={p.id} className="pay-qcard">
            <div className="flex items-start justify-between gap-2"><ProviderChip k={p.provider} /><span className="text-[11px] text-[var(--mu)]">{ago(p.created_at)}</span></div>
            <div className="mt-3"><Amount p={p} big /></div>
            <div className="mt-1 text-[11px] text-[var(--mu)]">کاربر <span dir="ltr" className="font-mono">{sid(p.user_id)}</span></div>
            <div className="mt-4 grid grid-cols-[auto_1fr_auto] gap-1.5">
              <button className="btn btn-g !px-2.5" aria-label="مشاهده رسید" title="مشاهده رسید" onClick={() => on.receipt(p)}><Receipt size={15} /></button>
              <button disabled={busy === p.id} className="btn" onClick={() => on.approve(p)}><Check size={15} />تأیید</button>
              <button disabled={busy === p.id} className="btn btn-g btn-d !px-2.5" aria-label="رد پرداخت" title="رد پرداخت" onClick={() => on.reject(p)}><X size={15} /></button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- detail drawer (shared kit Drawer)
function PaymentDrawer({ p, busy, on, onClose, toast, call }) {
  const [img, setImg] = useState(null);
  const [loadingImg, setLoadingImg] = useState(false);
  useEffect(() => { setImg(null); }, [p.id]);
  useEffect(() => () => { if (img) URL.revokeObjectURL(img); }, [img]);
  const preview = async () => {
    setLoadingImg(true);
    try {
      const r = await call(`/api/v1/admin/payments/${p.id}/receipt`);
      if (!r.ok) return toast("نمایش رسید ناموفق بود");
      const blob = await r.blob();
      if (blob.type.startsWith("image/")) setImg(URL.createObjectURL(blob));
      else { const u = URL.createObjectURL(blob); window.open(u, "_blank", "noopener"); setTimeout(() => URL.revokeObjectURL(u), 60000); }
    } catch { toast("ارتباط با سرور برقرار نشد"); } finally { setLoadingImg(false); }
  };
  const ids = [["شناسه پرداخت", p.id], ["شناسه کاربر", p.user_id], ["شناسه فروشگاه", p.store_id]];
  const footer = <>
    {reviewable(p) && <><button disabled={busy} className="btn !py-2 !text-sm" onClick={() => on.approve(p)}><Check size={15} />تأیید پرداخت</button><button disabled={busy} className="btn btn-g btn-d !py-2 !text-sm" onClick={() => on.reject(p)}><XCircle size={15} />رد</button></>}
    {refundable(p) && <button disabled={busy} className="btn btn-g btn-d !py-2 !text-sm" onClick={() => on.refund(p)}><Undo2 size={15} />استرداد پرداخت</button>}
  </>;
  return (
    <Drawer title="جزئیات پرداخت" subtitle={`${prov(p.provider).label} · ${sid(p.id)}`} busy={busy} onClose={onClose} footer={footer}
      icon={<span className="tile h-11 w-11" style={tint("in")}><Receipt size={19} /></span>}>
      <div className="card p-5 text-center">
        <Amount p={p} big />
        <div className="mt-3 flex items-center justify-center gap-2"><Badge s={p.status} /><span className="text-xs text-[var(--mu)]">{ago(p.created_at)}</span></div>
      </div>
      <Section title="اطلاعات تراکنش">
        <dl className="divide-y divide-[var(--ln)] text-sm">
          <div className="flex items-center justify-between gap-3 pb-3"><dt className="text-[var(--mu)]">درگاه</dt><dd><ProviderChip k={p.provider} size={14} /></dd></div>
          <div className="flex items-center justify-between gap-3 py-3"><dt className="text-[var(--mu)]">ثبت در</dt><dd className="font-bold">{dt(p.created_at)}</dd></div>
          {ids.map(([k, v], i) => (
            <div key={k} className={`flex items-center justify-between gap-3 ${i === ids.length - 1 ? "pt-3" : "py-3"}`}>
              <dt className="text-[var(--mu)]">{k}</dt>
              <dd className="flex min-w-0 items-center gap-1.5"><code dir="ltr" className="truncate text-xs">{sid(v)}</code>
                <button className="rounded-md p-1 text-[var(--mu)] hover:bg-[var(--mb)]" aria-label={`کپی ${k}`} onClick={() => copy(v, toast)}><Copy size={13} /></button></dd>
            </div>
          ))}
        </dl>
      </Section>
      <Section title="رسید پرداخت">
        {!p.has_receipt && <p className="rounded-xl border border-dashed border-[var(--ln)] p-5 text-center text-xs text-[var(--mu)]">رسیدی برای این پرداخت ثبت نشده است.</p>}
        {p.has_receipt && !img && <button className="btn btn-g" disabled={loadingImg} onClick={preview}><Receipt size={14} />{loadingImg ? "در حال دریافت…" : "نمایش رسید"}</button>}
        {img && <img src={img} alt="رسید پرداخت" className="max-h-96 w-full rounded-xl border border-[var(--ln)] bg-[var(--mb)] object-contain" />}
      </Section>
    </Drawer>
  );
}

// ---------------------------------------------------------------- gateway settings
const maskCard = (n) => { const d = String(n || "").replace(/\D/g, ""); return d.length >= 8 ? `${d.slice(0, 4)} •••• •••• ${d.slice(-4)}` : ""; };

function GatewaySettings({ obj, save }) {
  const [open, setOpen] = useState(false);
  const card = obj["card.info"] || {};
  const zp = obj["gateway.zarinpal"] || {};
  const [c, setC] = useState({ card_number: "", holder: "", bank: "", ...card });
  const [z, setZ] = useState({ merchant_id: "", sandbox: false, ...zp });
  useEffect(() => setC({ card_number: "", holder: "", bank: "", ...(obj["card.info"] || {}) }), [obj]);
  useEffect(() => setZ({ merchant_id: "", sandbox: false, ...(obj["gateway.zarinpal"] || {}) }), [obj]);
  const cardOk = !!(card.card_number && card.holder);
  const zpOk = !!zp.merchant_id;
  return (
    <section className="card overflow-hidden">
      <button className="flex w-full items-center justify-between gap-3 px-5 py-4 text-right" aria-expanded={open} onClick={() => setOpen((x) => !x)}>
        <span className="flex items-center gap-3"><span className="tile h-10 w-10 bg-[var(--mb)] text-[var(--mu)]"><Settings2 size={18} /></span>
          <span><span className="block font-extrabold">درگاه‌ها و روش‌های دریافت</span><span className="block text-xs text-[var(--mu)]">کارت‌به‌کارت و زرین‌پال فروشگاه اصلی</span></span></span>
        <span className="flex items-center gap-2"><span className="hidden gap-1.5 sm:flex">
          <span className={`badge ${cardOk ? "b-ok" : "b-mu"}`}>{cardOk ? "کارت تنظیم شد" : "کارت: تنظیم نشده"}</span>
          <span className={`badge ${zpOk ? "b-ok" : "b-mu"}`}>{zpOk ? "زرین‌پال فعال" : "زرین‌پال: تنظیم نشده"}</span></span>
          <ChevronDown size={18} className={`text-[var(--mu)] transition-transform ${open ? "rotate-180" : ""}`} /></span>
      </button>
      {open && (
        <div className="grid gap-4 border-t border-[var(--ln)] p-5 md:grid-cols-2">
          <div className="rounded-2xl border border-[var(--ln)] p-4">
            <div className="mb-3 flex items-center justify-between"><h4 className="font-bold">کارت‌به‌کارت</h4>{maskCard(card.card_number) && <span dir="ltr" className="font-mono text-[11px] text-[var(--mu)]">{maskCard(card.card_number)}</span>}</div>
            <div className="grid gap-3">
              <Field label="شماره کارت"><input dir="ltr" inputMode="numeric" className="inp" value={c.card_number} onChange={(e) => setC({ ...c, card_number: e.target.value })} /></Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="نام صاحب کارت"><input className="inp" value={c.holder} onChange={(e) => setC({ ...c, holder: e.target.value })} /></Field>
                <Field label="بانک"><input className="inp" value={c.bank} onChange={(e) => setC({ ...c, bank: e.target.value })} /></Field>
              </div>
            </div>
            <button className="btn mt-4" disabled={!c.card_number.trim() || !c.holder.trim()} onClick={() => save("card.info", c)}>ذخیره اطلاعات کارت</button>
          </div>
          <div className="rounded-2xl border border-[var(--ln)] p-4">
            <div className="mb-3 flex items-center justify-between"><h4 className="font-bold">زرین‌پال</h4>{z.sandbox && <span className="badge b-in">Sandbox</span>}</div>
            <div className="grid gap-3">
              <Field label="Merchant ID"><input dir="ltr" className="inp font-mono text-xs" value={z.merchant_id} onChange={(e) => setZ({ ...z, merchant_id: e.target.value })} /></Field>
              <div className="flex items-center justify-between rounded-xl bg-[var(--sf2)] px-3.5 py-3 text-sm font-bold">حالت آزمایشی (Sandbox)
                <Switch checked={!!z.sandbox} onChange={(v) => setZ({ ...z, sandbox: v })} label="حالت Sandbox" /></div>
            </div>
            <button className="btn mt-4" disabled={!z.merchant_id.trim()} onClick={() => save("gateway.zarinpal", z)}>ذخیره تنظیمات زرین‌پال</button>
          </div>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- main view
export default function PaymentsView({ api, toast }) {
  const call = useCallback((p, o = {}) => authFetch(api.base, p, o), [api.base]);
  const [rows, setRows] = useState(null);
  const [failed, setFailed] = useState(false);
  const [settings, setSettings] = useState({});
  const [tab, setTab] = useState("all");
  const [provider, setProvider] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [sel, setSel] = useState(null);
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await call("/api/v1/admin/payments");
      if (!r.ok) throw 0;
      const d = await r.json();
      setRows(Array.isArray(d) ? d : d.items || []); setFailed(false);
    } catch { setFailed(true); setRows((x) => x || []); }
  }, [call]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { call("/api/v1/admin/settings").then((r) => (r.ok ? r.json() : {})).then(setSettings).catch(() => {}); }, [call]);
  useEffect(() => setPage(0), [tab, provider, q]);

  const all = rows || [];
  const loading = rows === null;
  const counts = useMemo(() => Object.fromEntries(Object.entries(FILTERS).map(([k, f]) => [k, all.filter(f).length])), [all]);
  const providers = useMemo(() => [...new Set(all.map((p) => p.provider))], [all]);
  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    return all.filter((p) => FILTERS[tab](p) && (!provider || p.provider === provider) &&
      (!s || [p.id, p.user_id, p.store_id, p.provider, p.currency, String(p.amount)].some((v) => String(v || "").toLowerCase().includes(s))));
  }, [all, tab, provider, q]);
  const pageRows = filtered.slice(page * PAGE, page * PAGE + PAGE);
  const queue = all.filter(reviewable);
  const ok = all.filter(FILTERS.succeeded);
  const bad = all.filter(FILTERS.failed);
  const rate = ok.length + bad.length ? ok.length / (ok.length + bad.length) : null;
  const filtering = !!(q || provider || tab !== "all");

  const run = async (p, path, body, okMsg, failMsg) => {
    setBusy(p.id);
    try {
      const r = await call(`/api/v1/admin/payments/${p.id}/${path}`, { method: "POST", body: JSON.stringify(body) });
      if (r.ok) { toast(okMsg); await load(); setSel(null); } else toast(await errText(r, failMsg));
    } catch { toast("ارتباط با سرور برقرار نشد"); } finally { setBusy(""); }
  };
  const on = {
    approve: async (p) => { if (await confirmDialog(`پرداخت ${num(p.amount)} ${cur(p.currency)} تأیید شود؟ اعتبار یا سفارش مرتبط فعال خواهد شد.`, { title: "تأیید پرداخت", ok: "تأیید پرداخت" })) run(p, "review", { approve: true, reason: "" }, "پرداخت تأیید شد", "تأیید ناموفق بود"); },
    reject: async (p) => { const reason = await promptDialog("دلیل رد این پرداخت را بنویسید.", { title: "رد پرداخت", ok: "رد پرداخت" }); if (reason !== null) run(p, "review", { approve: false, reason }, "پرداخت رد شد", "رد پرداخت ناموفق بود"); },
    refund: async (p) => { const reason = await promptDialog(`استرداد واقعی ${num(p.amount)} ${cur(p.currency)} انجام می‌شود. دلیل را بنویسید.`, { title: "استرداد پرداخت", ok: "استرداد" }); if (reason !== null) run(p, "refund", { reason: reason || "درخواست استرداد توسط Admin" }, "استرداد ثبت شد", "استرداد ناموفق بود"); },
    receipt: async (p) => {
      try {
        const r = await call(`/api/v1/admin/payments/${p.id}/receipt`);
        if (!r.ok) return toast("نمایش رسید ناموفق بود");
        const url = URL.createObjectURL(await r.blob()); window.open(url, "_blank", "noopener"); setTimeout(() => URL.revokeObjectURL(url), 60000);
      } catch { toast("ارتباط با سرور برقرار نشد"); }
    },
  };
  const saveSetting = async (key, value) => {
    try {
      const r = await call(`/api/v1/admin/settings/${key}`, { method: "PUT", body: JSON.stringify({ value }) });
      if (r.ok) { toast("تنظیمات ذخیره شد"); setSettings((x) => ({ ...x, [key]: value })); } else toast(await errText(r, "ذخیره تنظیمات ناموفق بود"));
    } catch { toast("ارتباط با سرور برقرار نشد"); }
  };
  const exportCsv = () => {
    const head = ["id", "user_id", "store_id", "provider", "amount", "currency", "status", "has_receipt", "created_at"];
    const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const csv = [head.join(","), ...filtered.map((p) => head.map((k) => esc(p[k])).join(","))].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" }));
    a.download = `payments-${new Date().toISOString().slice(0, 10)}.csv`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  };
  const open = sel && all.find((p) => p.id === sel);
  const toggle = (k) => setTab(tab === k ? "all" : k);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><h2 className="text-xl font-extrabold">پرداخت‌ها</h2><p className="mt-1 text-xs text-[var(--mu)]">بررسی رسیدها، پیگیری تراکنش‌ها و مدیریت درگاه‌ها · {num(all.length)} پرداخت اخیر</p></div>
        <div className="flex gap-2">
          <button className="btn btn-g !py-2" onClick={load}><RefreshCw size={14} />به‌روزرسانی</button>
          <button className="btn btn-g !py-2" disabled={!filtered.length} onClick={exportCsv}><Download size={14} />خروجی CSV</button>
        </div>
      </div>

      <KpiBar cols={4}>
        <Metric Icon={TrendingUp} tone="ok" label="دریافتی موفق" value={sumBy(ok)} sub={`${num(ok.length)} تراکنش`} loading={loading} />
        <Stat label="منتظر بررسی" value={counts.review} tone={counts.review ? "wn" : "mu"} Icon={Clock} sub={counts.review ? sumBy(queue) : "صف خالی است"} active={tab === "review"} onClick={() => toggle("review")} />
        <Stat label="ناموفق" value={counts.failed} tone={counts.failed ? "bd" : "mu"} Icon={XCircle} sub={rate === null ? undefined : `نرخ موفقیت ${num(Math.round(rate * 100))}٪`} ring={rate === null ? undefined : rate} active={tab === "failed"} onClick={() => toggle("failed")} />
        <Stat label="مسترد / لغو" value={counts.closed} tone="in" Icon={Undo2} sub={sumBy(all.filter((p) => p.status === "refunded"))} active={tab === "closed"} onClick={() => toggle("closed")} />
      </KpiBar>

      {!filtering && <Queue items={queue.slice(0, 6)} total={queue.length} busy={busy} on={on} seeAll={() => setTab("review")} />}

      <div className="tool">
        <Pills label="فیلتر وضعیت" value={tab} onChange={setTab} options={[["all", "همه", counts.all], ["review", "نیازمند بررسی", counts.review, { warn: true }], ["succeeded", "موفق", counts.succeeded], ["failed", "ناموفق", counts.failed], ["closed", "مسترد / لغو", counts.closed]]} />
        <div className="mr-auto flex flex-wrap items-center gap-2">
          {providers.length > 1 && <select aria-label="فیلتر درگاه" className="inp !w-auto !py-2 !text-xs font-bold" value={provider} onChange={(e) => setProvider(e.target.value)}><option value="">همه درگاه‌ها</option>{providers.map((k) => <option key={k} value={k}>{prov(k).label}</option>)}</select>}
          <SearchBox label="جستجوی پرداخت" placeholder="شناسه، مبلغ، درگاه…" value={q} onChange={setQ} />
        </div>
      </div>

      {failed && <ErrorBar onRetry={load}><ShieldAlert size={16} />دریافت پرداخت‌ها ناموفق بود.</ErrorBar>}

      {loading ? <div className="card space-y-3 p-5">{[0, 1, 2, 3, 4].map((i) => <div key={i} className="skel h-10 w-full" />)}</div>
        : !filtered.length ? <Empty Icon={Wallet} title={filtering ? "پرداختی با این فیلتر پیدا نشد" : "هنوز پرداختی ثبت نشده است"} text={filtering ? "جستجو یا فیلتر را تغییر دهید." : "وقتی مشتری‌ها پرداخت انجام دهند، تراکنش‌ها و رسیدهای منتظر بررسی اینجا نمایش داده می‌شوند."}>
          {filtering && <button className="btn btn-g" onClick={() => { setTab("all"); setProvider(""); setQ(""); }}>پاک کردن فیلترها</button>}</Empty>
        : <section className="card rise overflow-hidden">
          {/* desktop table */}
          <div className="hidden max-h-[70vh] overflow-auto md:block">
            <table className="tbl2 min-w-[760px]">
              <thead><tr><th>درگاه</th><th>مبلغ</th><th>وضعیت</th><th>زمان</th><th className="!text-left">اقدام</th></tr></thead>
              <tbody>
                {pageRows.map((p) => (
                  <tr key={p.id} className="pay-row" tabIndex={0} onClick={() => setSel(p.id)} onKeyDown={(e) => e.key === "Enter" && setSel(p.id)}>
                    <td><ProviderChip k={p.provider} /><span dir="ltr" className="mr-2 font-mono text-[11px] text-[var(--mu)]">{sid(p.id)}</span></td>
                    <td><Amount p={p} /></td>
                    <td><Badge s={p.status} /></td>
                    <td className="text-xs text-[var(--mu)]" title={dt(p.created_at)}>{ago(p.created_at)}</td>
                    <td><RowActions p={p} busy={busy === p.id} on={on} /></td>
                  </tr>))}
              </tbody>
            </table>
          </div>
          {/* mobile cards */}
          <ul className="divide-y divide-[var(--ln)] md:hidden">
            {pageRows.map((p) => (
              <li key={p.id} className="space-y-3 p-4" onClick={() => setSel(p.id)}>
                <div className="flex items-center justify-between gap-2"><ProviderChip k={p.provider} /><Badge s={p.status} /></div>
                <div className="flex items-end justify-between gap-2"><Amount p={p} big /><span className="text-xs text-[var(--mu)]">{ago(p.created_at)}</span></div>
                <RowActions p={p} busy={busy === p.id} on={on} />
              </li>))}
          </ul>
        </section>}
      <Paginator page={page} setPage={setPage} total={filtered.length} pageSize={PAGE} />

      <GatewaySettings obj={settings} save={saveSetting} />
      {open && <PaymentDrawer p={open} busy={busy === open.id} on={on} call={call} toast={toast} onClose={() => setSel(null)} />}
    </div>
  );
}
