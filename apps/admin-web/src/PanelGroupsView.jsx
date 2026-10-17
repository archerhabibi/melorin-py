import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, confirmDialog } from "./ui.jsx";
import { AlertTriangle, ArrowDown, ArrowLeft, ArrowUp, Boxes, CheckCircle2, ChevronDown, Layers, PanelTop, Pencil, Plus, Search, ShieldAlert, Tag, X } from "lucide-react";
import { Bar, Drawer, Empty, ErrorBar, Field, KpiBar, NumInput, Paginator, Ring, SearchBox, Section, Segmented, SortSelect, Stat, Switch, Toggle, ViewToggle, DeleteButton, capTone, errText, num, removeEntity, tint, useAlive } from "./kit.jsx";
import { Dot, InfraChain, Rel, RelChip, Warn, clearParam, health as hs, infraHref, memberIds, useHashParams, useInfra } from "./infra.jsx";

// A panel group is a SALES POOL (بسته فروش): panels + connection kind + the packages it sells, each with
// its own price. Customers pick a pool, so the pool is the only way an account gets sold; there is no
// pool-less route. Selection / naming / reseller policy are advanced options: most pools never change them.
const API = "/api/v1/admin/panel-groups";
const PRODUCTS = "/api/v1/admin/products";
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

function GroupCard({ g, panelById, stat, products, busy, onEdit, onToggle, onDelete }) {
  const ms = g.panels || [], dim = g.is_enabled ? "" : "opacity-55", issue = groupIssue(g, stat);
  const u = stat.capacity ? stat.active / stat.capacity : 0, t = capTone(u);
  const state = !g.is_enabled ? "off" : issue ? "bd" : "ok";
  const from = fromPrice(products);
  return <article className={`card card-i rise stripe flex flex-col gap-4 p-5 ${state === "off" ? "off" : ""}`} style={{ "--stripe": state === "ok" ? "var(--ok)" : state === "bd" ? "var(--bd)" : "var(--ln)" }}>
    <div className={`flex items-start gap-3 ${dim}`}>
      <span className="tile h-12 w-12" style={tint("wn")}><Layers size={22} /></span>
      <div className="min-w-0 flex-1"><h3 className="truncate text-base font-extrabold" title={g.name}>{g.name}</h3>
        <div className="mt-1.5 flex flex-wrap gap-1.5">{g.kind_label && <span className="badge b-in">{g.kind_label}</span>}{g.selection_mode === "manual" && <span className="badge b-mu" title={MODES.manual[1]}>انتخاب پنل با مشتری</span>}{g.naming_mode === "custom" && <span className="badge b-mu">نام کاربری دلخواه</span>}{!g.reseller_enabled && <span className="badge b-mu">بدون نمایندگی</span>}</div></div>
      {state === "bd" ? <span className="badge b-bd">نمی‌فروشد</span> : <Badge s={g.is_enabled ? "active" : "disabled"} />}
    </div>

    <div className={`flow ${dim}`} aria-label="مسیر: پنل‌ها به بسته به پکیج‌ها">
      <a className="fn hover:ring-1 hover:ring-[var(--ac)]" href={infraHref("panels", { group: g.id })} title="پنل‌های این بسته">
        <div className="fv num">{num(ms.length)}</div><div className="fl">پنل</div>
        <div className="mt-1.5 flex justify-center gap-1">{ms.slice(0, 5).map((m) => <Dot key={m.id} s={hs(panelById[m.panel_id])} />)}{ms.length > 5 && <span className="text-[10px] text-[var(--mu)]">+{num(ms.length - 5)}</span>}</div></a>
      <span className="fa" aria-hidden><ArrowLeft size={14} /></span>
      <div className="fn relative" title={stat.servers ? `${num(stat.live)} سرور آماده از ${num(stat.servers)}` : "سروری نیست"}>
        <div className="flex justify-center"><Ring value={u} size={44} stroke={5} tone={stat.servers ? t : "mu"} label={`ظرفیت پر: ${Math.round(u * 100)} درصد`}><b className="num text-[11px]">{num(stat.free)}</b></Ring></div><div className="fl">ظرفیت آزاد</div></div>
      <span className="fa" aria-hidden><ArrowLeft size={14} /></span>
      <a className="fn hover:ring-1 hover:ring-[var(--ac)]" href={infraHref("products")} title="پکیج‌های این بسته">
        <div className="fv num">{num(products.length)}</div><div className="fl">پکیج</div>{from && <div className="mt-1.5 truncate text-[10px] font-bold text-[var(--mu)]">از {from}</div>}</a>
    </div>

    <div className={dim}><Quota sold={g.sold_count || 0} limit={g.sales_limit} /></div>

    <div className={`space-y-2 ${dim}`}>
      <Rel label="پنل‌ها" empty={<span className="flex items-center gap-1.5 text-[var(--wn)]"><AlertTriangle size={12} />هنوز پنلی به این بسته اضافه نشده</span>}>
        {ms.length ? <>{ms.slice(0, 3).map((m) => { const p = panelById[m.panel_id]; return <span key={m.id} className={m.is_enabled ? "" : "line-through"}><RelChip to="panels" params={{ id: m.panel_id }} tone="in" dim={!m.is_enabled}><span className="inline-flex items-center gap-1.5"><Dot s={hs(p)} />{p?.name || "پنل حذف‌شده"}</span></RelChip></span>; })}{ms.length > 3 && <span className="text-[11px] text-[var(--mu)]">+{num(ms.length - 3)}</span>}</> : null}</Rel>
      <Rel label="پکیج‌ها" empty={<span className="flex items-center gap-1.5 text-[var(--wn)]"><AlertTriangle size={12} />هنوز پکیجی در این بسته نیست</span>}>
        {products.length ? <>{products.slice(0, 3).map((p) => <RelChip key={p.id} to="products" params={{ q: p.code }} tone="mu" Icon={Boxes} dim={!p.is_active}>{p.name}</RelChip>)}{products.length > 3 && <span className="text-[11px] text-[var(--mu)]">+{num(products.length - 3)}</span>}</> : null}</Rel>
      {issue && <Warn tone="bd">{issue}؛ تا رفع مشکل، محصولات این بسته فروخته نمی‌شوند.</Warn>}
    </div>

    <div className="mt-auto flex items-center justify-between gap-2 border-t border-[var(--ln)] pt-3">
      <label className="flex cursor-pointer items-center gap-2 text-xs font-bold"><Switch checked={g.is_enabled} disabled={busy} onChange={(v) => onToggle(g, v)} label={`فعال‌سازی ${g.name}`} />{g.is_enabled ? "فعال" : "غیرفعال"}</label>
      <div className="flex items-center gap-1.5"><DeleteButton compact label={`حذف ${g.name}`} busy={busy} onClick={() => onDelete(g)} /><button className="btn btn-g" onClick={() => onEdit(g)}><Pencil size={13} />ویرایش</button></div>
    </div>
  </article>;
}

function GroupTable({ rows, panelById, idx, busy, onEdit, onToggle, onDelete }) {
  return <section className="card rise overflow-hidden"><div className="overflow-auto"><table className="tbl2 min-w-[900px]"><thead><tr>{["بسته", "پنل‌ها", "سرور آماده", "ظرفیت آزاد", "پکیج‌ها", "فروش / سقف", "وضعیت", ""].map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
    <tbody>{rows.map((g) => { const st = idx.groupStat(g), ps = idx.productsByGroup.get(g.id) || [], issue = groupIssue(g, st), u = st.capacity ? st.active / st.capacity : 0;
      return <tr key={g.id} className={g.is_enabled ? "" : "opacity-60"}>
        <td><div className="flex items-center gap-2.5"><span className="tile h-9 w-9" style={tint("wn")}><Layers size={16} /></span><div className="min-w-0"><div className="font-bold">{g.name}</div>{g.kind_label && <div className="text-[11px] text-[var(--mu)]">{g.kind_label}</div>}</div></div></td>
        <td><div className="flex items-center gap-1">{(g.panels || []).slice(0, 5).map((m) => <Dot key={m.id} s={hs(panelById[m.panel_id])} />)}<span className="num mr-1 text-xs text-[var(--mu)]">{num((g.panels || []).length)}</span></div></td>
        <td className="num">{num(st.live)} <span className="text-[var(--mu)]">/ {num(st.servers)}</span></td>
        <td><div className="flex items-center gap-2"><span className="num w-12 font-bold">{num(st.free)}</span><div className="w-20"><Bar value={u} tone={capTone(u)} label="ظرفیت" /></div></div></td>
        <td className="num">{num(ps.length)}</td>
        <td className="num">{num(g.sold_count || 0)} <span className="text-[var(--mu)]">/ {g.sales_limit ? num(g.sales_limit) : "∞"}</span></td>
        <td>{issue ? <span className="badge b-bd" title={issue}>{issue}</span> : <Badge s={g.is_enabled ? "active" : "disabled"} />}</td>
        <td><div className="flex items-center justify-end gap-2"><Switch checked={g.is_enabled} disabled={busy.has(g.id)} onChange={(v) => onToggle(g, v)} label={`فعال‌سازی ${g.name}`} /><button className="btn btn-g" onClick={() => onEdit(g)}><Pencil size={13} />ویرایش</button><DeleteButton compact label={`حذف ${g.name}`} busy={busy.has(g.id)} onClick={() => onDelete(g)} /></div></td></tr>; })}</tbody></table></div></section>;
}

const EMPTY = { name: "", selection_mode: "automatic", naming_mode: "automatic", kind_label: "", sales_limit: "", is_enabled: true, reseller_enabled: true, panel_ids: [], member_labels: {} };
const fromGroup = (g) => ({ name: g.name, selection_mode: g.selection_mode, naming_mode: g.naming_mode, kind_label: g.kind_label || "", sales_limit: g.sales_limit ? String(g.sales_limit) : "", is_enabled: g.is_enabled, reseller_enabled: g.reseller_enabled, panel_ids: memberIds(g), member_labels: Object.fromEntries((g.panels || []).map((m) => [m.panel_id, m.label || ""])) });

/** The packages a pool sells. Saved row by row (no drawer "save" needed): empty price = the product's own price. */
function PoolPackages({ group, products, pooledIds, call, toast, onChanged }) {
  const [rows, setRows] = useState(null), [draft, setDraft] = useState({}), [busy, setBusy] = useState(""), [q, setQ] = useState("");
  const load = async () => { try { const r = await call(`${API}/${group.id}/products`); setRows(r.ok ? await r.json() : []); } catch { setRows([]); } };
  useEffect(() => { load(); }, [group.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const put = async (row, patch) => {
    setBusy(row.product_id);
    const body = { main_price: row.main_price, reseller_price: row.reseller_price, is_listed: row.is_listed, sort: row.sort, ...patch };
    const r = await call(`${API}/${group.id}/products/${row.product_id}`, { method: "PUT", body: JSON.stringify(body) });
    setBusy(""); if (!r.ok) { toast(await errText(r, "ذخیره پکیج ناموفق بود")); return; }
    try { const out = await r.clone().json(); if (out?.stores_below_cost > 0) toast(`${out.stores_below_cost} فروشگاه نماینده قیمت فروششان از این قیمت همکاری کمتر است و این پکیج برایشان نمایش داده نمی‌شود تا قیمتشان را بالا ببرند.`); } catch { /* no warning */ }
    setDraft((d) => { const n = { ...d }; delete n[row.product_id]; return n; }); await load(); onChanged?.();
  };
  const add = async (p) => put({ product_id: p.id, main_price: null, reseller_price: null, is_listed: true, sort: (rows || []).length }, {});
  const remove = async (row) => {
    setBusy(row.product_id);
    const r = await call(`${API}/${group.id}/products/${row.product_id}`, { method: "DELETE" });
    setBusy(""); if (!r.ok) { toast(await errText(r, "برداشتن پکیج ناموفق بود")); return; } await load(); onChanged?.();
  };
  const num2 = (v) => (v === "" || v == null ? null : Number(v));
  const have = new Set((rows || []).map((x) => x.product_id));
  const availProd = products.filter((p) => !p.is_test && !have.has(p.id) && `${p.name} ${p.code}`.toLowerCase().includes(q.trim().toLowerCase()));
  return <Section title="پکیج‌های این بسته" hint="مشتری فقط پکیج‌های همین بسته را با قیمت همین بسته می‌بیند. قیمت خالی یعنی قیمت خود محصول؛ می‌توانید یک پکیج را در چند بسته با قیمت‌های متفاوت بفروشید.">
    {rows === null ? <div className="skel h-16 rounded-xl" /> : !rows.length ? <p className="rounded-xl bg-[var(--sf2)] p-3 text-xs text-[var(--wn)]">هنوز پکیجی در این بسته نیست؛ تا پکیج اضافه نشود مشتری چیزی در آن نمی‌بیند.</p>
      : <ul className="space-y-2">{rows.map((r) => { const d = draft[r.product_id] || {}; const dirty = d.main !== undefined || d.res !== undefined; return <li key={r.product_id} className={`space-y-2 rounded-xl border border-[var(--ln)] bg-[var(--sf2)] p-3 ${r.is_listed ? "" : "opacity-60"}`}>
        <div className="flex items-center gap-2"><div className="min-w-0 flex-1"><div className="truncate text-sm font-bold">{r.name}{!r.is_active && <span className="mr-1.5 text-[11px] font-normal text-[var(--mu)]">(غیرفعال)</span>}{r.is_default && <span className="mr-1.5 badge b-in">پیش‌فرض محصول</span>}</div><div className="text-[11px] text-[var(--mu)]">{r.code} · قیمت خود محصول {num(r.base_main_price)} / نماینده {num(r.base_reseller_price)}</div></div>
          <label className="flex cursor-pointer items-center gap-1.5 text-[11px] font-bold"><Switch checked={r.is_listed} disabled={busy === r.product_id} onChange={(v) => put(r, { is_listed: v })} label={`نمایش ${r.name}`} />نمایش</label>
          <DeleteButton compact label={`برداشتن ${r.name}`} busy={busy === r.product_id} onClick={() => remove(r)} /></div>
        <div className="grid gap-2 sm:grid-cols-2">
          <Field label="قیمت در این بسته"><NumInput value={d.main ?? (r.main_price ?? "")} onChange={(v) => setDraft((x) => ({ ...x, [r.product_id]: { ...x[r.product_id], main: v } }))} placeholder={String(r.base_main_price)} /></Field>
          <Field label="قیمت نماینده در این بسته"><NumInput value={d.res ?? (r.reseller_price ?? "")} onChange={(v) => setDraft((x) => ({ ...x, [r.product_id]: { ...x[r.product_id], res: v } }))} placeholder={String(r.base_reseller_price)} /></Field>
        </div>
        {dirty && <button type="button" className="btn !py-1.5 !text-xs" disabled={busy === r.product_id} onClick={() => put(r, { main_price: d.main !== undefined ? num2(d.main) : r.main_price, reseller_price: d.res !== undefined ? num2(d.res) : r.reseller_price })}>ثبت قیمت</button>}
      </li>; })}</ul>}
    <label className="relative block"><Search size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[var(--mu)]" /><input aria-label="جستجوی پکیج" className="inp !pr-9" placeholder="افزودن پکیج… (جستجو)" value={q} onChange={(e) => setQ(e.target.value)} /></label>
    <div className="max-h-48 space-y-1 overflow-y-auto">{!availProd.length ? <p className="p-3 text-center text-xs text-[var(--mu)]">{q ? "پکیجی پیدا نشد" : "همه‌ی پکیج‌ها در این بسته هستند"}</p>
      : availProd.map((p) => <button key={p.id} type="button" disabled={!!busy} onClick={() => add(p)} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-right text-sm transition hover:bg-[var(--mb)]"><span className="min-w-0 flex-1 truncate font-bold">{p.name}{!p.is_active && <span className="mr-1.5 text-[11px] font-normal text-[var(--mu)]">(غیرفعال)</span>}</span><span className="text-[11px] text-[var(--mu)]">{pooledIds.has(p.id) ? `${num(p.main_price)}` : "بدون بسته"}</span><Plus size={14} className="text-[var(--ac)]" /></button>)}</div>
  </Section>;
}

function GroupDrawer({ group, panels, products, idx, pooledIds, call, toast, onChanged, onClose, onSubmit, onDelete }) {
  const edit = !!group;
  const [f, setF] = useState(() => (group ? fromGroup(group) : EMPTY));
  const base = useRef(JSON.stringify(f));
  const [tried, setTried] = useState(false), [busy, setBusy] = useState(false), [srv, setSrv] = useState(""), [pq, setPq] = useState("");
  const [adv, setAdv] = useState(() => !!group && (group.selection_mode !== "automatic" || group.naming_mode !== "automatic" || !group.reseller_enabled));
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
  return <Drawer title={edit ? `ویرایش «${group.name}»` : "افزودن بسته فروش VPN"} subtitle={edit ? `${num(group.sold_count || 0)} فروش ثبت‌شده` : "نوع اتصال + پنل‌ها + پکیج‌هایی که مشتری می‌خرد"} icon={<span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint("in")}><Layers size={20} /></span>} dirty={dirty} busy={busy} onClose={onClose} error={srv}
    footer={<button className="btn !py-2 !text-sm" disabled={busy} onClick={submit}>{busy ? "در حال ذخیره…" : edit ? "ذخیره تغییرات" : "ساخت بسته"}</button>} danger={edit && <DeleteButton label="حذف بسته" busy={busy} onClick={() => onDelete(group)} />}>
    <Section title={edit ? "اطلاعات" : "۱ · اطلاعات"}>
      <Field label="نام بسته" error={tried && err.name}><input autoFocus className="inp" maxLength={120} value={f.name} placeholder="مثلاً: آلمان - پرسرعت" onChange={(e) => set("name")(e.target.value)} /></Field>
      <Field label="برچسب بسته" hint="اختیاری. هر متن دلخواهی که می‌خواهید مشتری کنار نام بسته ببیند (مثلاً نوع اتصال یا کشور)."><input className="inp" maxLength={40} value={f.kind_label} placeholder="مثلاً: مستقیم" onChange={(e) => set("kind_label")(e.target.value)} /></Field>
      <Field label="سقف فروش بسته" error={tried && err.limit} hint="خالی = نامحدود؛ با رسیدن به سقف، فروش از این بسته متوقف می‌شود"><NumInput value={f.sales_limit} onChange={set("sales_limit")} placeholder="نامحدود" suffix="اکانت" /></Field>
      <Toggle checked={f.is_enabled} onChange={set("is_enabled")} label="بسته فعال باشد" hint="بسته غیرفعال برای فروش جدید استفاده نمی‌شود و محصولاتش تا فعال‌سازی مجدد خرید ندارند." />
    </Section>

    <Section title={edit ? "پنل‌های بسته" : "۲ · پنل‌های بسته"} hint={f.selection_mode === "manual" ? "ترتیب فهرست = ترتیب نمایش برای مشتری؛ نام نمایشی را شما می‌دهید و نام داخلی پنل به مشتری نشان داده نمی‌شود." : "اکانت جدید روی پنلی ساخته می‌شود که اکانت فعال کمتری دارد؛ اگر برابر بودند، بالاتر در فهرست اولویت دارد."}>
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

    {edit ? <PoolPackages group={group} products={products} pooledIds={pooledIds} call={call} toast={toast} onChanged={onChanged} />
      : <p className="rounded-xl bg-[var(--sf2)] px-4 py-3 text-xs leading-6 text-[var(--mu)]">بعد از ساخت بسته، همین‌جا پکیج‌های قابل فروش و قیمت هر کدام را اضافه کنید.</p>}

    <section>
      <button type="button" className="flex items-center gap-1.5 text-xs font-bold text-[var(--mu)]" aria-expanded={adv} onClick={() => setAdv(!adv)}><ChevronDown size={14} className={adv ? "" : "-rotate-90"} />تنظیمات پیشرفته{f.selection_mode === "manual" && <span className="badge b-in">انتخاب دستی</span>}</button>
      {adv && <div className="mt-3 space-y-4">
        <Section title="نحوه‌ی انتخاب پنل">
          <Segmented label="نحوه‌ی انتخاب پنل" value={f.selection_mode} onChange={set("selection_mode")} options={Object.entries(MODES).map(([k, [t]]) => [k, t])} />
          <p className="text-[11px] leading-5 text-[var(--mu)]">{MODES[f.selection_mode][1]}</p>
        </Section>
        <Section title="نام‌گذاری و دسترسی">
          <Field label="نام کاربری اکانت‌ها" hint={f.naming_mode === "custom" ? "مشتری هنگام خرید نام کاربری را وارد می‌کند (اجباری، حداقل ۳ نویسه)" : "نام کاربری به‌صورت خودکار ساخته می‌شود"}><Segmented label="نام‌گذاری" value={f.naming_mode} onChange={set("naming_mode")} options={[["automatic", "خودکار"], ["custom", "دلخواه مشتری"]]} /></Field>
          <Toggle checked={f.reseller_enabled} onChange={set("reseller_enabled")} label="در دسترس نمایندگان" hint="خاموش = فقط فروشگاه اصلی از این بسته استفاده می‌کند." />
        </Section>
      </div>}
    </section>
  </Drawer>;
}

export default function PanelGroupsView({ api, toast }) {
  const infra = useInfra(api); const { call, idx } = infra;
  const groups = infra.groups, panelsQ = infra.panels;
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

  const pooledIds = useMemo(() => new Set((rows || []).flatMap((g) => g.product_ids || [])), [rows]);
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
  const toggle = async (g, next) => {
    if (!next && !(await confirmDialog(`«${g.name}» غیرفعال شود؟ تا فعال‌سازی مجدد برای فروش جدید استفاده نمی‌شود${(idx.productsByGroup.get(g.id) || []).length ? " و محصولات آن قابل خرید نیستند" : ""}.`, { title: "غیرفعال‌سازی بسته", danger: true, ok: "غیرفعال‌سازی" }))) return;
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
    <p className="flex items-start gap-3 rounded-xl border border-[var(--hair)] bg-[var(--sf)] px-4 py-3 text-xs leading-6 text-[var(--mu)]"><span className="tile mt-0.5 h-7 w-7 shrink-0" style={tint("in")}><Layers size={14} /></span><span>هر فروش از یک بسته انجام می‌شود: مشتری بسته را انتخاب می‌کند و پکیج‌های همان بسته را با قیمت همان بسته می‌بیند. <b className="text-[var(--tx)]">مسیر بدون بسته وجود ندارد</b>؛ پنلی که عضو هیچ بسته‌ای نباشد و پکیجی که در هیچ بسته‌ای نباشد چیزی نمی‌فروشد.</span></p>
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
        ? <GroupTable rows={shown} panelById={panelById} idx={idx} busy={busy} onEdit={(x) => setDrawer(x.id)} onToggle={toggle} onDelete={remove} />
        : <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{shown.map((g) => <GroupCard key={g.id} g={g} panelById={panelById} stat={idx.groupStat(g)} products={idx.productsByGroup.get(g.id) || []} busy={busy.has(g.id)} onEdit={(x) => setDrawer(x.id)} onToggle={toggle} onDelete={remove} />)}</div>}
        <Paginator page={page} setPage={setPage} total={filtered.length} pageSize={PAGE_SIZE} /></>}
    {drawer && (drawer === "add" || editing) && <GroupDrawer key={drawer} group={editing} panels={panels} products={products} idx={idx} pooledIds={pooledIds} call={call} toast={toast} onChanged={infra.reload} onClose={() => setDrawer(null)} onSubmit={save} onDelete={remove} />}
  </div>;
}
