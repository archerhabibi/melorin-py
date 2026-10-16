import { useMemo, useRef, useState } from "react";
import { AlertTriangle, ChevronDown, Layers, MapPin, Plus, RefreshCw, Save, Server, Upload } from "lucide-react";
import { authFetch } from "./api.js";
import { Badge, dt, sid } from "./ui.jsx";
import { Drawer, Field, NumInput, Section, Segmented, Switch, Toggle, DeleteButton, errText, num, tint } from "./kit.jsx";
import { RelChip, Warn, serverState } from "./infra.jsx";

// A server is only a capacity slot of ONE panel, so this form never asks "which panel":
// the panel is the context it is opened from (PanelsView). Moving a server to another panel is
// kept as an advanced edit, allowed only while the server has no accounts.
const PRESETS = [50, 100, 250, 500, 1000];
const EMPTY = (panel, name = "") => ({ name, panel_id: panel?.id || "", location: "", capacity: "500", all: true, codes: [], allow_test: true });
const fromServer = (s) => ({ name: s.name, panel_id: s.panel_id, location: s.location || "", capacity: String(s.capacity), all: !s.product_codes?.length, codes: s.product_codes || [], allow_test: !!s.allow_test });
const payload = (f) => ({ name: f.name.trim(), panel_id: f.panel_id, location: f.location.trim() || null, capacity: Number(f.capacity), product_codes: f.all ? null : [...f.codes].sort(), allow_test: f.allow_test });

function validate(f) {
  const e = {};
  if (!f.name.trim()) e.name = "نام سرور را وارد کنید";
  const c = Number(f.capacity);
  if (!(c >= 1 && c <= 100000)) e.capacity = "ظرفیت باید بین ۱ تا ۱۰۰٬۰۰۰ باشد";
  if (!f.all && !f.codes.length) e.codes = "حداقل یک محصول انتخاب کنید یا «همه محصولات» را بزنید";
  return e;
}

function ProductPicker({ products, value, onChange }) {
  const known = new Set((products || []).map((p) => p.code));
  const toggle = (code) => onChange(value.includes(code) ? value.filter((c) => c !== code) : [...value, code]);
  const items = [...(products || []).map((p) => ({ code: p.code, name: p.name })), ...value.filter((c) => !known.has(c)).map((code) => ({ code, name: "محصول ناشناخته", stale: true }))];
  if (products === null) return <div className="skel h-16" />;
  if (!items.length) return <p className="rounded-lg bg-[var(--sf2)] p-3 text-xs leading-6 text-[var(--mu)]">هنوز محصولی تعریف نشده است.</p>;
  return <div className="flex flex-wrap gap-2">{items.map((it) => {
    const on = value.includes(it.code);
    return <button key={it.code} type="button" aria-pressed={on} onClick={() => toggle(it.code)}
      className={`rounded-xl border px-3 py-2 text-right text-xs transition ${on ? "border-[var(--ac)] bg-[var(--sf)] font-bold ring-2 ring-[color-mix(in_srgb,var(--ac)_22%,transparent)]" : "border-[var(--ln)] bg-[var(--sf2)] hover:border-[var(--mu)]"} ${it.stale ? "!border-[var(--wn)]" : ""}`}>
      <span className="block">{it.name}</span><span dir="ltr" className="block text-right font-mono text-[10px] text-[var(--mu)]">{it.code}</span></button>;
  })}</div>;
}

/**
 * Add / edit a server of `panel` (POST /admin/servers, PATCH /admin/servers/{id}).
 * `server` null = add. Edit sends only the fields that changed.
 */
export function ServerForm({ api, infra, panel: panelProp, server, locations = [], toggling, onToggle, onDelete, toast, onClose, onSaved }) {
  const edit = !!server;
  const panels = infra.panels.rows || [], products = infra.products.failed ? [] : infra.products.rows, idx = infra.idx;
  const siblings = panelProp ? (idx.serversByPanel.get(panelProp.id) || []).length : 0;
  const [f, setF] = useState(() => (server ? fromServer(server) : EMPTY(panelProp, siblings ? `${panelProp.name} ${num(siblings + 1)}` : panelProp?.name || "")));
  const base = useRef(JSON.stringify(f));
  const [tried, setTried] = useState(false); const [busy, setBusy] = useState(false); const [srvErr, setSrvErr] = useState("");
  const [adv, setAdv] = useState(() => !!server?.product_codes?.length);
  const first = useRef();
  const set = (k) => (v) => { setSrvErr(""); setF((x) => ({ ...x, [k]: v })); };
  const err = useMemo(() => validate(f), [f]);
  const dirty = JSON.stringify(f) !== base.current;
  const panel = panels.find((p) => p.id === f.panel_id) || panelProp;
  const canMove = edit && !(server.total_accounts > 0) && panels.length > 1;
  const showErr = (k) => tried && err[k];
  const active = server?.active_accounts || 0, cap = Number(f.capacity) || 0;

  const submit = async (another) => {
    setTried(true); if (Object.keys(err).length) { if (err.codes) setAdv(true); return; }
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
        const next = { ...EMPTY(panel), location: f.location, capacity: f.capacity, all: f.all, codes: f.codes, allow_test: f.allow_test };
        base.current = JSON.stringify(next); setF(next); setTried(false); first.current?.focus();
      } else onClose();
    } catch { setSrvErr("ارتباط با سرور برقرار نشد"); } finally { setBusy(false); }
  };

  const st = serverState({ is_enabled: server ? server.is_enabled : true, capacity: cap, active_accounts: active }, panel);
  const groups = panel ? idx.groupsByPanel.get(panel.id) || [] : [];

  return <Drawer
    title={edit ? `ویرایش «${server.name}»` : "افزودن سرور"}
    subtitle={`روی پنل «${panel?.name || "—"}»${edit ? ` · شناسه ${sid(server.id)}` : ""}`}
    icon={<span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint(edit && !server.is_enabled ? "mu" : "in")}><Server size={20} /></span>}
    dirty={dirty} busy={busy} onClose={onClose} error={srvErr}
    danger={edit && onDelete && <DeleteButton label="حذف سرور" busy={busy} onClick={() => onDelete(server)} />}
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

    <Section title="مشخصات" hint="سرور یعنی یک ظرفیت مشخص روی همین پنل؛ وقتی پر شود، اکانت بعدی روی سرور دیگر ساخته می‌شود.">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="نام سرور" error={showErr("name")}><input ref={first} autoFocus className="inp" value={f.name} maxLength={100} placeholder="مثلاً Germany-1" onChange={(e) => set("name")(e.target.value)} /></Field>
        <Field label="موقعیت (اختیاری)" hint="فقط برای نمایش و سازمان‌دهی">
          <div className="relative"><MapPin size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[var(--mu)]" />
            <input list="srv-locations" className="inp pr-9" value={f.location} maxLength={100} placeholder="مثلاً آلمان" onChange={(e) => set("location")(e.target.value)} />
            <datalist id="srv-locations">{locations.map((l) => <option key={l} value={l} />)}</datalist></div></Field>
      </div>
    </Section>

    <Section title="ظرفیت" hint="سقف اکانت‌های فعال روی این سرور.">
      <Field label="تعداد اکانت فعال" error={showErr("capacity")}><NumInput value={f.capacity} onChange={set("capacity")} suffix="اکانت" placeholder="500" /></Field>
      <div className="flex flex-wrap gap-1.5">{PRESETS.map((n) => <button key={n} type="button" onClick={() => set("capacity")(String(n))} className={`btn btn-g ${Number(f.capacity) === n ? "!border-[var(--ac)]" : ""}`}>{num(n)}</button>)}</div>
      {edit && cap > 0 && cap < active && <p className="flex items-start gap-2 rounded-lg bg-[var(--wnb)] p-3 text-xs leading-6 text-[var(--wn)]"><AlertTriangle size={15} className="mt-1 shrink-0" />ظرفیت از تعداد اکانت‌های فعال ({num(active)}) کمتر است؛ اکانت جدید ساخته نمی‌شود ولی اکانت‌های موجود دست‌نخورده می‌مانند.</p>}
      <Toggle checked={f.allow_test} onChange={set("allow_test")} label="اکانت تست روی این سرور مجاز باشد" />
    </Section>

    <section>
      <button type="button" className="flex items-center gap-1.5 text-xs font-bold text-[var(--mu)]" aria-expanded={adv} onClick={() => setAdv(!adv)}><ChevronDown size={14} className={adv ? "" : "-rotate-90"} />تنظیمات پیشرفته{!f.all && <span className="badge b-wn">محدود به {num(f.codes.length)} محصول</span>}</button>
      {adv && <div className="mt-3 space-y-4">
        <Section title="محدود کردن محصولات" hint="معمولاً لازم نیست: محصول از طریق «گروه پنل» به پنل می‌رسد. فقط وقتی استفاده کنید که این سرور باید اختصاصاً برای چند محصول مشخص باشد.">
          <Segmented label="محدوده محصولات" value={f.all ? "all" : "some"} onChange={(v) => set("all")(v === "all")} options={[["all", "همه محصولات"], ["some", "فقط محصولات انتخابی"]]} />
          {!f.all && <><ProductPicker products={products} value={f.codes} onChange={set("codes")} />{showErr("codes") && <p className="text-[11px] text-[var(--bd)]">{err.codes}</p>}</>}
        </Section>
        {canMove && <Section title="انتقال به پنل دیگر" hint="فقط تا وقتی سرور هیچ اکانتی ندارد ممکن است.">
          <select aria-label="پنل سرور" className="inp" value={f.panel_id} onChange={(e) => set("panel_id")(e.target.value)}>{panels.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
        </Section>}
      </div>}
    </section>

    <div className="space-y-2 rounded-xl bg-[var(--sf2)] p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2"><span className="font-bold text-[var(--mu)]">وضعیت فروش:</span><span className={`badge b-${st.tone}`}>{st.label}</span></div>
      <div className="flex flex-wrap items-center gap-1.5"><span className="font-bold text-[var(--mu)]">گروه‌های این پنل:</span>
        {groups.length ? groups.map((g) => <RelChip key={g.id} to="panel-groups" params={{ q: g.name }} tone="wn" Icon={Layers} dim={!g.is_enabled}>{g.name}</RelChip>) : <span className="text-[var(--mu)]">هیچ — محصولات «بدون گروه» روی آن ساخته می‌شوند</span>}</div>
      {panel && panel.health_status !== "healthy" && <Warn>پنل «{panel.name}» {panel.is_enabled ? "سالم نیست یا هنوز بررسی نشده" : "غیرفعال است"}؛ تا آن موقع روی این سرور اکانت جدید ساخته نمی‌شود.</Warn>}
    </div>
  </Drawer>;
}

/* ---------- bulk import of servers for ONE panel ---------- */
const parseLine = (line) => {
  const [name = "", location = "", capacity = "", codes = ""] = line.split(",").map((s) => s.trim());
  const cap = capacity === "" ? 500 : parseInt(capacity, 10);
  return { name, location, capacity: cap, product_codes: codes ? codes.split("|").map((s) => s.trim()).filter(Boolean) : [], bad: !name ? "نام خالی" : !(cap >= 1 && cap <= 100000) ? "ظرفیت نامعتبر" : "" };
};

export function ServerImport({ api, panel, toast, onClose, onDone }) {
  const [text, setText] = useState(""); const [busy, setBusy] = useState(false);
  const rows = useMemo(() => text.split("\n").map((l) => l.trim()).filter((l) => l && !l.startsWith("#")).map(parseLine), [text]);
  const good = rows.filter((r) => !r.bad);
  const run = async () => {
    setBusy(true); let ok = 0, fail = [];
    for (const r of good) {
      try {
        const res = await authFetch(api.base, "/api/v1/admin/servers", { method: "POST", body: JSON.stringify({ name: r.name, location: r.location || null, capacity: r.capacity, product_codes: r.product_codes.length ? r.product_codes : null, panel_id: panel.id }) });
        if (res.ok) ok++; else fail.push(`${r.name}: ${await errText(res, "ناموفق")}`);
      } catch { fail.push(`${r.name}: ارتباط برقرار نشد`); }
    }
    setBusy(false);
    toast(fail.length ? `${num(ok)} از ${num(good.length)} سرور ساخته شد — ${fail[0]}` : `${num(ok)} سرور ساخته شد`);
    if (ok) await onDone();
    if (!fail.length) onClose();
  };
  return <Drawer title="ورود دسته‌جمعی سرور" subtitle={`روی پنل «${panel.name}»`} icon={<span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint("in")}><Upload size={20} /></span>} dirty={!!text.trim()} busy={busy} onClose={onClose}
    footer={<button className="btn" disabled={busy || !good.length} onClick={run}>{busy ? <RefreshCw size={15} className="animate-spin" /> : <Upload size={15} />}ساخت {num(good.length)} سرور</button>}>
    <Section title="داده CSV" hint="هر خط یک سرور: نام, موقعیت, ظرفیت, کدهای محصول با | (فقط نام لازم است؛ ظرفیت خالی = ۵۰۰). خط‌های شروع‌شده با # نادیده گرفته می‌شوند.">
      <textarea dir="ltr" rows={7} className="inp font-mono text-xs" placeholder={"de-1, Frankfurt, 100\nde-2, Frankfurt, 250, plan_1m|plan_3m"} value={text} onChange={(e) => setText(e.target.value)} />
    </Section>
    {rows.length > 0 && <div className="overflow-auto rounded-xl border border-[var(--ln)]"><table className="tbl"><thead><tr><th>نام</th><th>موقعیت</th><th>ظرفیت</th><th>محصولات</th></tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i} className={r.bad ? "!bg-[var(--bdb)]" : ""}><td>{r.name || "—"}{r.bad && <span className="mr-2 text-[11px] font-bold text-[var(--bd)]">{r.bad}</span>}</td><td>{r.location || "—"}</td><td>{Number.isFinite(r.capacity) ? num(r.capacity) : "—"}</td><td className="text-xs">{r.product_codes.join("، ") || "همه"}</td></tr>)}</tbody></table></div>}
  </Drawer>;
}
