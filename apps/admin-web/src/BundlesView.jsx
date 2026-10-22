import { useEffect, useMemo, useRef, useState } from "react";
import { confirmDialog } from "./ui.jsx";
import { ArrowDown, ArrowUp, CheckCircle2, ChevronDown, Layers, Pencil, Plus, Search, ShieldAlert, X } from "lucide-react";
import { Bar, Drawer, Empty, ErrorBar, Field, KpiBar, NumInput, Paginator, SearchBox, Section, Segmented, SortSelect, Stat, Switch, Toggle, ViewToggle, DeleteButton, capTone, errText, num, removeEntity, tint, useAlive, useRows } from "./kit.jsx";
import { Dot, InfraChain, Warn, clearParam, health as hs, infraHref, memberIds, useHashParams, useInfra } from "./infra.jsx";

// A sales bundle is a SALES BUNDLE (بسته فروش): panels + connection kind + the packages it sells, each with
// its own price. Customers pick a bundle, so the bundle is the only way an account gets sold; there is no
// bundle-less route. Selection / naming / reseller policy are advanced options: most bundles never change them.
const API = "/api/v1/admin/bundles";
const MODES = {
  automatic: ["خودکار", "سیستم پنلی را انتخاب می‌کند که اکانت فعال کمتری دارد؛ مشتری چیزی نمی‌بیند."],
  manual: ["انتخاب مشتری", "مشتری هنگام خرید یکی از پنل‌های بسته را با «نام نمایشی» که شما می‌دهید انتخاب می‌کند."],
};

function Quota({ sold, limit }) {
  const pct = limit ? Math.min(100, Math.round((sold / limit) * 100)) : 0;
  const full = limit && sold >= limit, warn = limit && pct >= 80;
  return <div>
    <div className="mb-1.5 flex items-center justify-between text-[11px]"><span className="text-[var(--mu)]">سقف فروش بسته</span><b className={`num ${full ? "text-[var(--bd)]" : ""}`}>{num(sold)} / {limit ? num(limit) : "نامحدود"}{full ? " · پر شده" : ""}</b></div>
    {limit ? <Bar value={pct / 100} tone={full ? "bd" : warn ? "wn" : "ok"} label="سهمیه فروش" /> : <div className="bar"><i style={{ width: "100%", background: "repeating-linear-gradient(135deg,var(--mb) 0 6px,transparent 6px 12px)" }} /></div>}
  </div>;
}

/** Why an enabled group cannot sell right now, or "" when it can. */
const groupIssue = (g, stat) => (!g.is_enabled ? "" : !(g.panels || []).length ? "پنلی ندارد" : !stat.live ? "هیچ سرور آماده‌ای ندارد" : "");

const fromPrice = (products) => {
  const cur = [...new Set(products.map((p) => p.currency))];
  if (cur.length !== 1 || !products.length) return null;
  return `${num(Math.min(...products.map((p) => p.main_price)))} ${{ IRT: "تومان", USD: "دلار", USDT: "تتر", XTR: "ستاره" }[cur[0]] || cur[0]}`;
};

/** Two switches: the main store, and resellers. Turning the main store off turns resellers off too. */
function Switches({ g, busy, hasResellers, onToggle, onToggleReseller }) {
  return <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
    <label className="flex cursor-pointer items-center gap-2 text-xs font-bold"><Switch checked={g.is_enabled} disabled={busy} onChange={(v) => onToggle(g, v)} label={`فعال‌سازی ${g.name} در فروشگاه اصلی`} />{hasResellers ? "فروشگاه اصلی" : g.is_enabled ? "فعال" : "غیرفعال"}</label>
    {hasResellers && <label className={`flex cursor-pointer items-center gap-2 text-xs font-bold ${g.is_enabled ? "" : "opacity-50"}`} title={g.is_enabled ? "" : "ابتدا در فروشگاه اصلی فعال کنید"}><Switch checked={g.is_enabled && g.reseller_enabled} disabled={busy || !g.is_enabled} onChange={(v) => onToggleReseller(g, v)} label={`فعال‌سازی ${g.name} برای نمایندگان`} />نمایندگان</label>}
  </div>;
}

function GroupCard({ g, stat, products, busy, hasResellers, onEdit, onToggle, onToggleReseller, onDelete }) {
  const ms = g.panels || [], dim = g.is_enabled ? "" : "opacity-55", issue = groupIssue(g, stat);
  const state = !g.is_enabled ? "off" : issue ? "bd" : "ok";
  const active = products.filter((p) => p.is_active).length;
  const from = fromPrice(products);
  return <article className={`card card-i rise stripe flex flex-col gap-4 p-5 ${state === "off" ? "off" : ""}`} style={{ "--stripe": state === "ok" ? "var(--ok)" : state === "bd" ? "var(--bd)" : "var(--ln)" }}>
    <div className={`flex items-start gap-3 ${dim}`}>
      <span className="tile h-12 w-12" style={tint("wn")}><Layers size={22} /></span>
      <div className="min-w-0 flex-1"><h3 className="truncate text-base font-extrabold" title={g.name}>{g.name}</h3>
        <div className="mt-1.5 flex flex-wrap gap-1.5">{g.kind_label && <span className="badge b-in">{g.kind_label}</span>}{g.selection_mode === "manual" && <span className="badge b-mu" title={MODES.manual[1]}>انتخاب پنل با مشتری</span>}</div></div>
      {state === "bd" && <span className="badge b-bd">نمی‌فروشد</span>}
    </div>
    <div className={`grid grid-cols-3 gap-2 text-center ${dim}`}>
      <a className="rounded-xl bg-[var(--sf2)] p-2.5 hover:ring-1 hover:ring-[var(--ac)]" href={infraHref("panels", { group: g.id })} title="پنل‌های این بسته"><div className="num text-lg font-extrabold">{num(ms.length)}</div><div className="text-[11px] text-[var(--mu)]">پنل</div></a>
      <div className="rounded-xl bg-[var(--sf2)] p-2.5"><div className="num text-lg font-extrabold">{num(active)}</div><div className="text-[11px] text-[var(--mu)]">پکیج فعال{from ? ` · از ${from}` : ""}</div></div>
      <div className="rounded-xl bg-[var(--sf2)] p-2.5" title={stat.servers ? `${num(stat.live)} سرور آماده از ${num(stat.servers)}` : "سروری نیست"}><div className={`num text-lg font-extrabold ${stat.free ? "" : "text-[var(--wn)]"}`}>{num(stat.free)}</div><div className="text-[11px] text-[var(--mu)]">ظرفیت آزاد</div></div>
    </div>
    {g.sales_limit ? <div className={dim}><Quota sold={g.sold_count || 0} limit={g.sales_limit} /></div> : null}
    {issue && <Warn tone="bd">{issue}؛ تا رفع مشکل، پکیج‌های این بسته فروخته نمی‌شوند.</Warn>}
    <div className="mt-auto flex items-center justify-between gap-2 border-t border-[var(--ln)] pt-3">
      <Switches g={g} busy={busy} hasResellers={hasResellers} onToggle={onToggle} onToggleReseller={onToggleReseller} />
      <div className="flex items-center gap-1.5"><DeleteButton compact label={`حذف ${g.name}`} busy={busy} onClick={() => onDelete(g)} /><button className="btn btn-g" onClick={() => onEdit(g)}><Pencil size={13} />ویرایش</button></div>
    </div>
  </article>;
}

function GroupTable({ rows, panelById, idx, busy, hasResellers, onEdit, onToggle, onToggleReseller, onDelete }) {
  return <section className="card rise overflow-hidden"><div className="overflow-auto"><table className="tbl2 min-w-[760px]"><thead><tr>{["بسته", "پنل‌ها", "سرور آماده", "ظرفیت آزاد", "پکیج‌ها", "فروش / سقف", "فروشگاه اصلی", ...(hasResellers ? ["نمایندگان"] : []), ""].map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
    <tbody>{rows.map((g) => { const st = idx.groupStat(g), ps = idx.productsByGroup.get(g.id) || [], issue = groupIssue(g, st), u = st.capacity ? st.active / st.capacity : 0;
      return <tr key={g.id} className={g.is_enabled ? "" : "opacity-60"}>
        <td><div className="flex items-center gap-2.5"><span className="tile h-9 w-9" style={tint("wn")}><Layers size={16} /></span><div className="min-w-0"><div className="font-bold">{g.name}</div>{issue ? <div className="text-[11px] font-bold text-[var(--bd)]">{issue}</div> : g.kind_label && <div className="text-[11px] text-[var(--mu)]">{g.kind_label}</div>}</div></div></td>
        <td><div className="flex items-center gap-1">{(g.panels || []).slice(0, 5).map((m) => <Dot key={m.id} s={hs(panelById[m.panel_id])} />)}<span className="num mr-1 text-xs text-[var(--mu)]">{num((g.panels || []).length)}</span></div></td>
        <td className="num">{num(st.live)} <span className="text-[var(--mu)]">/ {num(st.servers)}</span></td>
        <td><div className="flex items-center gap-2"><span className="num w-12 font-bold">{num(st.free)}</span><div className="w-20"><Bar value={u} tone={capTone(u)} label="ظرفیت" /></div></div></td>
        <td className="num">{num(ps.filter((p) => p.is_active).length)}</td>
        <td className="num">{num(g.sold_count || 0)} <span className="text-[var(--mu)]">/ {g.sales_limit ? num(g.sales_limit) : "∞"}</span></td>
        <td><Switch checked={g.is_enabled} disabled={busy.has(g.id)} onChange={(v) => onToggle(g, v)} label={`فعال‌سازی ${g.name}`} /></td>
        {hasResellers && <td><Switch checked={g.is_enabled && g.reseller_enabled} disabled={busy.has(g.id) || !g.is_enabled} onChange={(v) => onToggleReseller(g, v)} label={`فعال‌سازی ${g.name} برای نمایندگان`} /></td>}
        <td><div className="flex items-center justify-end gap-2"><button className="btn btn-g" onClick={() => onEdit(g)}><Pencil size={13} />ویرایش</button><DeleteButton compact label={`حذف ${g.name}`} busy={busy.has(g.id)} onClick={() => onDelete(g)} /></div></td></tr>; })}</tbody></table></div></section>;
}

const EMPTY = { name: "", selection_mode: "automatic", naming_mode: "automatic", kind_label: "", sales_limit: "", is_enabled: true, reseller_enabled: true, panel_ids: [], member_labels: {} };
const fromGroup = (g) => ({ name: g.name, selection_mode: g.selection_mode, naming_mode: g.naming_mode, kind_label: g.kind_label || "", sales_limit: g.sales_limit ? String(g.sales_limit) : "", is_enabled: g.is_enabled, reseller_enabled: g.reseller_enabled, panel_ids: memberIds(g), member_labels: Object.fromEntries((g.panels || []).map((m) => [m.panel_id, m.label || ""])) });

/** The packages of a bundle. Every package is here by default; the switch hides it in THIS bundle only.
 *  Price fields: the store price in this bundle and, only when resellers exist, the cooperation price they pay.
 *  An empty field = the product's own price. These prices are the same for every reseller (no per-store prices). */
function BundlePackages({ group, products, hasResellers, call, toast, onChanged }) {
  const [rows, setRows] = useState(null), [draft, setDraft] = useState({}), [busy, setBusy] = useState(""), [saving, setSaving] = useState(false), [q, setQ] = useState("");
  const load = async () => { try { const r = await call(`${API}/${group.id}/products`); setRows(r.ok ? await r.json() : []); } catch { setRows([]); } };
  useEffect(() => { load(); }, [group.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const body = (row, patch) => ({ main_price: row.main_price, reseller_price: row.reseller_price, is_listed: row.is_listed, sort: row.sort, ...patch });
  const put = async (row, patch, quiet) => {
    const r = await call(`${API}/${group.id}/products/${row.product_id}`, { method: "PUT", body: JSON.stringify(body(row, patch)) });
    if (!r.ok) { if (!quiet) toast(await errText(r, "ذخیره پکیج ناموفق بود")); return false; }
    try { const out = await r.clone().json(); if (out?.stores_below_cost > 0) toast(`${out.stores_below_cost} فروشگاه نماینده قیمت فروششان از این قیمت نماینده کمتر است و این پکیج برایشان نمایش داده نمی‌شود تا قیمتشان را بالا ببرند.`); } catch { /* no warning */ }
    return true;
  };
  const toggleListed = async (row, v) => { setBusy(row.product_id); const ok = await put(row, { is_listed: v }); setBusy(""); if (ok) { await load(); onChanged?.(); } };
  const n2 = (v) => (v === "" || v == null ? null : Number(v));
  const dirtyRows = (rows || []).filter((r) => draft[r.product_id] && (draft[r.product_id].main !== undefined || draft[r.product_id].res !== undefined));
  const saveAll = async () => {
    setSaving(true); let bad = 0;
    for (const r of dirtyRows) { const d = draft[r.product_id]; if (!(await put(r, { main_price: d.main !== undefined ? n2(d.main) : r.main_price, reseller_price: d.res !== undefined ? n2(d.res) : r.reseller_price }, true))) bad++; }
    setSaving(false); toast(bad ? `${num(bad)} پکیج ذخیره نشد` : "قیمت‌ها ذخیره شد"); if (!bad) setDraft({}); await load(); onChanged?.();
  };
  const add = async (p) => { setBusy(p.id); const ok = await put({ product_id: p.id, main_price: null, reseller_price: null, sort: (rows || []).length }, { is_listed: true }); setBusy(""); if (ok) { await load(); onChanged?.(); } };
  const have = new Set((rows || []).map((x) => x.product_id));
  const missing = products.filter((p) => !p.is_test && !have.has(p.id) && `${p.name} ${p.code}`.toLowerCase().includes(q.trim().toLowerCase()));
  const field = (r, k, ph) => <NumInput aria-label={`${k === "main" ? "قیمت فروشگاه" : "قیمت نماینده"} ${r.name}`} value={draft[r.product_id]?.[k] ?? (k === "main" ? r.main_price : r.reseller_price) ?? ""} placeholder={String(ph)} onChange={(v) => setDraft((x) => ({ ...x, [r.product_id]: { ...x[r.product_id], [k]: v } }))} />;
  return <Section title="پکیج‌ها و قیمت" hint={hasResellers ? "همه‌ی پکیج‌ها به‌صورت پیش‌فرض در این بسته فعال‌اند. خالی‌گذاشتن قیمت یعنی قیمت خود محصول. قیمت نماینده برای همه‌ی نماینده‌ها یکسان است." : "همه‌ی پکیج‌ها به‌صورت پیش‌فرض در این بسته فعال‌اند. خالی‌گذاشتن قیمت یعنی قیمت خود محصول."}>
    {rows === null ? <div className="skel h-16 rounded-xl" /> : !rows.length ? <p className="rounded-xl bg-[var(--sf2)] p-3 text-xs text-[var(--wn)]">هنوز پکیجی در این بسته نیست؛ ابتدا از صفحه‌ی «محصولات» یک پکیج بسازید.</p>
      : <ul className="space-y-2">{rows.map((r) => { const d = draft[r.product_id] || {}; const dirty = d.main !== undefined || d.res !== undefined;
        return <li key={r.product_id} className={`rounded-xl border bg-[var(--sf2)] p-3 ${dirty ? "border-[var(--wn)]" : "border-[var(--ln)]"}`}>
          <div className="flex items-center gap-2">
            <div className={`min-w-0 flex-1 ${r.is_listed ? "" : "opacity-55"}`}><div className="truncate text-sm font-bold">{r.name}{!r.is_active && <span className="mr-1.5 badge b-mu">غیرفعال در محصولات</span>}{r.is_active && hasResellers && r.reseller_enabled === false && <span className="mr-1.5 badge b-mu">خاموش برای نمایندگان</span>}</div><div className="text-[11px] text-[var(--mu)]">قیمت محصول {num(r.base_main_price)}</div></div>
            <label className="flex cursor-pointer items-center gap-1.5 text-[11px] font-bold"><Switch checked={r.is_listed} disabled={busy === r.product_id || saving} onChange={(v) => toggleListed(r, v)} label={`فعال بودن ${r.name} در این بسته`} />{r.is_listed ? "فعال" : "پنهان"}</label>
          </div>
          {r.is_listed && <div className={`mt-2 grid gap-2 ${hasResellers ? "sm:grid-cols-2" : ""}`}>
            <Field label="قیمت فروشگاه در این بسته">{field(r, "main", r.base_main_price)}</Field>
            {hasResellers && <Field label="قیمت نماینده">{field(r, "res", r.base_reseller_price)}</Field>}
          </div>}
        </li>; })}</ul>}
    {dirtyRows.length > 0 && <div className="flex gap-2"><button type="button" className="btn !py-1.5 !text-xs" disabled={saving} onClick={saveAll}>{saving ? "در حال ذخیره…" : `ذخیره‌ی قیمت‌ها (${num(dirtyRows.length)})`}</button><button type="button" className="btn btn-g !py-1.5 !text-xs" disabled={saving} onClick={() => setDraft({})}>لغو تغییرات</button></div>}
    {rows !== null && products.some((p) => !p.is_test && !have.has(p.id)) && <details className="rounded-xl bg-[var(--sf2)] p-3 text-xs"><summary className="cursor-pointer font-bold text-[var(--mu)]">افزودن پکیج‌های جاافتاده</summary>
      <label className="relative mt-2 block"><Search size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[var(--mu)]" /><input aria-label="جستجوی پکیج" className="inp !pr-9" placeholder="جستجو…" value={q} onChange={(e) => setQ(e.target.value)} /></label>
      <div className="mt-2 max-h-40 space-y-1 overflow-y-auto">{missing.map((p) => <button key={p.id} type="button" disabled={!!busy} onClick={() => add(p)} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-right text-sm transition hover:bg-[var(--mb)]"><span className="min-w-0 flex-1 truncate font-bold">{p.name}</span><Plus size={14} className="text-[var(--ac)]" /></button>)}</div></details>}
  </Section>;
}

/** READ-ONLY: what each reseller store charges in this bundle. The admin cannot change these; resellers set them. */
function ResellerPrices({ group, stores, call }) {
  const [sid, setSid] = useState(stores[0]?.id || ""), [rows, setRows] = useState(null);
  useEffect(() => {
    if (!sid) return; setRows(null);
    call(`/api/v1/admin/stores/${sid}/reseller-prices`).then((r) => (r.ok ? r.json() : [])).then(setRows).catch(() => setRows([]));
  }, [sid]); // eslint-disable-line react-hooks/exhaustive-deps
  const list = (rows || []).map((r) => ({ r, b: (r.bundles || []).find((x) => x.bundle_id === group.id) })).filter((x) => x.b);
  const ST = { ok: ["ok", "قابل فروش"], unset: ["mu", "قیمت ندارد"], below_cost: ["bd", "زیر قیمت نماینده"] };
  return <Section title="قیمت فروش نمایندگان (فقط نمایش)" hint="این قیمت‌ها را خود نماینده تعیین می‌کند و ادمین نمی‌تواند تغییرشان دهد.">
    <select aria-label="نماینده" className="inp" value={sid} onChange={(e) => setSid(e.target.value)}>{stores.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
    {rows === null ? <div className="skel h-12 rounded-xl" /> : !list.length ? <p className="text-xs text-[var(--mu)]">پکیجی برای نمایش نیست.</p>
      : <div className="overflow-auto"><table className="tbl2 min-w-[420px]"><thead><tr>{["پکیج", "قیمت نماینده", "قیمت فروش او", "وضعیت"].map((h) => <th key={h}>{h}</th>)}</tr></thead>
        <tbody>{list.map(({ r, b }) => { const [t, l] = ST[b.state] || ST.unset; return <tr key={r.product_id}><td className="font-bold">{r.name}</td><td className="num">{num(b.cost)}</td><td className="num">{b.effective_price ? num(b.effective_price) : "—"}</td><td><span className={`badge b-${t}`}>{l}</span></td></tr>; })}</tbody></table></div>}
  </Section>;
}

function GroupDrawer({ group, panels, products, idx, hasResellers, resellerStores, call, toast, onChanged, onClose, onSubmit, onDelete }) {
  const edit = !!group;
  const [f, setF] = useState(() => (group ? fromGroup(group) : EMPTY));
  const base = useRef(JSON.stringify(f));
  const [tried, setTried] = useState(false), [busy, setBusy] = useState(false), [srv, setSrv] = useState(""), [pq, setPq] = useState("");
  const [adv, setAdv] = useState(() => !!group && (group.selection_mode !== "automatic" || group.naming_mode !== "automatic" || !!group.sales_limit || !!group.kind_label));
  const set = (k) => (v) => { setSrv(""); setF((x) => ({ ...x, [k]: v })); };
  const dirty = JSON.stringify(f) !== base.current;
  const byId = useMemo(() => Object.fromEntries(panels.map((p) => [p.id, p])), [panels]);
  const err = {};
  if (f.name.trim().length < 2) err.name = "نام بسته حداقل ۲ نویسه باشد";
  if (f.selection_mode === "manual" && !f.panel_ids.length) err.panels = "بسته دستی باید حداقل یک پنل داشته باشد";
  if (f.sales_limit !== "" && Number(f.sales_limit) < 1) err.limit = "سقف باید عدد مثبت باشد یا خالی بماند";
  const toggleP = (id) => set("panel_ids")(f.panel_ids.includes(id) ? f.panel_ids.filter((x) => x !== id) : [...f.panel_ids, id]);
  const setLabel = (id, v) => set("member_labels")({ ...f.member_labels, [id]: v });
  const move = (i, d) => { const a = [...f.panel_ids]; const j = i + d; if (j < 0 || j >= a.length) return; [a[i], a[j]] = [a[j], a[i]]; set("panel_ids")(a); };
  const avail = panels.filter((p) => !f.panel_ids.includes(p.id) && `${p.name}`.toLowerCase().includes(pq.trim().toLowerCase()));
  const submit = async () => {
    setTried(true); if (Object.keys(err).length) { if (err.panels) setAdv(true); return; }
    setBusy(true);
    const msg = await onSubmit({ ...f, name: f.name.trim(), sales_limit: f.sales_limit === "" ? null : Number(f.sales_limit) }, group);
    setBusy(false); if (msg) setSrv(msg);
  };
  const noServer = f.panel_ids.filter((id) => !idx.panelStat(id).n);
  return <Drawer title={edit ? `ویرایش «${group.name}»` : "افزودن بسته فروش VPN"} subtitle={edit ? `${num(group.sold_count || 0)} فروش ثبت‌شده` : "نام، پنل‌ها و قیمت پکیج‌ها"} icon={<span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint("in")}><Layers size={20} /></span>} dirty={dirty} busy={busy} onClose={onClose} error={srv}
    footer={<button className="btn !py-2 !text-sm" disabled={busy} onClick={submit}>{busy ? "در حال ذخیره…" : edit ? "ذخیره تغییرات" : "ساخت بسته"}</button>} danger={edit && <DeleteButton label="حذف بسته" busy={busy} onClick={() => onDelete(group)} />}>
    <Section title="اطلاعات">
      <Field label="نام بسته" error={tried && err.name}><input autoFocus className="inp" maxLength={120} value={f.name} placeholder="مثلاً: آلمان - پرسرعت" onChange={(e) => set("name")(e.target.value)} /></Field>
      <Toggle checked={f.is_enabled} onChange={set("is_enabled")} label="فعال در فروشگاه اصلی" hint={hasResellers ? "با غیرفعال‌کردن، برای نمایندگان هم نمایش داده نمی‌شود." : "بسته غیرفعال برای فروش جدید استفاده نمی‌شود."} />
      {hasResellers && <div className={f.is_enabled ? "" : "pointer-events-none opacity-50"}><Toggle checked={f.is_enabled && f.reseller_enabled} onChange={set("reseller_enabled")} label="فعال برای نمایندگان" hint={f.is_enabled ? "خاموش = فقط فروشگاه اصلی از این بسته می‌فروشد." : "ابتدا بسته را در فروشگاه اصلی فعال کنید."} /></div>}
    </Section>

    <Section title="پنل‌های بسته" hint={f.selection_mode === "manual" ? "ترتیب فهرست = ترتیب نمایش برای مشتری؛ نام نمایشی را شما می‌دهید و نام داخلی پنل به مشتری نشان داده نمی‌شود." : "اکانت جدید روی پنلی ساخته می‌شود که اکانت فعال کمتری دارد؛ اگر برابر بودند، بالاتر در فهرست اولویت دارد."}>
      {f.panel_ids.length > 0 && <ol className="space-y-1.5">{f.panel_ids.map((id, i) => { const p = byId[id]; return <li key={id} className="flex items-center gap-2 rounded-xl border border-[var(--ln)] bg-[var(--sf2)] px-3 py-2">
        <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-[var(--mb)] text-[11px] font-extrabold">{num(i + 1)}</span><Dot s={hs(p)} />
        <div className="min-w-0 flex-1"><div className="truncate text-sm font-bold">{p?.name || "پنل حذف‌شده"}</div><div className="text-[11px] text-[var(--mu)]">{p && !p.is_enabled ? "غیرفعال · " : ""}<span className={idx.panelStat(id).n ? "" : "text-[var(--wn)]"}>{num(idx.panelStat(id).n)} سرور</span></div></div>
        {f.selection_mode === "manual" && <input aria-label="نام نمایشی برای مشتری" className="inp !w-36 !py-1 !text-xs" maxLength={80} placeholder="نام نمایشی (مثلاً آلمان)" value={f.member_labels[id] || ""} onChange={(e) => setLabel(id, e.target.value)} />}
        <button type="button" className="btn btn-g !px-1.5" aria-label="بالاتر" disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp size={13} /></button>
        <button type="button" className="btn btn-g !px-1.5" aria-label="پایین‌تر" disabled={i === f.panel_ids.length - 1} onClick={() => move(i, 1)}><ArrowDown size={13} /></button>
        <button type="button" className="btn btn-g btn-d !px-1.5" aria-label="حذف از بسته" onClick={() => toggleP(id)}><X size={13} /></button></li>; })}</ol>}
      {tried && err.panels && <p className="text-[11px] text-[var(--bd)]">{err.panels}</p>}
      <div>
        <label className="relative block"><Search size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[var(--mu)]" /><input aria-label="جستجوی پنل" className="inp !pr-9" placeholder="افزودن پنل… (جستجو)" value={pq} onChange={(e) => setPq(e.target.value)} /></label>
        <div className="mt-2 max-h-48 space-y-1 overflow-y-auto">{!panels.length ? <p className="p-4 text-center text-xs text-[var(--mu)]">هنوز پنلی ساخته نشده؛ ابتدا از «پنل‌ها و سرورها» یک پنل اضافه کنید.</p>
          : !avail.length ? <p className="p-3 text-center text-xs text-[var(--mu)]">{pq ? "پنلی پیدا نشد" : "همه‌ی پنل‌ها به بسته اضافه شده‌اند"}</p>
          : avail.map((p) => <button key={p.id} type="button" onClick={() => toggleP(p.id)} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-right text-sm transition hover:bg-[var(--mb)]"><Dot s={hs(p)} /><span className="min-w-0 flex-1 truncate font-bold">{p.name}</span><span className="text-[11px] text-[var(--mu)]">{!p.is_enabled ? "غیرفعال · " : ""}{num(idx.panelStat(p.id).n)} سرور</span><Plus size={14} className="text-[var(--ac)]" /></button>)}</div>
      </div>
      {noServer.length > 0 && <Warn>برخی پنل‌های بسته هنوز سرور ندارند؛ تا سرور اضافه نشود اکانتی روی آن‌ها ساخته نمی‌شود. <a className="underline" href={infraHref("panels", { id: noServer[0], add: "server" })}>افزودن سرور</a></Warn>}
      {edit && <p className="text-[11px] leading-5 text-[var(--mu)]">حذف یا تغییر ترتیب پنل‌ها، آمار فروش پنل‌های باقی‌مانده را حفظ می‌کند.</p>}
    </Section>

    {edit ? <BundlePackages group={group} products={products} hasResellers={hasResellers} call={call} toast={toast} onChanged={onChanged} />
      : <p className="rounded-xl bg-[var(--sf2)] px-4 py-3 text-xs leading-6 text-[var(--mu)]">همه‌ی پکیج‌ها به‌صورت پیش‌فرض در بسته‌ی جدید فعال‌اند؛ بعد از ساخت، قیمت هر پکیج را همین‌جا تنظیم کنید.</p>}

    {edit && resellerStores.length > 0 && <ResellerPrices group={group} stores={resellerStores} call={call} />}

    <section>
      <button type="button" className="flex items-center gap-1.5 text-xs font-bold text-[var(--mu)]" aria-expanded={adv} onClick={() => setAdv(!adv)}><ChevronDown size={14} className={adv ? "" : "-rotate-90"} />تنظیمات بیشتر{f.selection_mode === "manual" && <span className="badge b-in">انتخاب دستی</span>}</button>
      {adv && <div className="mt-3 space-y-4">
        <Section title="نمایش و سقف">
          <Field label="برچسب بسته" hint="اختیاری. متنی که کنار نام بسته به مشتری نشان داده می‌شود (مثلاً مستقیم)."><input className="inp" maxLength={40} value={f.kind_label} placeholder="مثلاً: مستقیم" onChange={(e) => set("kind_label")(e.target.value)} /></Field>
          <Field label="سقف فروش بسته" error={tried && err.limit} hint="خالی = نامحدود؛ با رسیدن به سقف، فروش از این بسته متوقف می‌شود"><NumInput value={f.sales_limit} onChange={set("sales_limit")} placeholder="نامحدود" suffix="اکانت" /></Field>
        </Section>
        <Section title="نحوه‌ی انتخاب پنل">
          <Segmented label="نحوه‌ی انتخاب پنل" value={f.selection_mode} onChange={set("selection_mode")} options={Object.entries(MODES).map(([k, [t]]) => [k, t])} />
          <p className="text-[11px] leading-5 text-[var(--mu)]">{MODES[f.selection_mode][1]}</p>
        </Section>
        <Section title="نام کاربری اکانت‌ها">
          <Field hint={f.naming_mode === "custom" ? "مشتری هنگام خرید نام کاربری را وارد می‌کند (اجباری، حداقل ۳ نویسه)" : "نام کاربری به‌صورت خودکار ساخته می‌شود"}><Segmented label="نام‌گذاری" value={f.naming_mode} onChange={set("naming_mode")} options={[["automatic", "خودکار"], ["custom", "دلخواه مشتری"]]} /></Field>
        </Section>
      </div>}
    </section>
  </Drawer>;
}

export default function BundlesView({ api, toast }) {
  const infra = useInfra(api); const { call, idx } = infra;
  const groups = infra.groups, panelsQ = infra.panels, storesQ = useRows(call, "/api/v1/admin/stores");
  const hasResellers = (storesQ.rows || []).some((x) => x.kind === "reseller"); // no resellers yet = no cooperation switches or prices
  const params = useHashParams();
  const [q, setQ] = useState(params.get("q") || ""), [filter, setFilter] = useState("all"), [drawer, setDrawer] = useState(null), [busy, setBusy] = useState(new Set()), [sort, setSort] = useState("attention"), [layout, setLayout] = useState("cards");
  const PAGE_SIZE = 20;
  const [page, setPage] = useState(0);
  useEffect(() => { setPage(0); }, [filter, q]); // eslint-disable-line react-hooks/exhaustive-deps
  const alive = useAlive();
  useEffect(() => { setQ(params.get("q") || ""); if (params.get("add") === "1") { setDrawer("add"); clearParam("add"); } }, [params]);
  const rows = groups.rows, panels = panelsQ.rows || [], products = infra.products.rows || [];
  const panelById = useMemo(() => Object.fromEntries(panels.map((p) => [p.id, p])), [panels]);
  const attention = (g) => !!groupIssue(g, idx.groupStat(g));
  const counts = useMemo(() => { const c = { all: 0, on: 0, off: 0, bad: 0 }; (rows || []).forEach((g) => { c.all++; g.is_enabled ? c.on++ : c.off++; if (attention(g)) c.bad++; }); return c; }, [rows, idx]); // eslint-disable-line react-hooks/exhaustive-deps
  const filtered = useMemo(() => (rows || []).filter((g) => (filter === "all" || (filter === "on" ? g.is_enabled : filter === "off" ? !g.is_enabled : attention(g))) && g.name.toLowerCase().includes(q.trim().toLowerCase())), [rows, filter, q, idx]); // eslint-disable-line react-hooks/exhaustive-deps
  const sorted = useMemo(() => {
    const by = { attention: (a, b) => Number(!!groupIssue(b, idx.groupStat(b))) - Number(!!groupIssue(a, idx.groupStat(a))) || Number(b.is_enabled) - Number(a.is_enabled) || a.name.localeCompare(b.name, "fa"),
      name: (a, b) => a.name.localeCompare(b.name, "fa"), sold: (a, b) => (b.sold_count || 0) - (a.sold_count || 0), free: (a, b) => idx.groupStat(b).free - idx.groupStat(a).free };
    return [...filtered].sort(by[sort]);
  }, [filtered, sort, idx]); // eslint-disable-line react-hooks/exhaustive-deps
  const shown = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const editing = drawer && drawer !== "add" ? (rows || []).find((g) => g.id === drawer) : null;

  const save = async (f, group) => {
    const labels = Object.fromEntries(f.panel_ids.map((id) => [id, (f.member_labels[id] || "").trim()]));
    const same = group && JSON.stringify(memberIds(group)) === JSON.stringify(f.panel_ids);
    const body = { name: f.name, selection_mode: f.selection_mode, naming_mode: f.naming_mode, kind_label: f.kind_label, is_enabled: f.is_enabled, reseller_enabled: f.reseller_enabled, sales_limit: f.sales_limit, member_labels: labels, ...(group ? (same ? {} : { panel_ids: f.panel_ids }) : { panel_ids: f.panel_ids }) };
    const r = await call(group ? `${API}/${group.id}` : API, { method: group ? "PATCH" : "POST", body: JSON.stringify(body) });
    if (!r.ok) return errText(r, group ? "ذخیره تغییرات ناموفق بود" : "ساخت بسته ناموفق بود");
    if (group) { setDrawer(null); toast("تغییرات بسته ذخیره شد"); }
    else { const created = await r.json(); setDrawer(created.id); toast("بسته ساخته شد؛ حالا پکیج‌هایش را اضافه کنید"); }
    await infra.reload(); return "";
  };
  const remove = async (g) => {
    setBusy((s) => new Set(s).add(g.id));
    const ok = await removeEntity(call, `${API}/${g.id}`, { toast, title: "حذف بسته فروش", done: `«${g.name}» حذف شد`,
      message: `«${g.name}» برای همیشه حذف شود؟ فقط خودِ بسته و اتصالش به فروشگاه‌ها پاک می‌شود؛ پنل‌های عضو دست‌نخورده می‌مانند. اگر بستهِ پیش‌فرضِ یک محصول باشد یا سفارشی از آن ساخته شده باشد، حذف انجام نمی‌شود.` });
    if (alive.current) setBusy((s) => { const n = new Set(s); n.delete(g.id); return n; });
    if (ok) { setDrawer(null); await infra.reload(); }
  };
  const toggleReseller = async (g, next) => {
    setBusy((s) => new Set(s).add(g.id));
    let ok = false; try { ok = (await call(`${API}/${g.id}`, { method: "PATCH", body: JSON.stringify({ reseller_enabled: next }) })).ok; } catch { /* network */ }
    if (alive.current) setBusy((s) => { const n = new Set(s); n.delete(g.id); return n; });
    toast(ok ? (next ? `«${g.name}» برای نمایندگان فعال شد` : `«${g.name}» برای نمایندگان غیرفعال شد`) : "تغییر وضعیت ناموفق بود"); if (ok) await infra.reload();
  };
  const toggle = async (g, next) => {
    if (!next && !(await confirmDialog(`«${g.name}» غیرفعال شود؟ تا فعال‌سازی مجدد برای فروش جدید استفاده نمی‌شود${hasResellers ? " و برای نمایندگان هم غیرفعال می‌شود" : ""}.`, { title: "غیرفعال‌سازی بسته", danger: true, ok: "غیرفعال‌سازی" }))) return;
    setBusy((s) => new Set(s).add(g.id));
    let ok = false; try { ok = (await call(`${API}/${g.id}`, { method: "PATCH", body: JSON.stringify({ is_enabled: next }) })).ok; } catch { /* network */ }
    if (alive.current) setBusy((s) => { const n = new Set(s); n.delete(g.id); return n; });
    toast(ok ? (next ? `«${g.name}» فعال شد` : `«${g.name}» غیرفعال شد`) : "تغییر وضعیت ناموفق بود"); if (ok) await infra.reload();
  };

  return <div className="space-y-5">
    <InfraChain current="groups" infra={infra} />
    <KpiBar cols={4}>
      <Stat label="همه بسته‌ها" value={counts.all} tone="in" Icon={Layers} active={filter === "all"} onClick={() => setFilter("all")} />
      <Stat label="فعال" value={counts.on} tone="ok" Icon={CheckCircle2} active={filter === "on"} onClick={() => setFilter(filter === "on" ? "all" : "on")} />
      <Stat label="غیرفعال" value={counts.off} tone="mu" Icon={Layers} active={filter === "off"} onClick={() => setFilter(filter === "off" ? "all" : "off")} />
      <Stat label="نمی‌تواند بفروشد" value={counts.bad} tone={counts.bad ? "bd" : "mu"} Icon={ShieldAlert} active={filter === "bad"} onClick={() => setFilter(filter === "bad" ? "all" : "bad")} />
    </KpiBar>
    <div className="tool">
      <SearchBox label="جستجوی بسته" placeholder="جستجوی نام بسته…" value={q} onChange={setQ} />
      <SortSelect value={sort} onChange={setSort} options={[["attention", "مشکل‌دارها اول"], ["name", "نام"], ["sold", "بیشترین فروش"], ["free", "بیشترین ظرفیت آزاد"]]} />
      <ViewToggle value={layout} onChange={setLayout} options={[["cards", "کارتی"], ["table", "جدولی"]]} />
      <button className="btn mr-auto" onClick={() => setDrawer("add")}><Plus size={16} />افزودن بسته</button>
    </div>
    {groups.failed && <ErrorBar onRetry={groups.load}><ShieldAlert size={16} />دریافت بسته‌ها ناموفق بود.</ErrorBar>}
    {rows === null ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="card skel h-72" />)}</div>
      : !shown.length ? <Empty Icon={Layers} title={counts.all ? "بسته‌ای با این فیلتر پیدا نشد" : "هنوز بسته‌ای ساخته نشده"} text={counts.all ? "جستجو یا فیلتر را تغییر دهید." : "بدون بسته هیچ اکانتی فروخته نمی‌شود. اولین بسته را بسازید، پنل‌ها و پکیج‌هایش را اضافه کنید."}>
        {!counts.all && <button className="btn" onClick={() => setDrawer("add")}><Plus size={16} />ساخت اولین بسته</button>}</Empty>
      : <>{layout === "table"
        ? <GroupTable rows={shown} panelById={panelById} idx={idx} busy={busy} hasResellers={hasResellers} onEdit={(x) => setDrawer(x.id)} onToggle={toggle} onToggleReseller={toggleReseller} onDelete={remove} />
        : <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{shown.map((g) => <GroupCard key={g.id} g={g} stat={idx.groupStat(g)} products={idx.productsByGroup.get(g.id) || []} busy={busy.has(g.id)} hasResellers={hasResellers} onEdit={(x) => setDrawer(x.id)} onToggle={toggle} onToggleReseller={toggleReseller} onDelete={remove} />)}</div>}
        <Paginator page={page} setPage={setPage} total={filtered.length} pageSize={PAGE_SIZE} /></>}
    {drawer && (drawer === "add" || editing) && <GroupDrawer key={drawer} group={editing} panels={panels} products={products} idx={idx} hasResellers={hasResellers} resellerStores={(storesQ.rows || []).filter((x) => x.kind === "reseller")} call={call} toast={toast} onChanged={infra.reload} onClose={() => setDrawer(null)} onSubmit={save} onDelete={remove} />}
  </div>;
}
