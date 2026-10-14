import { useMemo, useRef, useState } from "react";
import { AlertTriangle, MapPin, Plus, RefreshCw, Save, Server } from "lucide-react";
import { authFetch } from "./api.js";
import { Badge, dt, sid } from "./ui.jsx";
import { Drawer, Field, NumInput, Section, Segmented, Switch, Toggle, errText, num, tint } from "./kit.jsx";

const PRESETS = [50, 100, 250, 500, 1000];
const EMPTY = (panelId) => ({ name: "", panel_id: panelId || "", location: "", capacity: "500", all: true, codes: [], allow_test: true });
const fromServer = (s) => ({ name: s.name, panel_id: s.panel_id, location: s.location || "", capacity: String(s.capacity), all: !s.product_codes?.length, codes: s.product_codes || [], allow_test: !!s.allow_test });
const payload = (f) => ({ name: f.name.trim(), panel_id: f.panel_id, location: f.location.trim() || null, capacity: Number(f.capacity), product_codes: f.all ? null : [...f.codes].sort(), allow_test: f.allow_test });
const health = (p) => (p?.health_status === "healthy" || p?.health_status === "unhealthy" ? p.health_status : "unknown");

function validate(f) {
  const e = {};
  if (!f.name.trim()) e.name = "نام سرور را وارد کنید";
  if (!f.panel_id) e.panel_id = "یک پنل انتخاب کنید";
  const c = Number(f.capacity);
  if (!(c >= 1 && c <= 100000)) e.capacity = "ظرفیت باید بین ۱ تا ۱۰۰٬۰۰۰ باشد";
  if (!f.all && !f.codes.length) e.codes = "حداقل یک محصول انتخاب کنید یا «همه محصولات» را بزنید";
  return e;
}

function PanelPicker({ panels, value, onChange, disabled }) {
  return <div role="radiogroup" aria-label="پنل" className="max-h-56 space-y-2 overflow-y-auto">
    {panels.map((p) => {
      const on = value === p.id, h = health(p);
      return <button key={p.id} type="button" role="radio" aria-checked={on} disabled={disabled} onClick={() => onChange(p.id)}
        className={`flex w-full items-center gap-3 rounded-xl border p-3 text-right transition disabled:cursor-not-allowed disabled:opacity-60 ${on ? "border-[var(--ac)] bg-[var(--sf)] ring-2 ring-[color-mix(in_srgb,var(--ac)_22%,transparent)]" : "border-[var(--ln)] bg-[var(--sf2)] hover:border-[var(--mu)]"}`}>
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg" style={tint(h === "healthy" ? "ok" : h === "unhealthy" ? "bd" : "mu")}><Server size={17} /></span>
        <span className="min-w-0 flex-1"><span className="block truncate text-sm font-extrabold">{p.name}</span><span dir="ltr" className="block truncate text-right font-mono text-[11px] text-[var(--mu)]">{p.base_url}</span></span>
        <span className="flex flex-col items-end gap-1"><Badge s={h} />{!p.is_enabled && <Badge s="disabled" />}</span>
      </button>;
    })}
  </div>;
}

function ProductPicker({ products, value, onChange }) {
  const known = new Set((products || []).map((p) => p.code));
  const toggle = (code) => onChange(value.includes(code) ? value.filter((c) => c !== code) : [...value, code]);
  const items = [...(products || []).map((p) => ({ code: p.code, name: p.name })), ...value.filter((c) => !known.has(c)).map((code) => ({ code, name: "محصول ناشناخته", stale: true }))];
  if (products === null) return <div className="skel h-16" />;
  if (!items.length) return <p className="rounded-lg bg-[var(--sf2)] p-3 text-xs leading-6 text-[var(--mu)]">هنوز محصولی تعریف نشده است؛ ابتدا از بخش «محصولات VPN» محصول بسازید.</p>;
  return <div className="flex flex-wrap gap-2">{items.map((it) => {
    const on = value.includes(it.code);
    return <button key={it.code} type="button" aria-pressed={on} onClick={() => toggle(it.code)}
      className={`rounded-xl border px-3 py-2 text-right text-xs transition ${on ? "border-[var(--ac)] bg-[var(--sf)] font-bold ring-2 ring-[color-mix(in_srgb,var(--ac)_22%,transparent)]" : "border-[var(--ln)] bg-[var(--sf2)] hover:border-[var(--mu)]"} ${it.stale ? "!border-[var(--wn)]" : ""}`}>
      <span className="block">{it.name}</span><span dir="ltr" className="block text-right font-mono text-[10px] text-[var(--mu)]">{it.code}</span></button>;
  })}</div>;
}

/**
 * Add / edit a VPN server (POST /admin/servers, PATCH /admin/servers/{id}).
 * `server` null = add. Edit sends only the fields that changed.
 */
export function ServerForm({ api, panels, products, locations = [], server, toggling, onToggle, toast, onClose, onSaved }) {
  const edit = !!server;
  const [f, setF] = useState(() => (server ? fromServer(server) : EMPTY(panels.find((p) => p.is_enabled)?.id || panels[0]?.id)));
  const base = useRef(JSON.stringify(f));
  const [tried, setTried] = useState(false); const [busy, setBusy] = useState(false); const [srvErr, setSrvErr] = useState("");
  const first = useRef();
  const set = (k) => (v) => { setSrvErr(""); setF((x) => ({ ...x, [k]: v })); };
  const err = useMemo(() => validate(f), [f]);
  const dirty = JSON.stringify(f) !== base.current;
  const panel = panels.find((p) => p.id === f.panel_id);
  const locked = edit && server.total_accounts > 0;
  const showErr = (k) => tried && err[k];
  const active = server?.active_accounts || 0, cap = Number(f.capacity) || 0;

  const submit = async (another) => {
    setTried(true); if (Object.keys(err).length) return;
    const now = payload(f);
    let body = now, url = "/api/v1/admin/servers", method = "POST";
    if (edit) {
      const was = payload(fromServer(server));
      body = Object.fromEntries(Object.entries(now).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(was[k])));
      if (!Object.keys(body).length) { onClose(); return; }
      url = `/api/v1/admin/servers/${server.id}`; method = "PATCH";
    }
    setBusy(true); setSrvErr("");
    try {
      const r = await authFetch(api.base, url, { method, body: JSON.stringify(body) });
      if (!r.ok) { setSrvErr(await errText(r, edit ? "ذخیره تغییرات ناموفق بود" : "ثبت سرور ناموفق بود")); return; }
      toast(edit ? "تغییرات سرور ذخیره شد" : "سرور ثبت شد");
      await onSaved();
      if (another && !edit) {
        const next = { ...EMPTY(f.panel_id), location: f.location, capacity: f.capacity, all: f.all, codes: f.codes, allow_test: f.allow_test };
        base.current = JSON.stringify(next); setF(next); setTried(false); first.current?.focus();
      } else onClose();
    } catch { setSrvErr("ارتباط با سرور برقرار نشد"); } finally { setBusy(false); }
  };

  if (!edit && !panels.length) return <Drawer title="افزودن سرور" onClose={onClose} footer={null}>
    <div className="card grid place-items-center gap-2 p-10 text-center"><span className="grid h-12 w-12 place-items-center rounded-2xl bg-[var(--mb)] text-[var(--mu)]"><Server size={22} /></span>
      <h3 className="font-extrabold">ابتدا یک پنل اضافه کنید</h3><p className="max-w-xs text-sm leading-7 text-[var(--mu)]">هر سرور زیر یک پنل ثبت می‌شود؛ از تب «پنل‌ها» یک پنل بسازید و بعد برگردید.</p></div>
  </Drawer>;

  return <Drawer
    title={edit ? `ویرایش «${server.name}»` : "افزودن سرور جدید"}
    subtitle={edit ? `${server.panel_name} · شناسه ${sid(server.id)}` : "سرور ظرفیت و محدوده فروش را روی یک پنل مشخص می‌کند"}
    icon={<span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint(edit && !server.is_enabled ? "mu" : "in")}><Server size={20} /></span>}
    dirty={dirty} busy={busy} onClose={onClose} error={srvErr}
    footer={<>
      <button className="btn" disabled={busy || (edit && !dirty)} onClick={() => submit(false)}>{busy ? <RefreshCw size={15} className="animate-spin" /> : <Save size={15} />}{edit ? "ذخیره تغییرات" : "ثبت سرور"}</button>
      {!edit && <button className="btn btn-g !py-2 !text-sm" disabled={busy} onClick={() => submit(true)}><Plus size={14} />ثبت و افزودن دیگری</button>}
    </>}>
    {edit && <Section title="وضعیت">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="flex items-center gap-2"><Badge s={server.is_enabled ? "active" : "disabled"} /><span className="text-xs text-[var(--mu)]">{num(server.active_accounts)} اکانت فعال از {num(server.capacity)} ظرفیت</span></span>
        <label className="flex items-center gap-2 text-xs font-bold"><Switch checked={server.is_enabled} disabled={toggling} onChange={(v) => onToggle(server, v)} label="فعال بودن سرور" />{server.is_enabled ? "فعال" : "غیرفعال"}</label>
      </div>
      {!server.is_enabled && <p className="text-[11px] leading-5 text-[var(--mu)]">سرور غیرفعال برای اکانت جدید انتخاب نمی‌شود؛ اکانت‌های موجود حذف نمی‌شوند.</p>}
      <p className="text-[11px] text-[var(--mu)]">ایجاد: {dt(server.created_at)} · آخرین ویرایش: {dt(server.updated_at)}</p>
    </Section>}

    <Section title={edit ? "مشخصات" : "۱ · مشخصات"}>
      <Field label="نام سرور" error={showErr("name")}><input ref={first} autoFocus className="inp" value={f.name} maxLength={100} placeholder="مثلاً Germany-1" onChange={(e) => set("name")(e.target.value)} /></Field>
      <Field label="موقعیت (اختیاری)" hint="برای نمایش و سازمان‌دهی؛ بر انتخاب سرور اثری ندارد">
        <div className="relative"><MapPin size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[var(--mu)]" />
          <input list="srv-locations" className="inp pr-9" value={f.location} maxLength={100} placeholder="مثلاً آلمان" onChange={(e) => set("location")(e.target.value)} />
          <datalist id="srv-locations">{locations.map((l) => <option key={l} value={l} />)}</datalist></div></Field>
    </Section>

    <Section title={edit ? "پنل" : "۲ · پنل"} hint={locked ? "این سرور اکانت دارد؛ اکانت‌ها روی همین پنل ساخته شده‌اند و تغییر پنل ممکن نیست. برای انتقال، سرور جدید بسازید و این را غیرفعال کنید." : undefined}>
      <PanelPicker panels={panels} value={f.panel_id} onChange={set("panel_id")} disabled={locked} />
      {showErr("panel_id") && <p className="text-[11px] text-[var(--bd)]">{err.panel_id}</p>}
      {panel && (health(panel) !== "healthy" || !panel.is_enabled) && <p className="flex items-start gap-2 rounded-lg bg-[var(--wnb)] p-3 text-xs leading-6 text-[var(--wn)]"><AlertTriangle size={15} className="mt-1 shrink-0" />{!panel.is_enabled ? "این پنل غیرفعال است" : health(panel) === "unhealthy" ? "پنل ناسالم است" : "سلامت این پنل هنوز بررسی نشده"}؛ تا وقتی پنل فعال و سالم نباشد، روی این سرور اکانت جدید ساخته نمی‌شود.</p>}
    </Section>

    <Section title={edit ? "ظرفیت" : "۳ · ظرفیت"} hint="سقف اکانت‌های فعال روی این سرور؛ با پر شدن، سرور بعدی انتخاب می‌شود">
      <Field label="تعداد اکانت فعال" error={showErr("capacity")}><NumInput value={f.capacity} onChange={set("capacity")} suffix="اکانت" placeholder="500" /></Field>
      <div className="flex flex-wrap gap-1.5">{PRESETS.map((n) => <button key={n} type="button" onClick={() => set("capacity")(String(n))} className={`btn btn-g ${Number(f.capacity) === n ? "!border-[var(--ac)]" : ""}`}>{num(n)}</button>)}</div>
      {edit && cap > 0 && cap < active && <p className="flex items-start gap-2 rounded-lg bg-[var(--wnb)] p-3 text-xs leading-6 text-[var(--wn)]"><AlertTriangle size={15} className="mt-1 shrink-0" />ظرفیت از تعداد اکانت‌های فعال ({num(active)}) کمتر است؛ اکانت جدید ساخته نمی‌شود ولی اکانت‌های موجود دست‌نخورده می‌مانند.</p>}
    </Section>

    <Section title={edit ? "محصولات" : "۴ · محصولات و تست"}>
      <Segmented label="محدوده محصولات" value={f.all ? "all" : "some"} onChange={(v) => set("all")(v === "all")} options={[["all", "همه محصولات"], ["some", "فقط محصولات انتخابی"]]} />
      {!f.all && <><ProductPicker products={products} value={f.codes} onChange={set("codes")} />{showErr("codes") && <p className="text-[11px] text-[var(--bd)]">{err.codes}</p>}</>}
      <Toggle checked={f.allow_test} onChange={set("allow_test")} label="اکانت تست روی این سرور مجاز باشد" hint="با خاموش‌کردن، اکانت‌های تست روی این سرور ساخته نمی‌شوند." />
    </Section>
  </Drawer>;
}
