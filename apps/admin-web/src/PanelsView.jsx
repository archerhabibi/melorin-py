import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { authFetch } from "./api.js";
import { Badge, confirmDialog, dt, sid } from "./ui.jsx";
import ServersView from "./ServersView.jsx";
import {
  Activity, AlertTriangle, Check, ChevronDown, Copy, ExternalLink, Eye, EyeOff, FlaskConical, KeyRound,
  LayoutGrid, List, Pencil, Plus, RefreshCw, Save, Search, Server, ServerCog, ShieldAlert, ShieldCheck, X,
} from "lucide-react";

// ---------- helpers ----------
const num = (n) => Number(n || 0).toLocaleString("fa-IR");
const STALE_MS = 24 * 3600 * 1000;
const rtf = new Intl.RelativeTimeFormat("fa", { numeric: "auto" });
function ago(v) {
  if (!v) return "هرگز";
  const s = Math.round((new Date(v).getTime() - Date.now()) / 1000), a = Math.abs(s);
  if (a < 60) return rtf.format(s, "second");
  if (a < 3600) return rtf.format(Math.round(s / 60), "minute");
  if (a < 86400) return rtf.format(Math.round(s / 3600), "hour");
  return rtf.format(Math.round(s / 86400), "day");
}
const state = (p) => (p.health_status === "healthy" || p.health_status === "unhealthy" ? p.health_status : "unknown");
const isStale = (p) => !p.last_health_at || Date.now() - new Date(p.last_health_at).getTime() > STALE_MS;
async function errText(r, fallback) {
  try {
    const d = await r.json();
    const det = d?.detail;
    return d?.error?.message || (typeof det === "string" ? det : det?.message) || (Array.isArray(det) && det[0]?.msg?.replace(/^Value error, /, "")) || fallback;
  } catch { return fallback; }
}

const KINDS = {
  sanaei: { title: "سنایی (3x-ui)", desc: "پنل 3x-ui / Sanaei با Inbound و ساب‌اسکریپشن", Icon: ServerCog, tone: "in" },
  pasarguard: { title: "پاسارگارد", desc: "PasarGuard با گروه‌ها یا قالب کاربر", Icon: ShieldCheck, tone: "ok" },
  mock: { title: "Mock (آزمایشی)", desc: "فقط برای توسعه و تست؛ در محیط عملیاتی غیرفعال است", Icon: FlaskConical, tone: "wn" },
};
const kindOf = (k) => KINDS[k] || { title: k, desc: "", Icon: Server, tone: "mu" };
const tint = (t) => ({ background: `var(--${t}b, var(--mb))`, color: `var(--${t}, var(--mu))` });

// ---------- small UI parts ----------
function CopyButton({ text }) {
  const [ok, setOk] = useState(false);
  return <button type="button" className="btn btn-g !px-2" aria-label="کپی آدرس" title="کپی آدرس" onClick={async () => { try { await navigator.clipboard.writeText(text); setOk(true); setTimeout(() => setOk(false), 1400); } catch { /* clipboard unavailable */ } }}>{ok ? <Check size={14} /> : <Copy size={14} />}</button>;
}
function Dot({ s }) {
  const c = { healthy: "var(--ok)", unhealthy: "var(--bd)", unknown: "var(--mu)" }[s];
  return <span className="relative inline-flex h-2.5 w-2.5"><span className={`absolute inset-0 rounded-full ${s === "healthy" ? "pv-ping" : ""}`} style={{ background: c }} /><span className="relative h-2.5 w-2.5 rounded-full" style={{ background: c }} /></span>;
}
function Stat({ label, value, tone, active, onClick, Icon }) {
  return <button type="button" onClick={onClick} aria-pressed={active} className={`card flex items-center gap-3 p-4 text-right transition ${active ? "!border-[var(--ac)]" : "hover:-translate-y-0.5"}`}>
    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl" style={tint(tone)}><Icon size={19} /></span>
    <span><span className="block text-2xl font-extrabold leading-none">{num(value)}</span><span className="mt-1 block text-xs text-[var(--mu)]">{label}</span></span>
  </button>;
}
function Field({ label, hint, children }) {
  return <label className="block text-xs font-bold text-[var(--mu)]">{label}<div className="mt-1.5 font-normal">{children}</div>{hint && <span className="mt-1 block text-[11px] font-normal leading-5 text-[var(--mu)]">{hint}</span>}</label>;
}
function Segmented({ value, onChange, options }) {
  return <div role="radiogroup" className="pv-seg">{options.map(([v, l]) => <button key={v} type="button" role="radio" aria-checked={value === v} className={value === v ? "on" : ""} onClick={() => onChange(v)}>{l}</button>)}</div>;
}
function Secret({ value, onChange, placeholder }) {
  const [show, setShow] = useState(false);
  return <div className="relative"><input dir="ltr" autoComplete="off" spellCheck={false} type={show ? "text" : "password"} className="inp pl-10" value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} /><button type="button" aria-label={show ? "پنهان‌کردن" : "نمایش"} className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--mu)]" onClick={() => setShow(!show)}>{show ? <EyeOff size={16} /> : <Eye size={16} />}</button></div>;
}
function Chips({ values, onChange, placeholder }) {
  const [t, setT] = useState("");
  const add = () => { const n = parseInt(t, 10); if (Number.isInteger(n) && n > 0 && !values.includes(n)) onChange([...values, n]); setT(""); };
  return <div className="inp flex flex-wrap items-center gap-1.5 !py-1.5" dir="ltr">
    {values.map((n) => <span key={n} className="inline-flex items-center gap-1 rounded-md bg-[var(--mb)] px-2 py-0.5 text-xs font-bold">{n}<button type="button" aria-label={`حذف ${n}`} onClick={() => onChange(values.filter((x) => x !== n))}><X size={12} /></button></span>)}
    <input inputMode="numeric" className="min-w-[6rem] flex-1 bg-transparent py-1 text-sm outline-none" value={t} placeholder={values.length ? "" : placeholder} onChange={(e) => setT(e.target.value.replace(/\D/g, ""))} onBlur={add} onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); } else if (e.key === "Backspace" && !t && values.length) onChange(values.slice(0, -1)); }} />
  </div>;
}
function Toggle({ checked, onChange, label, hint }) {
  return <label className="flex cursor-pointer items-start gap-3"><button type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)} className="pv-sw mt-0.5" data-on={checked}><span /></button><span className="text-xs font-bold">{label}{hint && <span className="mt-0.5 block text-[11px] font-normal leading-5 text-[var(--mu)]">{hint}</span>}</span></label>;
}

// ---------- add / edit drawer ----------
const EMPTY = { kind: "sanaei", name: "", url: "", auth: "token", token: "", user: "", pass: "", inbounds: [], subUrl: "", apiStyle: "auto", groups: [], tpl: "", scope: "groups", verifyTls: true, extra: "" };
const KNOWN = { sanaei: ["inbound_ids", "inbound_id", "sub_base_url", "api_style", "verify_tls"], pasarguard: ["group_ids", "user_template_id", "verify_tls"], mock: [] };
const ints = (a) => (Array.isArray(a) ? a : []).map(Number).filter((n) => Number.isInteger(n) && n > 0);

// Rebuild the form from a stored panel; config keys the form has no field for stay in the JSON box so a save never drops them.
function fromPanel(p) {
  const c = p.config || {}, f = { ...EMPTY, kind: p.kind, name: p.name, url: p.base_url, verifyTls: c.verify_tls !== false };
  if (p.kind === "sanaei") { f.inbounds = ints(c.inbound_ids ?? (c.inbound_id != null ? [c.inbound_id] : [])); f.subUrl = c.sub_base_url || ""; f.apiStyle = c.api_style || "auto"; }
  if (p.kind === "pasarguard") { if (c.user_template_id != null) { f.scope = "template"; f.tpl = String(c.user_template_id); } else f.groups = ints(c.group_ids); }
  const rest = Object.fromEntries(Object.entries(c).filter(([k]) => !KNOWN[p.kind].includes(k)));
  f.extra = Object.keys(rest).length ? JSON.stringify(rest, null, 2) : "";
  return f;
}
const parseExtra = (t) => { if (!t.trim()) return {}; const x = JSON.parse(t); if (!x || typeof x !== "object" || Array.isArray(x)) throw new Error("obj"); return x; };

function buildPayload(f, withCreds) {
  const credentials = {}; let config = {};
  if (withCreds && f.kind !== "mock") {
    if (f.auth === "token") credentials[f.kind === "sanaei" ? "api_token" : "api_key"] = f.token.trim(); else { credentials.username = f.user.trim(); credentials.password = f.pass; }
  }
  if (f.kind === "sanaei") config = { inbound_ids: f.inbounds, sub_base_url: f.subUrl.trim(), api_style: f.apiStyle };
  else if (f.kind === "pasarguard") { if (f.scope === "groups") config.group_ids = f.groups; else config.user_template_id = parseInt(f.tpl, 10); }
  if (f.kind !== "mock") config.verify_tls = f.verifyTls;
  config = { ...config, ...parseExtra(f.extra) };
  if (f.kind === "sanaei" && !config.inbound_ids?.length) delete config.inbound_ids;
  return { name: f.name.trim(), kind: f.kind, base_url: f.url.trim().replace(/\/+$/, ""), credentials, config };
}
function validate(f, withCreds) {
  const e = {}; let extra = {};
  if (f.extra.trim()) { try { extra = parseExtra(f.extra); } catch { e.extra = "JSON پیشرفته نامعتبر است (باید یک شیء باشد)"; } }
  if (!f.name.trim()) e.name = "نام پنل را وارد کنید";
  try { const u = new URL(f.url.trim()); if (!/^https?:$/.test(u.protocol)) throw 0; } catch { e.url = "آدرس معتبر نیست (مثال: https://panel.example.com:2053/path)"; }
  if (withCreds && f.kind !== "mock" && (f.auth === "token" ? !f.token.trim() : !(f.user.trim() && f.pass))) e.auth = f.auth === "token" ? "توکن را وارد کنید" : "نام کاربری و رمز عبور هر دو لازم است";
  if (f.kind === "sanaei") {
    if (!/^https?:\/\//.test(f.subUrl.trim())) e.subUrl = "آدرس ساب‌اسکریپشن لازم است (مثال: https://sub.example.com:2096/sub)";
    if (!f.inbounds.length && !extra.template_username) e.inbounds = "حداقل یک Inbound ID لازم است";
  }
  if (f.kind === "pasarguard") {
    if (f.scope === "groups" && !f.groups.length) e.scope = "حداقل یک Group ID لازم است";
    if (f.scope === "template" && !(parseInt(f.tpl, 10) > 0)) e.scope = "شناسه قالب باید عدد مثبت باشد";
  }
  return e;
}

function PanelDrawer({ panel, onClose, onSubmit, onToggle, toggling }) {
  const edit = !!panel;
  const [f, setF] = useState(() => (panel ? fromPanel(panel) : EMPTY));
  const base = useRef(JSON.stringify(f));
  const [changeCred, setChangeCred] = useState(!panel || !panel.has_credentials);
  const [tried, setTried] = useState(false); const [busy, setBusy] = useState(false); const [srvErr, setSrvErr] = useState("");
  const [adv, setAdv] = useState(() => !!(panel && fromPanel(panel).extra));
  const withCreds = changeCred && f.kind !== "mock";
  const set = (k) => (v) => { setSrvErr(""); setF((x) => ({ ...x, [k]: v })); };
  const err = useMemo(() => validate(f, withCreds), [f, withCreds]);
  const show = (k) => tried && err[k];
  const dirty = JSON.stringify(f) !== base.current || (edit && changeCred && !!panel.has_credentials);
  const insecure = /^http:\/\//i.test(f.url.trim());
  const first = useRef(); useEffect(() => { first.current?.focus(); }, []);
  const close = async () => { if (busy) return; if (dirty && !(await confirmDialog("تغییرات ذخیره‌نشده از بین می‌رود. بسته شود؟", { title: "بستن بدون ذخیره", danger: true, ok: "بستن" }))) return; onClose(); };
  const submit = async (check) => {
    setTried(true); if (Object.keys(err).length) return;
    setBusy(true); setSrvErr("");
    const msg = await onSubmit(buildPayload(f, withCreds), check);
    setBusy(false); if (msg) setSrvErr(msg);
  };
  const k = kindOf(f.kind), st = panel ? state(panel) : null;
  return <div className="fixed inset-0 z-50" onKeyDown={(e) => e.key === "Escape" && close()}>
    <div className="pv-fade absolute inset-0 bg-black/55" onClick={close} />
    <aside role="dialog" aria-modal="true" aria-label={edit ? "ویرایش پنل" : "افزودن پنل"} dir="rtl" className="pv-drawer absolute inset-y-0 right-0 flex w-full max-w-xl flex-col border-l border-[var(--ln)] bg-[var(--bg)] shadow-2xl">
      <header className="flex items-center gap-3 border-b border-[var(--ln)] bg-[var(--sf)] px-5 py-4">
        {edit && <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint(k.tone)}><k.Icon size={20} /></span>}
        <div className="min-w-0 flex-1"><h2 className="truncate text-lg font-extrabold">{edit ? `ویرایش «${panel.name}»` : "افزودن پنل جدید"}</h2><p className="mt-0.5 text-xs text-[var(--mu)]">{edit ? `${k.title} · شناسه ${sid(panel.id)}` : "اتصال یک پنل VPN به Core برای ساخت و مدیریت اکانت‌ها"}</p></div>
        {dirty && <span className="badge b-wn">تغییرات ذخیره‌نشده</span>}
        <button className="btn btn-g !px-2" aria-label="بستن" onClick={close} disabled={busy}><X size={16} /></button>
      </header>
      <div className="flex-1 space-y-6 overflow-y-auto p-5">
        {edit && <section className="card space-y-3 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2"><Dot s={st} /><Badge s={st} /><span className="text-xs text-[var(--mu)]">آخرین بررسی: {panel.last_health_at ? dt(panel.last_health_at) : "هرگز"}</span></div>
            <label className="flex cursor-pointer items-center gap-2 text-xs font-bold"><button type="button" role="switch" aria-checked={panel.is_enabled} disabled={toggling} onClick={() => onToggle(panel, !panel.is_enabled)} className="pv-sw" data-on={panel.is_enabled}><span /></button>{panel.is_enabled ? "فعال" : "غیرفعال"}</label></div>
          {st === "unhealthy" && panel.last_health_error && <p dir="auto" className="break-words rounded-lg bg-[var(--bdb)] p-3 text-xs leading-6 text-[var(--bd)]"><b>آخرین خطا: </b>{panel.last_health_error}</p>}
          {!panel.is_enabled && <p className="text-[11px] leading-5 text-[var(--mu)]">پنل غیرفعال برای ساخت اکانت جدید انتخاب نمی‌شود و بررسی سلامت خودکار هم برای آن اجرا نمی‌شود. اکانت‌های موجود حذف نمی‌شوند.</p>}
          <p className="text-[11px] text-[var(--mu)]">ایجاد: {dt(panel.created_at)} · آخرین ویرایش: {dt(panel.updated_at)}</p>
        </section>}

        {!edit && <section><h3 className="mb-2 text-xs font-bold text-[var(--mu)]">۱ · نوع پنل</h3>
          <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="نوع پنل">{Object.entries(KINDS).map(([key, m]) => <button key={key} type="button" role="radio" aria-checked={f.kind === key} onClick={() => set("kind")(key)} className={`card p-3 text-right transition ${f.kind === key ? "!border-[var(--ac)] ring-2 ring-[color-mix(in_srgb,var(--ac)_25%,transparent)]" : "hover:-translate-y-0.5"}`}>
            <span className="grid h-9 w-9 place-items-center rounded-lg" style={tint(m.tone)}><m.Icon size={18} /></span>
            <span className="mt-2 block text-sm font-extrabold">{m.title}</span><span className="mt-1 block text-[11px] leading-5 text-[var(--mu)]">{m.desc}</span></button>)}</div></section>}

        <section className="card space-y-4 p-4"><h3 className="text-xs font-bold text-[var(--mu)]">{edit ? "اتصال" : "۲ · اتصال"}</h3>
          <Field label="نام نمایشی" hint={show("name")}><input ref={first} className="inp" value={f.name} maxLength={100} placeholder="مثلاً: آلمان - هتزنر ۱" onChange={(e) => set("name")(e.target.value)} /></Field>
          <Field label="آدرس پنل (Base URL)" hint={show("url") || "آدرس کامل همراه پورت و web base path"}>
            <input dir="ltr" inputMode="url" spellCheck={false} className="inp" value={f.url} placeholder="https://panel.example.com:2053/secret-path" onChange={(e) => set("url")(e.target.value)} /></Field>
          {insecure && <p className="flex items-start gap-2 rounded-lg bg-[var(--wnb)] p-3 text-xs leading-6 text-[var(--wn)]"><AlertTriangle size={15} className="mt-1 shrink-0" />آدرس HTTP است؛ در محیط staging/production فقط HTTPS پذیرفته می‌شود.</p>}
        </section>

        {f.kind !== "mock" && <section className="card space-y-4 p-4"><h3 className="flex items-center gap-1.5 text-xs font-bold text-[var(--mu)]"><KeyRound size={14} />{edit ? "احراز هویت" : "۳ · احراز هویت"} <span className="font-normal">(رمزنگاری‌شده ذخیره می‌شود)</span></h3>
          {edit && panel.has_credentials && !changeCred
            ? <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-[var(--sf2)] px-3 py-2.5"><span className="flex items-center gap-2 text-xs"><ShieldCheck size={15} className="text-[var(--ok)]" />اعتبارنامه ذخیره شده است و نمایش داده نمی‌شود.</span><button type="button" className="btn btn-g" onClick={() => setChangeCred(true)}>تغییر اعتبارنامه</button></div>
            : <>
              <Segmented value={f.auth} onChange={set("auth")} options={[["token", f.kind === "sanaei" ? "API Token" : "API Key"], ["login", "نام کاربری و رمز"]]} />
              {f.auth === "token" ? <Field label={f.kind === "sanaei" ? "API Token" : "API Key"} hint={show("auth")}><Secret value={f.token} onChange={set("token")} placeholder="••••••••" /></Field>
                : <div className="grid gap-3 sm:grid-cols-2"><Field label="نام کاربری"><input dir="ltr" autoComplete="off" className="inp" value={f.user} onChange={(e) => set("user")(e.target.value)} /></Field><Field label="رمز عبور"><Secret value={f.pass} onChange={set("pass")} /></Field>{show("auth") && <p className="text-[11px] text-[var(--bd)] sm:col-span-2">{err.auth}</p>}</div>}
              {f.kind === "sanaei" && f.auth === "login" && <p className="text-[11px] leading-5 text-[var(--mu)]">اگر 2FA روی پنل فعال است، ورود با نام کاربری کار نمی‌کند؛ از API Token استفاده کنید.</p>}
              {edit && panel.has_credentials && <button type="button" className="text-xs font-bold text-[var(--mu)] underline" onClick={() => { setChangeCred(false); setF((x) => ({ ...x, token: "", user: "", pass: "" })); }}>انصراف از تغییر اعتبارنامه</button>}
            </>}
        </section>}

        {f.kind !== "mock" && <section className="card space-y-4 p-4"><h3 className="text-xs font-bold text-[var(--mu)]">{edit ? "" : "۴ · "}تنظیمات {k.title}</h3>
          {f.kind === "sanaei" && <>
            <Field label="Inbound IDها" hint={show("inbounds") || "شناسه Inboundهایی که کلاینت در آن‌ها ساخته می‌شود؛ بعد از هر عدد Enter بزنید"}><Chips values={f.inbounds} onChange={set("inbounds")} placeholder="مثلاً 1" /></Field>
            <Field label="آدرس ساب‌اسکریپشن" hint={show("subUrl") || "Sub Port + Sub Path از Settings → Subscription پنل"}><input dir="ltr" spellCheck={false} className="inp" value={f.subUrl} placeholder="https://sub.example.com:2096/sub" onChange={(e) => set("subUrl")(e.target.value)} /></Field>
            <Field label="سبک API"><Segmented value={f.apiStyle} onChange={set("apiStyle")} options={[["auto", "خودکار"], ["v3", "v3"], ["legacy", "Legacy"]]} /></Field></>}
          {f.kind === "pasarguard" && <>
            <Segmented value={f.scope} onChange={set("scope")} options={[["groups", "Group IDs"], ["template", "قالب کاربر"]]} />
            {f.scope === "groups" ? <Field label="Group IDها" hint={show("scope")}><Chips values={f.groups} onChange={set("groups")} placeholder="مثلاً 1" /></Field>
              : <Field label="شناسه قالب کاربر" hint={show("scope")}><input dir="ltr" inputMode="numeric" className="inp" value={f.tpl} onChange={(e) => set("tpl")(e.target.value.replace(/\D/g, ""))} /></Field>}</>}
          <Toggle checked={f.verifyTls} onChange={set("verifyTls")} label="بررسی گواهی TLS" hint="در محیط عملیاتی خاموش‌کردن آن مجاز نیست؛ فقط برای تست با گواهی self-signed." />
        </section>}

        <section><button type="button" className="flex items-center gap-1.5 text-xs font-bold text-[var(--mu)]" aria-expanded={adv} onClick={() => setAdv(!adv)}><ChevronDown size={14} className={adv ? "" : "-rotate-90"} />تنظیمات پیشرفته (JSON)</button>
          {adv && <div className="mt-2"><Field label="Config اضافه" hint={show("extra") || "روی تنظیمات بالا ادغام می‌شود؛ مثلاً {\"timeout\": 30}"}><textarea rows={4} dir="ltr" spellCheck={false} className="inp font-mono text-xs" value={f.extra} onChange={(e) => set("extra")(e.target.value)} /></Field></div>}</section>
        {edit && <p className="flex items-start gap-2 rounded-lg bg-[var(--inb)] p-3 text-[11px] leading-5 text-[var(--in)]"><Activity size={14} className="mt-0.5 shrink-0" />با تغییر آدرس، تنظیمات یا اعتبارنامه، وضعیت سلامت به «بررسی‌نشده» برمی‌گردد؛ برای اطمینان از اتصال از «ذخیره و بررسی سلامت» استفاده کنید.</p>}
        {srvErr && <p role="alert" className="flex items-start gap-2 rounded-lg bg-[var(--bdb)] p-3 text-xs leading-6 text-[var(--bd)]"><ShieldAlert size={15} className="mt-1 shrink-0" />{srvErr}</p>}
      </div>
      <footer className="flex flex-wrap items-center gap-2 border-t border-[var(--ln)] bg-[var(--sf)] px-5 py-4">
        <button className="btn" disabled={busy || (edit && !dirty)} onClick={() => submit(true)}>{busy ? <RefreshCw size={15} className="animate-spin" /> : <Activity size={15} />}{edit ? "ذخیره و بررسی سلامت" : "ثبت و بررسی سلامت"}</button>
        <button className="btn btn-g !py-2 !text-sm" disabled={busy || (edit && !dirty)} onClick={() => submit(false)}>{edit ? <><Save size={14} />فقط ذخیره</> : "فقط ثبت"}</button>
        <button className="btn btn-g mr-auto !py-2 !text-sm" disabled={busy} onClick={close}>انصراف</button>
      </footer>
    </aside>
  </div>;
}

// ---------- panel card / row ----------
function Switch({ p, busy, onToggle }) {
  return <button type="button" role="switch" aria-checked={p.is_enabled} aria-label={`${p.is_enabled ? "غیرفعال‌سازی" : "فعال‌سازی"} ${p.name}`} title={p.is_enabled ? "غیرفعال‌سازی" : "فعال‌سازی"} disabled={busy} onClick={() => onToggle(p, !p.is_enabled)} className="pv-sw" data-on={p.is_enabled}><span /></button>;
}
function PanelCard({ p, busy, srv, onShowServers, onCheck, onEdit, onToggle }) {
  const s = state(p), k = kindOf(p.kind), stale = isStale(p) && p.is_enabled;
  return <article className="card rise flex flex-col gap-4 p-4">
    <div className={`flex items-start gap-3 ${p.is_enabled ? "" : "opacity-55"}`}>
      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint(k.tone)}><k.Icon size={20} /></span>
      <div className="min-w-0 flex-1"><h3 className="truncate font-extrabold" title={p.name}>{p.name}</h3><p className="text-xs text-[var(--mu)]">{k.title}</p></div>
      <div className="flex flex-col items-end gap-1"><span className="flex items-center gap-2"><Dot s={s} /><Badge s={s} /></span>{!p.is_enabled && <Badge s="disabled" />}</div>
    </div>
    <div className={`flex items-center gap-1.5 rounded-lg bg-[var(--sf2)] px-3 py-2 ${p.is_enabled ? "" : "opacity-55"}`}><span dir="ltr" className="min-w-0 flex-1 truncate font-mono text-xs" title={p.base_url}>{p.base_url}</span><CopyButton text={p.base_url} />
      <a className="btn btn-g !px-2" href={p.base_url} target="_blank" rel="noopener noreferrer" aria-label="باز کردن پنل" title="باز کردن پنل"><ExternalLink size={14} /></a></div>
    {s === "unhealthy" && p.last_health_error && <p dir="auto" className="break-words rounded-lg bg-[var(--bdb)] px-3 py-2 text-[11px] leading-5 text-[var(--bd)]">{p.last_health_error}</p>}
    <div className="mt-auto flex items-center justify-between gap-2 border-t border-[var(--ln)] pt-3">
      <div className="flex min-w-0 flex-col gap-1">
        <span className={`flex items-center gap-1.5 text-xs ${stale ? "text-[var(--wn)]" : "text-[var(--mu)]"}`} title={p.last_health_at ? dt(p.last_health_at) : ""}>{stale && <AlertTriangle size={13} />}{ago(p.last_health_at)}</span>
        <button type="button" className="flex items-center gap-1 text-right text-[11px] font-bold text-[var(--mu)] hover:text-[var(--ac)]" onClick={() => onShowServers(p.id)}><Server size={12} />{srv?.n ? `${num(srv.n)} سرور · ${num(srv.active)} اکانت فعال` : "بدون سرور — افزودن"}</button>
      </div>
      <div className="flex items-center gap-1.5"><Switch p={p} busy={busy} onToggle={onToggle} />
        <button className="btn btn-g" onClick={() => onEdit(p)}><Pencil size={13} />ویرایش</button>
        <button className="btn btn-g !px-2" aria-label="بررسی سلامت" title="بررسی سلامت" disabled={busy} onClick={() => onCheck(p)}><RefreshCw size={13} className={busy ? "animate-spin" : ""} /></button></div>
    </div>
  </article>;
}
function PanelTable({ rows, busy, srvBy, onShowServers, onCheck, onEdit, onToggle }) {
  return <section className="card rise overflow-hidden"><div className="overflow-auto"><table className="tbl min-w-[820px]"><thead><tr>{["نام", "نوع", "آدرس", "وضعیت", "آخرین بررسی", "سرورها", "فعال", ""].map((c, i) => <th key={i}>{c}</th>)}</tr></thead>
    <tbody>{rows.map((p) => <tr key={p.id} className={p.is_enabled ? "" : "opacity-60"}><td className="font-bold">{p.name}</td><td>{kindOf(p.kind).title}</td><td><span dir="ltr" className="block max-w-[260px] truncate font-mono text-xs">{p.base_url}</span></td>
      <td><Badge s={state(p)} /></td><td className={isStale(p) && p.is_enabled ? "text-[var(--wn)]" : "text-[var(--mu)]"}>{ago(p.last_health_at)}</td><td><button type="button" className="font-bold hover:text-[var(--ac)]" onClick={() => onShowServers(p.id)}>{num(srvBy.get(p.id)?.n)}</button></td><td><Switch p={p} busy={busy.has(p.id)} onToggle={onToggle} /></td>
      <td><div className="flex gap-1.5"><button className="btn btn-g" onClick={() => onEdit(p)}><Pencil size={13} />ویرایش</button><button className="btn btn-g" disabled={busy.has(p.id)} onClick={() => onCheck(p)}><RefreshCw size={13} className={busy.has(p.id) ? "animate-spin" : ""} />بررسی</button></div></td></tr>)}</tbody></table></div></section>;
}

// ---------- page ----------
// drawer: null | "add" | id of the panel being edited
function PanelsTab({ api, toast, onAddServer, onShowServers }) {
  const [rows, setRows] = useState(null); const [failed, setFailed] = useState(false);
  const [q, setQ] = useState(""); const [filter, setFilter] = useState("all"); const [layout, setLayout] = useState("grid");
  const [drawer, setDrawer] = useState(null); const [busy, setBusy] = useState(new Set()); const [bulk, setBulk] = useState(null);
  const alive = useRef(true); useEffect(() => () => { alive.current = false; }, []);

  const load = useCallback(async () => {
    try { const r = await authFetch(api.base, "/api/v1/admin/panels"); if (!r.ok) throw 0; const d = await r.json(); if (alive.current) { setRows(Array.isArray(d) ? d : d.items || []); setFailed(false); } }
    catch { if (alive.current) { setFailed(true); setRows((x) => x || []); } }
  }, [api.base]);
  useEffect(() => { load(); }, [load]);

  const check = useCallback(async (p, quiet) => {
    setBusy((s) => new Set(s).add(p.id));
    let ok = false, healthy = false;
    try { const r = await authFetch(api.base, `/api/v1/admin/panels/${p.id}/health`, { method: "POST" }); ok = r.ok; healthy = ok && (await r.json()).healthy; } catch { /* network */ }
    if (alive.current) setBusy((s) => { const n = new Set(s); n.delete(p.id); return n; });
    if (!quiet) toast(!ok ? `بررسی «${p.name}» ناموفق بود` : healthy ? `«${p.name}» سالم است` : `«${p.name}» پاسخ سالم نداد`);
    if (!quiet) await load();
    return healthy;
  }, [api.base, toast, load]);

  const checkAll = async () => {
    const list = (rows || []).filter((p) => p.is_enabled); if (!list.length) return;
    if (!(await confirmDialog(`سلامت ${num(list.length)} پنل فعال بررسی شود؟`, { title: "بررسی همه پنل‌ها", ok: "شروع" }))) return;
    let done = 0, bad = 0; setBulk({ done, total: list.length });
    const queue = [...list];
    await Promise.all(Array.from({ length: Math.min(3, queue.length) }, async () => { for (let p = queue.shift(); p; p = queue.shift()) { if (!(await check(p, true))) bad++; done++; if (alive.current) setBulk({ done, total: list.length }); } }));
    if (alive.current) setBulk(null);
    toast(bad ? `${num(bad)} پنل از ${num(list.length)} مورد ناسالم است` : "همه پنل‌ها سالم هستند"); await load();
  };

  const save = async (payload, withCheck) => {
    const editing = drawer !== "add";
    const r = await authFetch(api.base, editing ? `/api/v1/admin/panels/${drawer}` : "/api/v1/admin/panels", { method: editing ? "PATCH" : "POST", body: JSON.stringify(payload) });
    if (!r.ok) return errText(r, editing ? "ذخیره تغییرات ناموفق بود" : "ثبت پنل ناموفق بود");
    const id = editing ? drawer : (await r.json())?.id; setDrawer(null); toast(editing ? "تغییرات ذخیره شد" : "پنل ثبت شد");
    await load(); if (withCheck && id) await check({ id, name: payload.name }); return "";
  };

  const toggle = async (p, next) => {
    if (!next && !(await confirmDialog(`«${p.name}» غیرفعال شود؟ برای ساخت اکانت جدید استفاده نمی‌شود و بررسی سلامت خودکار آن هم متوقف می‌شود.`, { title: "غیرفعال‌سازی پنل", danger: true, ok: "غیرفعال کن" }))) return;
    setBusy((x) => new Set(x).add(p.id));
    let ok = false;
    try { ok = (await authFetch(api.base, `/api/v1/admin/panels/${p.id}/state`, { method: "POST", body: JSON.stringify({ is_enabled: next }) })).ok; } catch { /* network */ }
    if (alive.current) setBusy((x) => { const n = new Set(x); n.delete(p.id); return n; });
    toast(ok ? (next ? `«${p.name}» فعال شد` : `«${p.name}» غیرفعال شد`) : "تغییر وضعیت ناموفق بود");
    if (ok) await load();
  };

  const servers = useRef([]); const [srvTick, setSrvTick] = useState(0);
  useEffect(() => { authFetch(api.base, "/api/v1/admin/servers").then((r) => (r.ok ? r.json() : [])).then((d) => { servers.current = Array.isArray(d) ? d : []; if (alive.current) setSrvTick((x) => x + 1); }).catch(() => {}); }, [api.base, rows]);
  const srvBy = useMemo(() => { const m = new Map(); servers.current.forEach((x) => { const c = m.get(x.panel_id) || { n: 0, active: 0 }; c.n++; c.active += x.active_accounts || 0; m.set(x.panel_id, c); }); return m; }, [srvTick]); // eslint-disable-line react-hooks/exhaustive-deps
  const counts = useMemo(() => { const c = { all: 0, healthy: 0, unhealthy: 0, unknown: 0 }; (rows || []).forEach((p) => { c.all++; c[state(p)]++; }); return c; }, [rows]);
  const shown = useMemo(() => (rows || []).filter((p) => (filter === "all" || state(p) === filter) && `${p.name} ${p.base_url} ${kindOf(p.kind).title}`.toLowerCase().includes(q.trim().toLowerCase())), [rows, filter, q]);
  const loading = rows === null;
  const editing = drawer && drawer !== "add" ? (rows || []).find((p) => p.id === drawer) : null;

  return <div className="space-y-5">
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Stat label="همه پنل‌ها" value={counts.all} tone="in" Icon={Server} active={filter === "all"} onClick={() => setFilter("all")} />
      <Stat label="سالم" value={counts.healthy} tone="ok" Icon={ShieldCheck} active={filter === "healthy"} onClick={() => setFilter(filter === "healthy" ? "all" : "healthy")} />
      <Stat label="ناسالم" value={counts.unhealthy} tone="bd" Icon={ShieldAlert} active={filter === "unhealthy"} onClick={() => setFilter(filter === "unhealthy" ? "all" : "unhealthy")} />
      <Stat label="بررسی‌نشده" value={counts.unknown} tone="wn" Icon={AlertTriangle} active={filter === "unknown"} onClick={() => setFilter(filter === "unknown" ? "all" : "unknown")} />
    </div>

    <div className="flex flex-wrap items-center gap-2">
      <label className="relative min-w-[12rem] flex-1 sm:max-w-xs"><Search size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[var(--mu)]" /><input aria-label="جستجوی پنل" className="inp pr-9" placeholder="جستجو در نام، نوع یا آدرس…" value={q} onChange={(e) => setQ(e.target.value)} /></label>
      <div className="pv-seg" role="group" aria-label="نحوه نمایش"><button type="button" className={layout === "grid" ? "on" : ""} aria-label="کارتی" onClick={() => setLayout("grid")}><LayoutGrid size={15} /></button><button type="button" className={layout === "list" ? "on" : ""} aria-label="جدولی" onClick={() => setLayout("list")}><List size={15} /></button></div>
      <div className="mr-auto flex items-center gap-2">
        <button className="btn btn-g !py-2 !text-sm" onClick={checkAll} disabled={!!bulk || !counts.all}><RefreshCw size={14} className={bulk ? "animate-spin" : ""} />{bulk ? `${num(bulk.done)} از ${num(bulk.total)}` : "بررسی همه"}</button>
        <button className="btn" onClick={() => setDrawer("add")}><Plus size={16} />افزودن پنل</button>
        <button className="btn btn-g !py-2 !text-sm" onClick={onAddServer}><Plus size={16} />افزودن سرور</button>
      </div>
    </div>

    {failed && <p role="alert" className="flex items-center gap-2 rounded-xl bg-[var(--bdb)] p-3 text-sm text-[var(--bd)]"><AlertTriangle size={16} />دریافت پنل‌ها ناموفق بود. <button className="underline" onClick={load}>تلاش دوباره</button></p>}

    {loading ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="card skel h-40" />)}</div>
      : !shown.length ? <div className="card grid place-items-center gap-3 p-14 text-center"><span className="grid h-14 w-14 place-items-center rounded-2xl bg-[var(--mb)] text-[var(--mu)]"><Server size={26} /></span>
        <h3 className="font-extrabold">{counts.all ? "پنلی با این فیلتر پیدا نشد" : "هنوز پنلی اضافه نشده"}</h3>
        <p className="max-w-sm text-sm leading-7 text-[var(--mu)]">{counts.all ? "جستجو یا فیلتر وضعیت را تغییر دهید." : "برای فروش اکانت، ابتدا یک پنل سنایی یا پاسارگارد به Core وصل کنید."}</p>
        {!counts.all && <button className="btn" onClick={() => setDrawer("add")}><Plus size={16} />افزودن اولین پنل</button>}</div>
      : layout === "grid" ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{shown.map((p) => <PanelCard key={p.id} p={p} srv={srvBy.get(p.id)} onShowServers={onShowServers} busy={busy.has(p.id)} onCheck={check} onEdit={(x) => setDrawer(x.id)} onToggle={toggle} />)}</div>
        : <PanelTable rows={shown} busy={busy} srvBy={srvBy} onShowServers={onShowServers} onCheck={check} onEdit={(x) => setDrawer(x.id)} onToggle={toggle} />}

    {drawer && (drawer === "add" || editing) && <PanelDrawer key={drawer} panel={drawer === "add" ? null : editing} onClose={() => setDrawer(null)} onSubmit={save} onToggle={toggle} toggling={editing ? busy.has(editing.id) : false} />}
  </div>;
}

// Page shell: one "Panels & servers" screen with two tabs. Tab state lives here so a panel card can jump to its servers.
export default function PanelsView({ api, toast }) {
  const [tab, setTab] = useState("panels");
  const [addTick, setAddTick] = useState(0); const [panelFilter, setPanelFilter] = useState(null);
  const tabs = [["panels", "پنل‌ها"], ["servers", "سرورها"]];
  return <div className="space-y-5">
    <div className="pv-seg" role="tablist" aria-label="بخش‌های پنل و سرور">{tabs.map(([k, l]) => <button key={k} type="button" role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => { setPanelFilter(null); setTab(k); }}>{k === "panels" ? <Server size={15} /> : <ServerCog size={15} />}{l}</button>)}</div>
    {tab === "panels"
      ? <PanelsTab api={api} toast={toast} onAddServer={() => { setPanelFilter(null); setAddTick((x) => x + 1); setTab("servers"); }} onShowServers={(id) => { setPanelFilter(id); setTab("servers"); }} />
      : <ServersView key={panelFilter || "all"} api={api} toast={toast} startAdd={addTick} initialPanel={panelFilter} onGoPanels={() => setTab("panels")} />}
  </div>;
}
