import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { authFetch } from "./api.js";
import { ServerForm, ServerImport } from "./ServerForm.jsx";
import { Badge, confirmDialog, dt, sid } from "./ui.jsx";
import { Dot, HLABEL, InfraChain, RelChip, clearParam, free, health, memberIds, saveGroupPanels, serverState, serves, usage, useHashParams, useInfra } from "./infra.jsx";
import { Drawer, Empty, ErrorBar, Field, KpiBar, NumInput, Paginator, Pills, Ring, SearchBox, Section, Segmented, SegMeter, SortSelect, Stat, Switch, Toggle, ViewToggle, DeleteButton, capTone, errText, num, removeEntity, tint, useAlive } from "./kit.jsx";
import {
  Activity, AlertTriangle, Check, ChevronDown, Copy, ExternalLink, Eye, EyeOff, FlaskConical, FolderInput,
  ChevronLeft, Layers, MapPin, Pencil, Plus, RefreshCw, Save, Search, Server, ServerCog, ShieldAlert, ShieldCheck, X,
} from "lucide-react";

// Panels and their servers are ONE screen: a server is only a capacity slot of a single panel,
// so it is created, edited and enabled right under the panel it belongs to. Group membership of a
// panel can be set here too (it is saved through the same API the group screen uses).

// ---------- helpers ----------
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
const isStale = (p) => !p.last_health_at || Date.now() - new Date(p.last_health_at).getTime() > STALE_MS;

const KINDS = {
  sanaei: { title: "سنایی (3x-ui)", desc: "پنل 3x-ui / Sanaei با Inbound و ساب‌اسکریپشن", Icon: ServerCog, tone: "in" },
  pasarguard: { title: "پاسارگارد", desc: "PasarGuard با گروه‌ها یا قالب کاربر", Icon: ShieldCheck, tone: "ok" },
  // Mock is only available in dev builds; backend rejects mock panels in production.
  ...(import.meta.env.DEV
    ? { mock: { title: "Mock (آزمایشی)", desc: "فقط برای توسعه و تست؛ در محیط عملیاتی غیرفعال است", Icon: FlaskConical, tone: "wn" } }
    : {}),
};
const kindOf = (k) => KINDS[k] || { title: k, desc: "", Icon: Server, tone: "mu" };

// ---------- small UI parts ----------
function CopyButton({ text }) {
  const [ok, setOk] = useState(false);
  return <button type="button" className="btn btn-g !px-2" aria-label="کپی آدرس" title="کپی آدرس" onClick={async () => { try { await navigator.clipboard.writeText(text); setOk(true); setTimeout(() => setOk(false), 1400); } catch { /* clipboard unavailable */ } }}>{ok ? <Check size={14} /> : <Copy size={14} />}</button>;
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

function Meter({ s }) {
  const u = usage(s), t = capTone(u);
  return <div>
    <div className="mb-1.5 flex items-baseline justify-between text-xs"><span className="text-[var(--mu)]">ظرفیت</span><span className="num font-bold"><span style={{ color: `var(--${t})` }}>{num(s.active_accounts)}</span> از {num(s.capacity)}<span className="mr-1.5 font-normal text-[var(--mu)]">({num(Math.round(u * 100))}٪)</span></span></div>
    <SegMeter value={u} tone={t} max={s.capacity} now={s.active_accounts} label="میزان استفاده از ظرفیت" />
  </div>;
}

// ---------- panel add / edit form ----------
const EMPTY = { kind: "sanaei", name: "", url: "", auth: "token", token: "", user: "", pass: "", inbounds: [], subUrl: "", apiStyle: "auto", groups: [], tpl: "", scope: "groups", verifyTls: true, extra: "" };
const EMPTY_SRV = { on: true, name: "", location: "", capacity: "500" };
const KNOWN = { sanaei: ["inbound_ids", "inbound_id", "sub_base_url", "api_style", "verify_tls"], pasarguard: ["group_ids", "user_template_id", "verify_tls"], mock: [] };
const ints = (a) => (Array.isArray(a) ? a : []).map(Number).filter((n) => Number.isInteger(n) && n > 0);

// Rebuild the form from a stored panel; config keys the form has no field for stay in the JSON box so a save never drops them.
function fromPanel(p) {
  const c = p.config || {}, f = { ...EMPTY, kind: p.kind, name: p.name, url: p.base_url, verifyTls: c.verify_tls !== false };
  if (p.kind === "sanaei") { f.inbounds = ints(c.inbound_ids ?? (c.inbound_id != null ? [c.inbound_id] : [])); f.subUrl = c.sub_base_url || ""; f.apiStyle = c.api_style || "auto"; }
  if (p.kind === "pasarguard") { if (c.user_template_id != null) { f.scope = "template"; f.tpl = String(c.user_template_id); } else f.groups = ints(c.group_ids); }
  const rest = Object.fromEntries(Object.entries(c).filter(([k]) => !(KNOWN[p.kind] || []).includes(k)));
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
function validate(f, withCreds, srv, edit) {
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
  if (!edit && srv.on && !(Number(srv.capacity) >= 1 && Number(srv.capacity) <= 100000)) e.capacity = "ظرفیت باید بین ۱ تا ۱۰۰٬۰۰۰ باشد";
  return e;
}

function PanelDrawer({ panel, groups, idx, onClose, onSubmit, onToggle, onDelete, toggling }) {
  const edit = !!panel;
  const initial = useMemo(() => ({ f: panel ? fromPanel(panel) : EMPTY, srv: EMPTY_SRV, gids: panel ? groups.filter((g) => memberIds(g).includes(panel.id)).map((g) => g.id).sort() : [] }), []); // eslint-disable-line react-hooks/exhaustive-deps
  const [f, setF] = useState(initial.f); const [srv, setSrv] = useState(initial.srv); const [gids, setGids] = useState(initial.gids);
  const base = useRef(JSON.stringify(initial));
  const [changeCred, setChangeCred] = useState(!panel || !panel.has_credentials);
  const [tried, setTried] = useState(false); const [busy, setBusy] = useState(false); const [srvErr, setSrvErr] = useState("");
  const [adv, setAdv] = useState(() => !!(panel && fromPanel(panel).extra));
  const withCreds = changeCred && f.kind !== "mock";
  const set = (k) => (v) => { setSrvErr(""); setF((x) => ({ ...x, [k]: v })); };
  const setS = (k) => (v) => { setSrvErr(""); setSrv((x) => ({ ...x, [k]: v })); };
  const err = useMemo(() => validate(f, withCreds, srv, edit), [f, withCreds, srv, edit]);
  const show = (k) => tried && err[k];
  const dirty = JSON.stringify({ f, srv, gids: [...gids].sort() }) !== base.current || (edit && changeCred && !!panel.has_credentials);
  const insecure = /^http:\/\//i.test(f.url.trim());
  const toggleG = (id) => setGids((x) => (x.includes(id) ? x.filter((y) => y !== id) : [...x, id]));
  const submit = async (check) => {
    setTried(true); if (Object.keys(err).length) { if (err.extra) setAdv(true); return; }
    setBusy(true); setSrvErr("");
    const msg = await onSubmit(buildPayload(f, withCreds), check, { server: !edit && srv.on ? { name: srv.name.trim() || f.name.trim(), location: srv.location.trim(), capacity: Number(srv.capacity) } : null, gids, was: initial.gids });
    setBusy(false); if (msg) setSrvErr(msg);
  };
  const k = kindOf(f.kind), st = panel ? health(panel) : null;
  return <Drawer
    title={edit ? `ویرایش «${panel.name}»` : "افزودن پنل جدید"}
    subtitle={edit ? `${k.title} · شناسه ${sid(panel.id)}` : "اتصال یک پنل VPN و تعریف ظرفیت آن در یک مرحله"}
    icon={edit ? <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint(k.tone)}><k.Icon size={20} /></span> : undefined}
    dirty={dirty} busy={busy} onClose={onClose} error={srvErr}
    danger={edit && <DeleteButton label="حذف پنل" busy={busy || toggling} onClick={() => onDelete(panel)} />}
    footer={<>
      <button className="btn" disabled={busy || (edit && !dirty)} onClick={() => submit(true)}>{busy ? <RefreshCw size={15} className="animate-spin" /> : <Activity size={15} />}{edit ? "ذخیره و بررسی سلامت" : "ثبت و بررسی سلامت"}</button>
      <button className="btn btn-g !py-2 !text-sm" disabled={busy || (edit && !dirty)} onClick={() => submit(false)}>{edit ? <><Save size={14} />فقط ذخیره</> : "فقط ثبت"}</button>
    </>}>
    {edit && <Section title="وضعیت">
      <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2"><Dot s={st} ping /><Badge s={st} /><span className="text-xs text-[var(--mu)]">آخرین بررسی: {panel.last_health_at ? dt(panel.last_health_at) : "هرگز"}</span></div>
        <label className="flex cursor-pointer items-center gap-2 text-xs font-bold"><Switch checked={panel.is_enabled} disabled={toggling} onChange={(v) => onToggle(panel, v)} label={panel.is_enabled ? "غیرفعال‌سازی پنل" : "فعال‌سازی پنل"} />{panel.is_enabled ? "فعال" : "غیرفعال"}</label></div>
      {st === "unhealthy" && panel.last_health_error && <p dir="auto" className="break-words rounded-lg bg-[var(--bdb)] p-3 text-xs leading-6 text-[var(--bd)]"><b>آخرین خطا: </b>{panel.last_health_error}</p>}
      {!panel.is_enabled && <p className="text-[11px] leading-5 text-[var(--mu)]">پنل غیرفعال برای ساخت اکانت جدید انتخاب نمی‌شود و بررسی سلامت خودکار هم برای آن اجرا نمی‌شود. اکانت‌های موجود حذف نمی‌شوند.</p>}
      <p className="text-[11px] text-[var(--mu)]">ایجاد: {dt(panel.created_at)} · آخرین ویرایش: {dt(panel.updated_at)}</p>
    </Section>}

    {!edit && <Section title="۱ · نوع پنل">
      <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="نوع پنل">{Object.entries(KINDS).map(([key, m]) => <button key={key} type="button" role="radio" aria-checked={f.kind === key} onClick={() => set("kind")(key)} className={`card p-3 text-right transition ${f.kind === key ? "!border-[var(--ac)] ring-2 ring-[color-mix(in_srgb,var(--ac)_25%,transparent)]" : "hover:-translate-y-0.5"}`}>
        <span className="grid h-9 w-9 place-items-center rounded-lg" style={tint(m.tone)}><m.Icon size={18} /></span>
        <span className="mt-2 block text-sm font-extrabold">{m.title}</span><span className="mt-1 block text-[11px] leading-5 text-[var(--mu)]">{m.desc}</span></button>)}</div></Section>}

    <Section title={edit ? "اتصال" : "۲ · اتصال"}>
      <Field label="نام نمایشی" error={show("name") || undefined}><input autoFocus className="inp" value={f.name} maxLength={100} placeholder="مثلاً: آلمان - هتزنر ۱" onChange={(e) => set("name")(e.target.value)} /></Field>
      <Field label="آدرس پنل (Base URL)" error={show("url") || undefined} hint="آدرس کامل همراه پورت و web base path">
        <input dir="ltr" inputMode="url" spellCheck={false} className="inp" value={f.url} placeholder="https://panel.example.com:2053/secret-path" onChange={(e) => set("url")(e.target.value)} /></Field>
      {insecure && <p className="flex items-start gap-2 rounded-lg bg-[var(--wnb)] p-3 text-xs leading-6 text-[var(--wn)]"><AlertTriangle size={15} className="mt-1 shrink-0" />آدرس HTTP است؛ در محیط staging/production فقط HTTPS پذیرفته می‌شود.</p>}
    </Section>

    {f.kind !== "mock" && <Section title={`${edit ? "" : "۳ · "}احراز هویت (رمزنگاری‌شده ذخیره می‌شود)`}>
      {edit && panel.has_credentials && !changeCred
        ? <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-[var(--sf2)] px-3 py-2.5"><span className="flex items-center gap-2 text-xs"><ShieldCheck size={15} className="text-[var(--ok)]" />اعتبارنامه ذخیره شده است و نمایش داده نمی‌شود.</span><button type="button" className="btn btn-g" onClick={() => setChangeCred(true)}>تغییر اعتبارنامه</button></div>
        : <>
          <Segmented label="روش ورود" value={f.auth} onChange={set("auth")} options={[["token", f.kind === "sanaei" ? "API Token" : "API Key"], ["login", "نام کاربری و رمز"]]} />
          {f.auth === "token" ? <Field label={f.kind === "sanaei" ? "API Token" : "API Key"} error={show("auth") || undefined}><Secret value={f.token} onChange={set("token")} placeholder="••••••••" /></Field>
            : <div className="grid gap-3 sm:grid-cols-2"><Field label="نام کاربری"><input dir="ltr" autoComplete="off" className="inp" value={f.user} onChange={(e) => set("user")(e.target.value)} /></Field><Field label="رمز عبور"><Secret value={f.pass} onChange={set("pass")} /></Field>{show("auth") && <p className="text-[11px] text-[var(--bd)] sm:col-span-2">{err.auth}</p>}</div>}
          {f.kind === "sanaei" && f.auth === "login" && <p className="text-[11px] leading-5 text-[var(--mu)]">اگر 2FA روی پنل فعال است، ورود با نام کاربری کار نمی‌کند؛ از API Token استفاده کنید.</p>}
          {edit && panel.has_credentials && <button type="button" className="text-xs font-bold text-[var(--mu)] underline" onClick={() => { setChangeCred(false); setF((x) => ({ ...x, token: "", user: "", pass: "" })); }}>انصراف از تغییر اعتبارنامه</button>}
        </>}
    </Section>}

    {f.kind !== "mock" && <Section title={`${edit ? "" : "۴ · "}تنظیمات ${k.title}`}>
      {f.kind === "sanaei" && <>
        <Field label="Inbound IDها" error={show("inbounds") || undefined} hint="شناسه Inboundهایی که کلاینت در آن‌ها ساخته می‌شود؛ بعد از هر عدد Enter بزنید"><Chips values={f.inbounds} onChange={set("inbounds")} placeholder="مثلاً 1" /></Field>
        <Field label="آدرس ساب‌اسکریپشن" error={show("subUrl") || undefined} hint="Sub Port + Sub Path از Settings → Subscription پنل"><input dir="ltr" spellCheck={false} className="inp" value={f.subUrl} placeholder="https://sub.example.com:2096/sub" onChange={(e) => set("subUrl")(e.target.value)} /></Field>
        <Field label="سبک API"><Segmented label="سبک API" value={f.apiStyle} onChange={set("apiStyle")} options={[["auto", "خودکار"], ["v3", "v3"], ["legacy", "Legacy"]]} /></Field></>}
      {f.kind === "pasarguard" && <>
        <Segmented label="محدوده" value={f.scope} onChange={set("scope")} options={[["groups", "Group IDs"], ["template", "قالب کاربر"]]} />
        {f.scope === "groups" ? <Field label="Group IDها" error={show("scope") || undefined}><Chips values={f.groups} onChange={set("groups")} placeholder="مثلاً 1" /></Field>
          : <Field label="شناسه قالب کاربر" error={show("scope") || undefined}><input dir="ltr" inputMode="numeric" className="inp" value={f.tpl} onChange={(e) => set("tpl")(e.target.value.replace(/\D/g, ""))} /></Field>}</>}
      <Toggle checked={f.verifyTls} onChange={set("verifyTls")} label="بررسی گواهی TLS" hint="در محیط عملیاتی خاموش‌کردن آن مجاز نیست؛ فقط برای تست با گواهی self-signed." />
    </Section>}

    {!edit && <Section title="۵ · ظرفیت (اولین سرور)" hint="سرور یعنی سقف اکانت‌های فعال روی این پنل. بعداً می‌توانید سرور بیشتری اضافه کنید.">
      <Toggle checked={srv.on} onChange={setS("on")} label="همین حالا یک سرور برای این پنل بساز" hint="خاموش = پنل بدون سرور ثبت می‌شود و تا اضافه‌کردن سرور اکانتی روی آن ساخته نمی‌شود." />
      {srv.on && <>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="نام سرور" hint="خالی = همان نام پنل"><input className="inp" value={srv.name} maxLength={100} placeholder={f.name || "مثلاً Germany-1"} onChange={(e) => setS("name")(e.target.value)} /></Field>
          <Field label="موقعیت (اختیاری)"><input className="inp" value={srv.location} maxLength={100} placeholder="مثلاً آلمان" onChange={(e) => setS("location")(e.target.value)} /></Field>
        </div>
        <Field label="ظرفیت" error={show("capacity") || undefined}><NumInput value={srv.capacity} onChange={setS("capacity")} suffix="اکانت" placeholder="500" /></Field>
      </>}
    </Section>}

    <Section title={edit ? "بسته‌ها" : "۶ · بسته‌ها (اختیاری)"} hint="بسته مشخص می‌کند محصولات کدام پنل‌ها را برای ساخت اکانت بسنجند. محصولاتی که بسته ندارند روی هر پنل سالمی ساخته می‌شوند.">
      {groups.length
        ? <div className="flex flex-wrap gap-2">{groups.map((g) => { const on = gids.includes(g.id); return <button key={g.id} type="button" aria-pressed={on} className={`btn btn-g !py-1 !text-xs ${on ? "!border-[var(--ac)]" : ""}`} onClick={() => toggleG(g.id)}>{on ? <Check size={13} /> : <Plus size={13} />}{g.name}{!g.is_enabled && <span className="text-[var(--mu)]">(غیرفعال)</span>}</button>; })}</div>
        : <p className="text-xs leading-6 text-[var(--mu)]">هنوز بسته‌ای ساخته نشده است. از صفحه‌ی «بسته‌های فروش» می‌توانید بسازید.</p>}
    </Section>

    <section><button type="button" className="flex items-center gap-1.5 text-xs font-bold text-[var(--mu)]" aria-expanded={adv} onClick={() => setAdv(!adv)}><ChevronDown size={14} className={adv ? "" : "-rotate-90"} />تنظیمات پیشرفته (JSON)</button>
      {adv && <div className="mt-2"><Field label="Config اضافه" error={show("extra") || undefined} hint={'روی تنظیمات بالا ادغام می‌شود؛ مثلاً {"timeout": 30}'}><textarea rows={4} dir="ltr" spellCheck={false} className="inp font-mono text-xs" value={f.extra} onChange={(e) => set("extra")(e.target.value)} /></Field></div>}</section>
    {edit && <p className="flex items-start gap-2 rounded-lg bg-[var(--inb)] p-3 text-[11px] leading-5 text-[var(--in)]"><Activity size={14} className="mt-0.5 shrink-0" />با تغییر آدرس، تنظیمات یا اعتبارنامه، وضعیت سلامت به «بررسی‌نشده» برمی‌گردد؛ برای اطمینان از اتصال از «ذخیره و بررسی سلامت» استفاده کنید.</p>}
  </Drawer>;
}

// ---------- one panel with its servers ----------
function ServerRow({ s, panel, busy, onEdit, onToggle, onDelete }) {
  const st = serverState(s, panel), dim = s.is_enabled ? "" : "opacity-60";
  const limited = (s.product_codes || []).length;
  return <li className="grid gap-3 px-4 py-3 transition-colors hover:bg-[var(--sf2)] md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_auto] md:items-center">
    <div className={`flex min-w-0 items-center gap-3 ${dim}`}>
      <span className="tile h-9 w-9" style={tint(st.tone)}><ServerCog size={16} /></span>
      <div className="min-w-0">
        <div className="flex items-center gap-2"><b className="truncate" title={s.name}>{s.name}</b>
          {!s.allow_test && <span className="badge b-mu" title="اکانت تست روی این سرور ساخته نمی‌شود">بدون تست</span>}
          {limited > 0 && <span className="badge b-wn" title="این سرور فقط برای محصولات انتخاب‌شده استفاده می‌شود">فقط {num(limited)} محصول</span>}</div>
        <div className="mt-1 flex items-center gap-2 text-[11px] text-[var(--mu)]">{s.location ? <span className="flex items-center gap-1"><MapPin size={11} />{s.location}</span> : null}<span className={`badge b-${st.tone}`}>{st.label}</span></div>
      </div>
    </div>
    <div className={dim}><Meter s={s} /></div>
    <div className="flex items-center justify-end gap-2">
      <Switch checked={s.is_enabled} disabled={busy} onChange={(v) => onToggle(s, v)} label={`${s.is_enabled ? "غیرفعال‌سازی" : "فعال‌سازی"} ${s.name}`} />
      <button className="btn btn-g" onClick={() => onEdit(s)}><Pencil size={13} />ویرایش</button>
      <DeleteButton compact label={`حذف ${s.name}`} busy={busy} onClick={() => onDelete(s)} />
    </div>
  </li>;
}

const STRIPE = { healthy: "var(--ok)", unhealthy: "var(--bd)", unknown: "var(--wn)" };
function PanelSection({ p, servers, stat, groups, busy, srvBusy, filtered, dense, onCheck, onEdit, onToggle, onDelete, onSrvAdd, onSrvEdit, onSrvToggle, onSrvDelete, onImport }) {
  const h = health(p), k = kindOf(p.kind), u = stat.capacity ? stat.active / stat.capacity : 0, t = capTone(u), stale = isStale(p) && p.is_enabled;
  const [open, setOpen] = useState(true);
  const showServers = !dense && open;
  return <section id={`panel-${p.id}`} className={`card card-i rise stripe overflow-hidden ${p.is_enabled ? "" : "off"}`} style={{ "--stripe": p.is_enabled ? STRIPE[h] : "var(--ln)" }}>
    <header className={`space-y-3 border-b border-[var(--ln)] bg-[linear-gradient(180deg,var(--sf2),var(--sf))] px-5 py-4 ${p.is_enabled ? "" : "opacity-80"}`}>
      <div className="flex flex-wrap items-center gap-4">
        <span className="tile h-12 w-12" style={tint(k.tone)}><k.Icon size={22} /></span>
        <div className="min-w-0 flex-1 basis-60">
          <div className="flex flex-wrap items-center gap-2"><b className="truncate text-base font-extrabold" title={p.name}>{p.name}</b>
            <span className="hp" style={tint(h === "healthy" ? "ok" : h === "unhealthy" ? "bd" : "wn")}><Dot s={h} ping />{HLABEL[h]}</span>
            {!p.is_enabled && <Badge s="disabled" />}</div>
          <div className="mt-1.5 flex min-w-0 items-center gap-1.5"><span className="shrink-0 text-[11px] font-bold text-[var(--mu)]">{k.title}</span><span className="text-[var(--ln)]">·</span><span dir="ltr" className="min-w-0 truncate font-mono text-[11px] text-[var(--mu)]" title={p.base_url}>{p.base_url}</span><CopyButton text={p.base_url} />
            <a className="btn btn-g !px-2" href={p.base_url} target="_blank" rel="noopener noreferrer" aria-label="باز کردن پنل" title="باز کردن پنل"><ExternalLink size={13} /></a></div>
        </div>
        {stat.n > 0 && <div className="flex items-center gap-3" title={`${num(stat.active)} اکانت فعال از ظرفیت ${num(stat.capacity)}`}>
          <Ring value={u} size={54} stroke={6} tone={t} label={`ظرفیت پر: ${Math.round(u * 100)} درصد`}><b className="num text-xs font-extrabold">{num(Math.round(u * 100))}٪</b></Ring>
          <div className="text-[11px] leading-5 text-[var(--mu)]"><b className="num block text-sm text-[var(--tx)]">{num(stat.active)} <span className="font-normal text-[var(--mu)]">/ {num(stat.capacity)}</span></b>{num(stat.n)} سرور</div></div>}
        <div className="flex items-center gap-1.5">
          <Switch checked={p.is_enabled} disabled={busy} onChange={(v) => onToggle(p, v)} label={`${p.is_enabled ? "غیرفعال‌سازی" : "فعال‌سازی"} ${p.name}`} />
          <button className="btn btn-g" onClick={() => onEdit(p)}><Pencil size={13} />ویرایش</button>
          <button className="btn btn-g !px-2" aria-label="بررسی سلامت" title={`بررسی سلامت · آخرین بررسی ${ago(p.last_health_at)}`} disabled={busy} onClick={() => onCheck(p)}><RefreshCw size={13} className={busy ? "animate-spin" : ""} /></button>
          <DeleteButton compact label={`حذف پنل ${p.name}`} busy={busy} onClick={() => onDelete(p)} />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
        <span className="text-[var(--mu)]">بسته‌ها:</span>
        {groups.length ? groups.slice(0, 4).map((g) => <RelChip key={g.id} to="panel-groups" params={{ q: g.name }} tone="wn" Icon={Layers} dim={!g.is_enabled}>{g.name}</RelChip>) : <span className="font-bold text-[var(--wn)]">هیچ — این پنل چیزی نمی‌فروشد</span>}
        {groups.length > 4 && <span className="text-[var(--mu)]">+{num(groups.length - 4)}</span>}
        <span className={`mr-auto flex items-center gap-1 ${stale ? "font-bold text-[var(--wn)]" : "text-[var(--mu)]"}`} title={p.last_health_at ? dt(p.last_health_at) : ""}>{stale && <AlertTriangle size={12} />}آخرین بررسی: {ago(p.last_health_at)}</span>
      </div>
      {h === "unhealthy" && p.last_health_error && <p dir="auto" className="break-words rounded-lg bg-[var(--bdb)] px-3 py-2 text-[11px] leading-5 text-[var(--bd)]">{p.last_health_error}</p>}
    </header>
    {dense
      ? <div className="flex flex-wrap items-center gap-1.5 px-5 py-3">{servers.length ? servers.map((sv) => { const st = serverState(sv, p); return <span key={sv.id} className="spec" title={`${st.label} · ${num(sv.active_accounts)} از ${num(sv.capacity)}`}><span className="h-2 w-2 rounded-full" style={{ background: `var(--${st.ok ? capTone(usage(sv)) : st.tone})` }} />{sv.name}<span className="num font-normal text-[var(--mu)]">{num(sv.active_accounts)}/{num(sv.capacity)}</span></span>; }) : <span className="text-xs font-bold text-[var(--wn)]">بدون سرور</span>}</div>
      : <>
        <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 border-b border-[var(--hair)] px-5 py-2 text-[11px] font-bold text-[var(--mu)] hover:text-[var(--tx)]"><ChevronDown size={14} className={open ? "" : "-rotate-90"} />سرورها (ظرفیت‌ها)<span className="badge b-mu num">{num(servers.length)}</span></button>
        {showServers && (servers.length
          ? <ul className="divide-y divide-[var(--hair)]">{servers.map((sv) => <ServerRow key={sv.id} s={sv} panel={p} busy={srvBusy.has(sv.id)} onEdit={onSrvEdit} onToggle={onSrvToggle} onDelete={onSrvDelete} />)}</ul>
          : <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-5 text-sm"><span className="flex items-center gap-2 text-[var(--wn)]"><AlertTriangle size={15} />{filtered ? "سروری با این فیلتر روی این پنل نیست" : "این پنل هنوز سرور ندارد؛ تا ظرفیت تعریف نشود اکانتی روی آن ساخته نمی‌شود."}</span>{!filtered && <button className="btn" onClick={() => onSrvAdd(p)}><Plus size={15} />افزودن اولین سرور</button>}</div>)}
        {showServers && servers.length > 0 && <footer className="flex flex-wrap items-center gap-2 bg-[var(--sf2)] px-5 py-2.5">
          <button className="btn btn-g" onClick={() => onSrvAdd(p)}><Plus size={13} />سرور جدید</button>
          <button className="btn btn-g" onClick={() => onImport(p)}><FolderInput size={13} />ورود دسته‌جمعی</button>
        </footer>}
      </>}
  </section>;
}

// ---------- page ----------
// Deep links: #/panels?id=<panel> · ?group=<group id> · ?product=<code> · ?add=1 (new panel) · ?id=<panel>&add=server
const PAGE_SIZE = 10;
export default function PanelsView({ api, toast }) {
  const infra = useInfra(api); const { idx } = infra;
  const params = useHashParams();
  const alive = useAlive();
  const [q, setQ] = useState(""); const [filter, setFilter] = useState("all");
  const [only, setOnly] = useState(params.get("id") || ""); const [groupF, setGroupF] = useState(params.get("group") || ""); const [productF, setProductF] = useState(params.get("product") || "");
  const [drawer, setDrawer] = useState(null); const [busy, setBusy] = useState(new Set()); const [bulk, setBulk] = useState(null);
  const [srvDrawer, setSrvDrawer] = useState(null); const [srvBusy, setSrvBusy] = useState(new Set()); const [importFor, setImportFor] = useState(null);
  const [page, setPage] = useState(0); const [sort, setSort] = useState("attention"); const [dense, setDense] = useState("full");
  useEffect(() => { setOnly(params.get("id") || ""); setGroupF(params.get("group") || ""); setProductF(params.get("product") || ""); }, [params]);
  useEffect(() => {
    if (params.get("add") === "1") { setDrawer("add"); clearParam("add"); }
    else if (params.get("add") === "server" && params.get("id")) { setSrvDrawer({ panelId: params.get("id"), serverId: null }); clearParam("add"); }
  }, [params]);
  useEffect(() => { setPage(0); }, [filter, q, only, groupF, productF]);

  const rows = infra.panels.rows, failed = infra.panels.failed, load = infra.panels.load;
  const allServers = infra.servers.rows || [];

  const probe = useCallback(async (p) => {
    setBusy((s) => new Set(s).add(p.id));
    let ok = false, healthy = false;
    try { const r = await authFetch(api.base, `/api/v1/admin/panels/${p.id}/health`, { method: "POST" }); ok = r.ok; healthy = ok && (await r.json()).healthy; } catch { /* network */ }
    if (alive.current) setBusy((s) => { const n = new Set(s); n.delete(p.id); return n; });
    return { ok, healthy };
  }, [api.base, alive]);
  const healthToast = useCallback((p, { ok, healthy }) => toast(!ok ? `بررسی «${p.name}» ناموفق بود` : healthy ? `«${p.name}» سالم است` : `«${p.name}» پاسخ سالم نداد`), [toast]);
  const check = useCallback(async (p, quiet) => {
    const res = await probe(p);
    if (!quiet) { healthToast(p, res); await infra.reload(); }
    return res.healthy;
  }, [probe, healthToast]); // eslint-disable-line react-hooks/exhaustive-deps

  const checkAll = async () => {
    const list = (rows || []).filter((p) => p.is_enabled); if (!list.length) return;
    if (!(await confirmDialog(`سلامت ${num(list.length)} پنل فعال بررسی شود؟`, { title: "بررسی همه پنل‌ها", ok: "شروع" }))) return;
    let done = 0, bad = 0; setBulk({ done, total: list.length });
    const queue = [...list];
    await Promise.all(Array.from({ length: Math.min(3, queue.length) }, async () => { for (let p = queue.shift(); p; p = queue.shift()) { if (!(await check(p, true))) bad++; done++; if (alive.current) setBulk({ done, total: list.length }); } }));
    if (alive.current) setBulk(null);
    toast(bad ? `${num(bad)} پنل از ${num(list.length)} مورد ناسالم است` : "همه پنل‌ها سالم هستند"); await infra.reload();
  };

  // One save = panel (+ first server on create) (+ group membership). Every step reports its own failure.
  const save = async (payload, withCheck, { server, gids, was }) => {
    const editing = drawer !== "add";
    const r = await authFetch(api.base, editing ? `/api/v1/admin/panels/${drawer}` : "/api/v1/admin/panels", { method: editing ? "PATCH" : "POST", body: JSON.stringify(payload) });
    if (!r.ok) return errText(r, editing ? "ذخیره تغییرات ناموفق بود" : "ثبت پنل ناموفق بود");
    const id = editing ? drawer : (await r.json())?.id;
    const notes = [];
    if (!editing && server && id) {
      const sr = await authFetch(api.base, "/api/v1/admin/servers", { method: "POST", body: JSON.stringify({ name: server.name, panel_id: id, location: server.location || null, capacity: server.capacity, product_codes: null, allow_test: true }) });
      if (!sr.ok) notes.push(`ساخت سرور ناموفق بود (${await errText(sr, "خطا")}) — از «سرور جدید» اضافه کنید`);
    }
    const toAdd = gids.filter((g) => !was.includes(g)), toDel = was.filter((g) => !gids.includes(g));
    for (const gid of [...toAdd, ...toDel]) {
      const g = (infra.groups.rows || []).find((x) => x.id === gid); if (!g || !id) continue;
      const cur = memberIds(g), next = toAdd.includes(gid) ? [...cur.filter((x) => x !== id), id] : cur.filter((x) => x !== id);
      const m = await saveGroupPanels(infra.call, g, next); if (m) notes.push(`«${g.name}»: ${m}`);
    }
    setDrawer(null);
    toast(notes.length ? notes.join(" · ") : editing ? "تغییرات ذخیره شد" : server ? "پنل و سرور ثبت شد" : "پنل ثبت شد — مرحله بعد: افزودن سرور");
    // Health probe runs BEFORE the single reload so the reloaded list already shows the fresh status.
    if (withCheck && id) healthToast({ id, name: payload.name }, await probe({ id, name: payload.name }));
    await infra.reload();
    return "";
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
  const srvToggle = async (s, next) => {
    if (!next && !(await confirmDialog(`«${s.name}» غیرفعال شود؟ برای ساخت اکانت جدید انتخاب نمی‌شود؛ اکانت‌های موجود حذف نمی‌شوند.`, { title: "غیرفعال‌سازی سرور", danger: true, ok: "غیرفعال کن" }))) return;
    setSrvBusy((x) => new Set(x).add(s.id));
    let ok = false;
    try { ok = (await authFetch(api.base, `/api/v1/admin/servers/${s.id}/state`, { method: "POST", body: JSON.stringify({ is_enabled: next }) })).ok; } catch { /* network */ }
    if (alive.current) setSrvBusy((x) => { const n = new Set(x); n.delete(s.id); return n; });
    toast(ok ? (next ? `«${s.name}» فعال شد` : `«${s.name}» غیرفعال شد`) : "تغییر وضعیت ناموفق بود");
    if (ok) await infra.servers.load();
  };

  const removePanel = async (p) => {
    const n = (idx.serversByPanel.get(p.id) || []).length;
    setBusy((x) => new Set(x).add(p.id));
    const ok = await removeEntity(infra.call, `/api/v1/admin/panels/${p.id}`, { toast, title: "حذف پنل", done: `«${p.name}» حذف شد`,
      message: `«${p.name}» برای همیشه حذف شود؟${n ? ` ${num(n)} سرور آن هم حذف می‌شود و` : ""} از بسته‌ها خارج می‌شود. پنل واقعی (سنایی/پاسارگارد) دست‌نخورده می‌ماند. اگر روی این پنل اکانت ساخته شده باشد حذف انجام نمی‌شود و باید آن را غیرفعال کنید.` });
    if (alive.current) setBusy((x) => { const m = new Set(x); m.delete(p.id); return m; });
    if (ok) { setDrawer(null); setSrvDrawer(null); await infra.reload(); }
  };
  const removeServer = async (s) => {
    setSrvBusy((x) => new Set(x).add(s.id));
    const ok = await removeEntity(infra.call, `/api/v1/admin/servers/${s.id}`, { toast, title: "حذف سرور", done: `«${s.name}» حذف شد`,
      message: `«${s.name}» برای همیشه حذف شود؟ اگر روی این سرور اکانت ساخته شده باشد حذف انجام نمی‌شود و باید آن را غیرفعال کنید.` });
    if (alive.current) setSrvBusy((x) => { const m = new Set(x); m.delete(s.id); return m; });
    if (ok) { setSrvDrawer(null); await infra.reload(); }
  };

  const attention = (p) => p.is_enabled && health(p) !== "healthy";
  const counts = useMemo(() => { const c = { all: 0, healthy: 0, attention: 0 }; (rows || []).forEach((p) => { c.all++; if (health(p) === "healthy") c.healthy++; if (attention(p)) c.attention++; }); return c; }, [rows]);
  const cap = useMemo(() => { let freeN = 0, total = 0; allServers.forEach((s) => { total += s.capacity || 0; if (serverState(s, idx.panelById.get(s.panel_id)).ok) freeN += free(s); }); return { free: freeN, total }; }, [allServers, idx]);
  const group = groupF ? idx.groupById.get(groupF) : null;
  const groupPanels = useMemo(() => (group ? new Set(memberIds(group)) : null), [group]);
  const productObj = productF ? (infra.products.rows || []).find((x) => x.code === productF) : null;
  const serversOf = (p) => (idx.serversByPanel.get(p.id) || []).filter((s) => !productF || serves(s, productF));
  const filtered = useMemo(() => (rows || []).filter((p) => (!only || p.id === only)
    && (filter === "all" || (filter === "healthy" ? health(p) === "healthy" : attention(p)))
    && (!groupPanels || groupPanels.has(p.id))
    && (!productF || (idx.serversByPanel.get(p.id) || []).some((s) => serves(s, productF)))
    && `${p.name} ${p.base_url} ${kindOf(p.kind).title} ${(idx.serversByPanel.get(p.id) || []).map((s) => `${s.name} ${s.location || ""}`).join(" ")}`.toLowerCase().includes(q.trim().toLowerCase())),
  [rows, filter, q, only, groupPanels, productF, idx]); // eslint-disable-line react-hooks/exhaustive-deps
  const sorted = useMemo(() => {
    const rank = (p) => (!p.is_enabled ? 3 : health(p) === "unhealthy" ? 0 : health(p) === "unknown" ? 1 : 2);
    const by = { attention: (a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name, "fa"), name: (a, b) => a.name.localeCompare(b.name, "fa"),
      free: (a, b) => idx.panelStat(b.id).capacity - idx.panelStat(b.id).active - (idx.panelStat(a.id).capacity - idx.panelStat(a.id).active),
      usage: (a, b) => { const f = (p) => { const x = idx.panelStat(p.id); return x.capacity ? x.active / x.capacity : 0; }; return f(b) - f(a); } };
    return [...filtered].sort(by[sort]);
  }, [filtered, sort, idx]);
  const shown = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const loading = rows === null || infra.loading;
  const editing = drawer && drawer !== "add" ? (rows || []).find((p) => p.id === drawer) : null;
  const srvPanel = srvDrawer ? (rows || []).find((p) => p.id === srvDrawer.panelId) : null;
  const srvEditing = srvDrawer?.serverId ? allServers.find((s) => s.id === srvDrawer.serverId) : null;
  const locations = useMemo(() => [...new Set(allServers.map((s) => s.location).filter(Boolean))].sort(), [allServers]);
  const hasScope = only || groupF || productF;
  const clearScope = () => { setOnly(""); setGroupF(""); setProductF(""); if (window.location.hash.includes("?")) window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}${window.location.hash.split("?")[0]}`); };

  return <div className="space-y-5">
    <InfraChain current="panels" infra={infra} />
    <KpiBar cols={4}>
      <Stat label="همه پنل‌ها" value={counts.all} tone="in" Icon={Server} active={filter === "all"} onClick={() => setFilter("all")} />
      <Stat label="سالم" value={counts.healthy} tone="ok" Icon={ShieldCheck} active={filter === "healthy"} onClick={() => setFilter(filter === "healthy" ? "all" : "healthy")} />
      <Stat label="نیازمند بررسی (ناسالم / بررسی‌نشده)" value={counts.attention} tone={counts.attention ? "bd" : "mu"} Icon={ShieldAlert} active={filter === "attention"} onClick={() => setFilter(filter === "attention" ? "all" : "attention")} />
      <Stat label={`ظرفیت آزاد قابل فروش از ${num(cap.total)}`} value={cap.free} tone={cap.free ? "ok" : "bd"} Icon={ServerCog} ring={cap.total ? cap.free / cap.total : 0} />
    </KpiBar>

    <div className="tool">
      <SearchBox label="جستجوی پنل یا سرور" placeholder="جستجو در پنل، سرور، موقعیت یا آدرس…" value={q} onChange={setQ} />
      {!!(infra.groups.rows || []).length && <select aria-label="فیلتر بسته" className="inp !w-auto !py-2 !text-xs font-bold" value={groupF} onChange={(e) => setGroupF(e.target.value)}><option value="">همه بسته‌ها</option>{(infra.groups.rows || []).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</select>}
      <SortSelect value={sort} onChange={setSort} options={[["attention", "مشکل‌دارها اول"], ["name", "نام"], ["free", "بیشترین ظرفیت آزاد"], ["usage", "بیشترین پُری"]]} />
      <ViewToggle value={dense} onChange={setDense} options={[["full", "کامل"], ["dense", "فشرده"]]} />
      <div className="mr-auto flex items-center gap-2">
        <button className="btn btn-g !py-2 !text-sm" onClick={checkAll} disabled={!!bulk || !counts.all}><RefreshCw size={14} className={bulk ? "animate-spin" : ""} />{bulk ? `${num(bulk.done)} از ${num(bulk.total)}` : "بررسی همه"}</button>
        <button className="btn" onClick={() => setDrawer("add")}><Plus size={16} />افزودن پنل</button>
      </div>
    </div>

    {hasScope && <p className="flex flex-wrap items-center gap-2 rounded-xl bg-[var(--inb)] px-3 py-2 text-xs font-bold text-[var(--in)]">
      {only && <>فقط یک پنل نمایش داده می‌شود</>}{group && <>پنل‌های بسته «{group.name}»</>}{productObj && <>{group || only ? " · " : ""}پنل‌ها و سرورهایی که «{productObj.name}» را پوشش می‌دهند</>}
      <button className="mr-auto underline" onClick={clearScope}>نمایش همه</button></p>}

    {failed && <ErrorBar onRetry={infra.reload}><AlertTriangle size={16} />دریافت پنل‌ها ناموفق بود.</ErrorBar>}

    {loading ? <div className="space-y-4">{[0, 1].map((i) => <div key={i} className="card skel h-56" />)}</div>
      : !filtered.length ? <Empty Icon={Server} title={counts.all ? "پنلی با این فیلتر پیدا نشد" : "هنوز پنلی اضافه نشده"} text={counts.all ? "جستجو یا فیلتر را تغییر دهید." : "برای فروش اکانت، ابتدا یک پنل سنایی یا پاسارگارد به Core وصل کنید؛ ظرفیت (سرور) آن هم در همان مرحله تعریف می‌شود."}>
        {!counts.all && <button className="btn" onClick={() => setDrawer("add")}><Plus size={16} />افزودن اولین پنل</button>}</Empty>
      : <><div className="space-y-4">{shown.map((p) => <PanelSection key={p.id} p={p} servers={serversOf(p)} stat={idx.panelStat(p.id)} groups={idx.groupsByPanel.get(p.id) || []} busy={busy.has(p.id)} srvBusy={srvBusy} filtered={!!productF || !!q.trim()} dense={dense === "dense"}
          onCheck={check} onEdit={(x) => setDrawer(x.id)} onToggle={toggle} onDelete={removePanel} onSrvDelete={removeServer}
          onSrvAdd={(x) => setSrvDrawer({ panelId: x.id, serverId: null })} onSrvEdit={(s) => setSrvDrawer({ panelId: s.panel_id, serverId: s.id })} onSrvToggle={srvToggle} onImport={setImportFor} />)}</div>
        <Paginator page={page} setPage={setPage} total={filtered.length} pageSize={PAGE_SIZE} /></>}

    {drawer && (drawer === "add" || editing) && <PanelDrawer key={drawer} panel={drawer === "add" ? null : editing} groups={infra.groups.rows || []} idx={idx} onClose={() => setDrawer(null)} onSubmit={save} onToggle={toggle} onDelete={removePanel} toggling={editing ? busy.has(editing.id) : false} />}
    {srvDrawer && srvPanel && (!srvDrawer.serverId || srvEditing) && <ServerForm key={`${srvDrawer.panelId}:${srvDrawer.serverId || "new"}`} api={api} toast={toast} infra={infra} panel={srvPanel} server={srvEditing || null} locations={locations}
      toggling={srvEditing ? srvBusy.has(srvEditing.id) : false} onToggle={srvToggle} onDelete={removeServer} onSaved={infra.reload} onClose={() => setSrvDrawer(null)} />}
    {importFor && <ServerImport api={api} toast={toast} panel={importFor} onClose={() => setImportFor(null)} onDone={infra.reload} />}
  </div>;
}
