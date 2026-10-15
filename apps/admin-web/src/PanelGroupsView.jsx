import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, confirmDialog } from "./ui.jsx";
import { AlertTriangle, ArrowDown, ArrowUp, Boxes, CheckCircle2, ChevronDown, Layers, Pencil, Plus, Search, ShieldAlert, X } from "lucide-react";
import { Drawer, Field, NumInput, Paginator, Section, Segmented, Stat, Switch, Toggle, capTone, errText, num, tint, useAlive } from "./kit.jsx";
import { Dot, InfraChain, Rel, RelChip, Warn, clearParam, health as hs, infraHref, memberIds, useHashParams, useInfra } from "./infra.jsx";

// A panel group is a POOL of panels with a sales quota. Which products are sold from the pool is
// decided here too (a product's "default group" is edited from this screen or from the product).
// Selection / naming / reseller policy are advanced options: most groups never change them.
const API = "/api/v1/admin/panel-groups";
const PRODUCTS = "/api/v1/admin/products";
const MODES = {
  automatic: ["خودکار", "سیستم پنلی را انتخاب می‌کند که اکانت فعال کمتری دارد؛ ربات و سایت فقط همین حالت را پشتیبانی می‌کنند."],
  manual: ["دستی (فقط API)", "خریدار یا نماینده هنگام سفارش پنل را مشخص می‌کند. ربات و سایت این حالت را ندارند و گروه دستی نمی‌تواند پیش‌فرض محصول باشد."],
};

function Quota({ sold, limit }) {
  const pct = limit ? Math.min(100, Math.round((sold / limit) * 100)) : 0;
  const full = limit && sold >= limit, warn = limit && pct >= 80;
  return <div>
    <div className="mb-1.5 flex items-center justify-between text-[11px]"><span className="text-[var(--mu)]">فروش</span><b className={full ? "text-[var(--bd)]" : ""}>{num(sold)} / {limit ? num(limit) : "نامحدود"}{full ? " · پر شده" : ""}</b></div>
    <div className="h-1.5 overflow-hidden rounded-full bg-[var(--mb)]" role="progressbar" aria-valuenow={limit ? pct : undefined} aria-label="سهمیه فروش"><div className="h-full rounded-full transition-all" style={{ width: limit ? `${Math.max(pct, 3)}%` : "100%", background: limit ? (full ? "var(--bd)" : warn ? "var(--wn)" : "var(--ok)") : "var(--mb)", opacity: limit ? 1 : .6 }} /></div>
  </div>;
}

/** Why an enabled group cannot sell right now, or "" when it can. */
const groupIssue = (g, stat) => (!g.is_enabled ? "" : !(g.panels || []).length ? "پنلی ندارد" : !stat.live ? "هیچ سرور آماده‌ای ندارد" : "");

function GroupCard({ g, panelById, stat, products, busy, onEdit, onToggle }) {
  const ms = g.panels || [], dim = g.is_enabled ? "" : "opacity-55", issue = groupIssue(g, stat);
  const u = stat.capacity ? stat.active / stat.capacity : 0, t = capTone(u);
  return <article className="card rise flex flex-col gap-4 p-4">
    <div className={`flex items-start gap-3 ${dim}`}>
      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint("wn")}><Layers size={20} /></span>
      <div className="min-w-0 flex-1"><h3 className="truncate font-extrabold" title={g.name}>{g.name}</h3>
        <div className="mt-1 flex flex-wrap gap-1.5">{g.selection_mode === "manual" && <span className="badge b-in" title={MODES.manual[1]}>انتخاب دستی · API</span>}{g.naming_mode === "custom" && <span className="badge b-mu">نام کاربری دلخواه</span>}{!g.reseller_enabled && <span className="badge b-mu">بدون نمایندگی</span>}</div></div>
      <Badge s={g.is_enabled ? "active" : "disabled"} />
    </div>
    <div className={dim}><Quota sold={g.sold_count || 0} limit={g.sales_limit} /></div>
    <div className={`space-y-2 rounded-xl bg-[var(--sf2)] p-3 ${dim}`}>
      <Rel label="پنل‌ها" empty={<span className="flex items-center gap-1.5 text-[var(--wn)]"><AlertTriangle size={12} />هنوز پنلی به این گروه اضافه نشده</span>}>
        {ms.length ? <>{ms.slice(0, 4).map((m) => { const p = panelById[m.panel_id]; return <span key={m.id} className={m.is_enabled ? "" : "line-through"}><RelChip to="panels" params={{ id: m.panel_id }} tone="in" dim={!m.is_enabled}><span className="inline-flex items-center gap-1.5"><Dot s={hs(p)} />{p?.name || "پنل حذف‌شده"}</span></RelChip></span>; })}{ms.length > 4 && <span className="text-[11px] text-[var(--mu)]">+{num(ms.length - 4)}</span>}</> : null}</Rel>
      <Rel label="ظرفیت" empty="روی پنل‌های گروه سروری نیست">
        {stat.servers ? <a href={infraHref("panels", { group: g.id })} className="flex min-w-0 flex-1 items-center gap-3 hover:text-[var(--ac)]"><span className="shrink-0 font-bold">{num(stat.live)} سرور آماده از {num(stat.servers)}</span>
          <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--mb)]"><span className="block h-full rounded-full" style={{ width: `${Math.min(100, u * 100)}%`, background: `var(--${t})` }} /></span>
          <span className="shrink-0 text-[11px] text-[var(--mu)]">{num(stat.free)} آزاد</span></a> : null}</Rel>
      <Rel label="محصولات" empty="هنوز محصولی از این گروه فروخته نمی‌شود">
        {products.length ? <>{products.slice(0, 3).map((p) => <RelChip key={p.id} to="products" params={{ q: p.code }} tone="mu" Icon={Boxes} dim={!p.is_active}>{p.name}</RelChip>)}{products.length > 3 && <span className="text-[11px] text-[var(--mu)]">+{num(products.length - 3)}</span>}</> : null}</Rel>
      {issue && <Warn tone="bd">{issue}؛ تا رفع مشکل، محصولات این گروه فروخته نمی‌شوند.</Warn>}
    </div>
    <div className="mt-auto flex items-center justify-between gap-2 border-t border-[var(--ln)] pt-3">
      <label className="flex cursor-pointer items-center gap-2 text-xs font-bold"><Switch checked={g.is_enabled} disabled={busy} onChange={(v) => onToggle(g, v)} label={`فعال‌سازی ${g.name}`} />{g.is_enabled ? "فعال" : "غیرفعال"}</label>
      <button className="btn btn-g" onClick={() => onEdit(g)}><Pencil size={13} />ویرایش</button>
    </div>
  </article>;
}

const EMPTY = { name: "", selection_mode: "automatic", naming_mode: "automatic", sales_limit: "", is_enabled: true, reseller_enabled: true, panel_ids: [], product_ids: [] };
const fromGroup = (g, used) => ({ name: g.name, selection_mode: g.selection_mode, naming_mode: g.naming_mode, sales_limit: g.sales_limit ? String(g.sales_limit) : "", is_enabled: g.is_enabled, reseller_enabled: g.reseller_enabled, panel_ids: memberIds(g), product_ids: used.map((p) => p.id) });

function GroupDrawer({ group, panels, products, idx, onClose, onSubmit }) {
  const edit = !!group;
  const used = useMemo(() => (group ? idx.productsByGroup.get(group.id) || [] : []), [group, idx]);
  const [f, setF] = useState(() => (group ? fromGroup(group, used) : EMPTY));
  const base = useRef(JSON.stringify(f));
  const [tried, setTried] = useState(false), [busy, setBusy] = useState(false), [srv, setSrv] = useState(""), [pq, setPq] = useState(""), [prq, setPrq] = useState("");
  const [adv, setAdv] = useState(() => !!group && (group.selection_mode !== "automatic" || group.naming_mode !== "automatic" || !group.reseller_enabled));
  const set = (k) => (v) => { setSrv(""); setF((x) => ({ ...x, [k]: v })); };
  const dirty = JSON.stringify(f) !== base.current;
  const byId = useMemo(() => Object.fromEntries(panels.map((p) => [p.id, p])), [panels]);
  const prodById = useMemo(() => Object.fromEntries(products.map((p) => [p.id, p])), [products]);
  const err = {};
  if (f.name.trim().length < 2) err.name = "نام گروه حداقل ۲ نویسه باشد";
  if (f.selection_mode === "manual" && !f.panel_ids.length) err.panels = "گروه دستی باید حداقل یک پنل داشته باشد";
  if (f.sales_limit !== "" && Number(f.sales_limit) < 1) err.limit = "سقف باید عدد مثبت باشد یا خالی بماند";
  if (f.product_ids.length && f.selection_mode === "manual") err.products = "گروه دستی نمی‌تواند پیش‌فرض محصول باشد؛ محصولات را بردارید یا حالت را خودکار کنید";
  if (f.product_ids.length && !f.is_enabled) err.products = "محصول فقط به گروه فعال وصل می‌شود؛ گروه را فعال کنید یا محصولات را بردارید";
  const toggleP = (id) => set("panel_ids")(f.panel_ids.includes(id) ? f.panel_ids.filter((x) => x !== id) : [...f.panel_ids, id]);
  const toggleProd = (id) => set("product_ids")(f.product_ids.includes(id) ? f.product_ids.filter((x) => x !== id) : [...f.product_ids, id]);
  const move = (i, d) => { const a = [...f.panel_ids]; const j = i + d; if (j < 0 || j >= a.length) return; [a[i], a[j]] = [a[j], a[i]]; set("panel_ids")(a); };
  const avail = panels.filter((p) => !f.panel_ids.includes(p.id) && `${p.name}`.toLowerCase().includes(pq.trim().toLowerCase()));
  const availProd = products.filter((p) => !f.product_ids.includes(p.id) && `${p.name} ${p.code}`.toLowerCase().includes(prq.trim().toLowerCase()));
  const submit = async () => {
    setTried(true); if (Object.keys(err).length) { if (err.panels) setAdv(true); return; }
    setBusy(true);
    const was = used.map((p) => p.id);
    const msg = await onSubmit({ ...f, name: f.name.trim(), sales_limit: f.sales_limit === "" ? null : Number(f.sales_limit) }, group, { add: f.product_ids.filter((x) => !was.includes(x)), del: was.filter((x) => !f.product_ids.includes(x)) });
    setBusy(false); if (msg) setSrv(msg);
  };
  const noServer = f.panel_ids.filter((id) => !idx.panelStat(id).n);
  return <Drawer title={edit ? `ویرایش «${group.name}»` : "افزودن گروه پنل VPN"} subtitle={edit ? `${num(group.sold_count || 0)} فروش ثبت‌شده` : "چند پنل که محصولات از بینشان اکانت می‌سازند"} icon={<span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint("in")}><Layers size={20} /></span>} dirty={dirty} busy={busy} onClose={onClose} error={srv}
    footer={<button className="btn !py-2 !text-sm" disabled={busy} onClick={submit}>{busy ? "در حال ذخیره…" : edit ? "ذخیره تغییرات" : "ساخت گروه"}</button>}>
    <Section title={edit ? "اطلاعات" : "۱ · اطلاعات"}>
      <Field label="نام گروه" error={tried && err.name}><input autoFocus className="inp" maxLength={120} value={f.name} placeholder="مثلاً: آلمان - پرسرعت" onChange={(e) => set("name")(e.target.value)} /></Field>
      <Field label="سقف فروش گروه" error={tried && err.limit} hint="خالی = نامحدود؛ با رسیدن به سقف، فروش از این گروه متوقف می‌شود"><NumInput value={f.sales_limit} onChange={set("sales_limit")} placeholder="نامحدود" suffix="اکانت" /></Field>
      <Toggle checked={f.is_enabled} onChange={set("is_enabled")} label="گروه فعال باشد" hint="گروه غیرفعال برای فروش جدید استفاده نمی‌شود و محصولاتش تا فعال‌سازی مجدد خرید ندارند." />
    </Section>

    <Section title={edit ? "پنل‌های گروه" : "۲ · پنل‌های گروه"} hint={f.selection_mode === "manual" ? "ترتیب فهرست = ترتیب نمایش و اولویت." : "اکانت جدید روی پنلی ساخته می‌شود که اکانت فعال کمتری دارد؛ اگر برابر بودند، بالاتر در فهرست اولویت دارد."}>
      {f.panel_ids.length > 0 && <ol className="space-y-1.5">{f.panel_ids.map((id, i) => { const p = byId[id]; return <li key={id} className="flex items-center gap-2 rounded-xl border border-[var(--ln)] bg-[var(--sf2)] px-3 py-2">
        <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-[var(--mb)] text-[11px] font-extrabold">{num(i + 1)}</span><Dot s={hs(p)} />
        <div className="min-w-0 flex-1"><div className="truncate text-sm font-bold">{p?.name || "پنل حذف‌شده"}</div><div className="text-[11px] text-[var(--mu)]">{p && !p.is_enabled ? "غیرفعال · " : ""}<span className={idx.panelStat(id).n ? "" : "text-[var(--wn)]"}>{num(idx.panelStat(id).n)} سرور</span></div></div>
        <button type="button" className="btn btn-g !px-1.5" aria-label="بالاتر" disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp size={13} /></button>
        <button type="button" className="btn btn-g !px-1.5" aria-label="پایین‌تر" disabled={i === f.panel_ids.length - 1} onClick={() => move(i, 1)}><ArrowDown size={13} /></button>
        <button type="button" className="btn btn-g btn-d !px-1.5" aria-label="حذف از گروه" onClick={() => toggleP(id)}><X size={13} /></button></li>; })}</ol>}
      {tried && err.panels && <p className="text-[11px] text-[var(--bd)]">{err.panels}</p>}
      <div>
        <label className="relative block"><Search size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[var(--mu)]" /><input aria-label="جستجوی پنل" className="inp !pr-9" placeholder="افزودن پنل… (جستجو)" value={pq} onChange={(e) => setPq(e.target.value)} /></label>
        <div className="mt-2 max-h-48 space-y-1 overflow-y-auto">{!panels.length ? <p className="p-4 text-center text-xs text-[var(--mu)]">هنوز پنلی ساخته نشده؛ ابتدا از «پنل‌ها و سرورها» یک پنل اضافه کنید.</p>
          : !avail.length ? <p className="p-3 text-center text-xs text-[var(--mu)]">{pq ? "پنلی پیدا نشد" : "همه‌ی پنل‌ها به گروه اضافه شده‌اند"}</p>
          : avail.map((p) => <button key={p.id} type="button" onClick={() => toggleP(p.id)} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-right text-sm transition hover:bg-[var(--mb)]"><Dot s={hs(p)} /><span className="min-w-0 flex-1 truncate font-bold">{p.name}</span><span className="text-[11px] text-[var(--mu)]">{!p.is_enabled ? "غیرفعال · " : ""}{num(idx.panelStat(p.id).n)} سرور</span><Plus size={14} className="text-[var(--ac)]" /></button>)}</div>
      </div>
      {noServer.length > 0 && <Warn>برخی پنل‌های گروه هنوز سرور ندارند؛ تا سرور اضافه نشود اکانتی روی آن‌ها ساخته نمی‌شود. <a className="underline" href={infraHref("panels", { id: noServer[0], add: "server" })}>افزودن سرور</a></Warn>}
      {edit && <p className="text-[11px] leading-5 text-[var(--mu)]">حذف یا تغییر ترتیب پنل‌ها، آمار فروش پنل‌های باقی‌مانده را حفظ می‌کند.</p>}
    </Section>

    <Section title={edit ? "محصولات این گروه" : "۳ · محصولات این گروه (اختیاری)"} hint="محصولاتی که اکانتشان از این گروه ساخته می‌شود. هر محصول فقط یک گروه دارد؛ اگر محصولی را از گروه دیگر انتخاب کنید به این گروه منتقل می‌شود.">
      {f.product_ids.length > 0 && <div className="flex flex-wrap gap-1.5">{f.product_ids.map((id) => { const p = prodById[id]; return <span key={id} className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] font-bold" style={tint("mu")}><Boxes size={12} />{p?.name || "محصول حذف‌شده"}<button type="button" aria-label={`برداشتن ${p?.name || ""}`} onClick={() => toggleProd(id)}><X size={12} /></button></span>; })}</div>}
      {tried && err.products && <p className="text-[11px] text-[var(--bd)]">{err.products}</p>}
      <label className="relative block"><Search size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[var(--mu)]" /><input aria-label="جستجوی محصول" className="inp !pr-9" placeholder="افزودن محصول… (جستجو)" value={prq} onChange={(e) => setPrq(e.target.value)} /></label>
      <div className="max-h-48 space-y-1 overflow-y-auto">{!products.length ? <p className="p-4 text-center text-xs text-[var(--mu)]">هنوز محصولی تعریف نشده است.</p>
        : !availProd.length ? <p className="p-3 text-center text-xs text-[var(--mu)]">{prq ? "محصولی پیدا نشد" : "همه‌ی محصولات انتخاب شده‌اند"}</p>
        : availProd.map((p) => { const other = p.default_panel_group_id && p.default_panel_group_id !== group?.id ? idx.groupById.get(p.default_panel_group_id) : null; return <button key={p.id} type="button" onClick={() => toggleProd(p.id)} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-right text-sm transition hover:bg-[var(--mb)]"><span className="min-w-0 flex-1 truncate font-bold">{p.name}{!p.is_active && <span className="mr-1.5 text-[11px] font-normal text-[var(--mu)]">(غیرفعال)</span>}</span><span className="text-[11px] text-[var(--mu)]">{other ? `اکنون در «${other.name}»` : "بدون گروه"}</span><Plus size={14} className="text-[var(--ac)]" /></button>; })}</div>
    </Section>

    <section>
      <button type="button" className="flex items-center gap-1.5 text-xs font-bold text-[var(--mu)]" aria-expanded={adv} onClick={() => setAdv(!adv)}><ChevronDown size={14} className={adv ? "" : "-rotate-90"} />تنظیمات پیشرفته{f.selection_mode === "manual" && <span className="badge b-in">انتخاب دستی</span>}</button>
      {adv && <div className="mt-3 space-y-4">
        <Section title="نحوه‌ی انتخاب پنل">
          <Segmented label="نحوه‌ی انتخاب پنل" value={f.selection_mode} onChange={set("selection_mode")} options={Object.entries(MODES).map(([k, [t]]) => [k, t])} />
          <p className="text-[11px] leading-5 text-[var(--mu)]">{MODES[f.selection_mode][1]}</p>
        </Section>
        <Section title="نام‌گذاری و دسترسی">
          <Field label="نام کاربری اکانت‌ها" hint={f.naming_mode === "custom" ? "مشتری هنگام خرید نام کاربری انتخاب می‌کند" : "نام کاربری به‌صورت خودکار ساخته می‌شود"}><Segmented label="نام‌گذاری" value={f.naming_mode} onChange={set("naming_mode")} options={[["automatic", "خودکار"], ["custom", "دلخواه مشتری"]]} /></Field>
          <Toggle checked={f.reseller_enabled} onChange={set("reseller_enabled")} label="در دسترس نمایندگان" hint="خاموش = فقط فروشگاه اصلی از این گروه استفاده می‌کند." />
        </Section>
      </div>}
    </section>
  </Drawer>;
}

export default function PanelGroupsView({ api, toast }) {
  const infra = useInfra(api); const { call, idx } = infra;
  const groups = infra.groups, panelsQ = infra.panels;
  const params = useHashParams();
  const [q, setQ] = useState(params.get("q") || ""), [filter, setFilter] = useState("all"), [drawer, setDrawer] = useState(null), [busy, setBusy] = useState(new Set());
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
  const shown = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const editing = drawer && drawer !== "add" ? (rows || []).find((g) => g.id === drawer) : null;

  const setProductGroup = async (id, groupId) => (await call(`${PRODUCTS}/${id}`, { method: "PATCH", body: JSON.stringify({ default_panel_group_id: groupId }) }));
  // One save = group, then its products. A product leaves a group BEFORE the group turns "manual"
  // (the core refuses that while products still use it) and joins AFTER the group is saved.
  const save = async (f, group, { add, del }) => {
    const { product_ids, ...fields } = f;
    const manualNow = group && group.selection_mode !== "manual" && f.selection_mode === "manual";
    const notes = [];
    const detach = async () => { for (const id of del) { const r = await setProductGroup(id, null); if (!r.ok) notes.push(await errText(r, "برداشتن محصول ناموفق بود")); } };
    if (manualNow) await detach();
    const same = group && JSON.stringify(memberIds(group)) === JSON.stringify(f.panel_ids);
    const body = group ? { name: fields.name, selection_mode: fields.selection_mode, naming_mode: fields.naming_mode, is_enabled: fields.is_enabled, reseller_enabled: fields.reseller_enabled, sales_limit: fields.sales_limit, ...(same ? {} : { panel_ids: fields.panel_ids }) } : fields;
    const r = await call(group ? `${API}/${group.id}` : API, { method: group ? "PATCH" : "POST", body: JSON.stringify(body) });
    if (!r.ok) return errText(r, group ? "ذخیره تغییرات ناموفق بود" : "ساخت گروه ناموفق بود");
    const gid = group ? group.id : (await r.json())?.id;
    if (!manualNow) await detach();
    for (const id of add) { const pr = await setProductGroup(id, gid); if (!pr.ok) notes.push(await errText(pr, "اتصال محصول ناموفق بود")); }
    setDrawer(null); toast(notes.length ? `گروه ذخیره شد، اما: ${notes[0]}` : group ? "تغییرات گروه ذخیره شد" : "گروه پنل VPN ساخته شد"); await infra.reload(); return "";
  };
  const toggle = async (g, next) => {
    if (!next && !(await confirmDialog(`«${g.name}» غیرفعال شود؟ تا فعال‌سازی مجدد برای فروش جدید استفاده نمی‌شود${(idx.productsByGroup.get(g.id) || []).length ? " و محصولات آن قابل خرید نیستند" : ""}.`, { title: "غیرفعال‌سازی گروه", danger: true, ok: "غیرفعال‌سازی" }))) return;
    setBusy((s) => new Set(s).add(g.id));
    let ok = false; try { ok = (await call(`${API}/${g.id}`, { method: "PATCH", body: JSON.stringify({ is_enabled: next }) })).ok; } catch { /* network */ }
    if (alive.current) setBusy((s) => { const n = new Set(s); n.delete(g.id); return n; });
    toast(ok ? (next ? `«${g.name}» فعال شد` : `«${g.name}» غیرفعال شد`) : "تغییر وضعیت ناموفق بود"); if (ok) await infra.reload();
  };

  return <div className="space-y-5">
    <InfraChain current="groups" infra={infra} />
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Stat label="همه گروه‌ها" value={counts.all} tone="in" Icon={Layers} active={filter === "all"} onClick={() => setFilter("all")} />
      <Stat label="فعال" value={counts.on} tone="ok" Icon={CheckCircle2} active={filter === "on"} onClick={() => setFilter(filter === "on" ? "all" : "on")} />
      <Stat label="غیرفعال" value={counts.off} tone="mu" Icon={Layers} active={filter === "off"} onClick={() => setFilter(filter === "off" ? "all" : "off")} />
      <Stat label="نمی‌تواند بفروشد" value={counts.bad} tone={counts.bad ? "bd" : "mu"} Icon={ShieldAlert} active={filter === "bad"} onClick={() => setFilter(filter === "bad" ? "all" : "bad")} />
    </div>
    <p className="rounded-xl bg-[var(--sf2)] px-4 py-3 text-xs leading-6 text-[var(--mu)]">گروه <b className="text-[var(--tx)]">اختیاری</b> است: محصولی که گروه ندارد روی هر پنل سالمی ساخته می‌شود. گروه را وقتی بسازید که بخواهید فروش یک محصول را به چند پنل مشخص (مثلاً «آلمان») محدود کنید یا برایش سقف فروش بگذارید.</p>
    <div className="flex flex-wrap items-center gap-2">
      <label className="relative min-w-[12rem] flex-1 sm:max-w-xs"><Search size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[var(--mu)]" /><input aria-label="جستجوی گروه" className="inp !pr-9" placeholder="جستجوی نام گروه…" value={q} onChange={(e) => setQ(e.target.value)} /></label>
      <button className="btn mr-auto" onClick={() => setDrawer("add")}><Plus size={16} />افزودن گروه</button>
    </div>
    {groups.failed && <p role="alert" className="flex items-center gap-2 rounded-xl bg-[var(--bdb)] p-3 text-sm text-[var(--bd)]"><ShieldAlert size={16} />دریافت گروه‌ها ناموفق بود. <button className="font-extrabold underline" onClick={groups.load}>تلاش مجدد</button></p>}
    {rows === null ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="card skel h-52" />)}</div>
      : !shown.length ? <div className="card grid place-items-center gap-3 p-14 text-center"><span className="grid h-14 w-14 place-items-center rounded-2xl bg-[var(--mb)] text-[var(--mu)]"><Layers size={26} /></span>
        <h3 className="font-extrabold">{counts.all ? "گروهی با این فیلتر پیدا نشد" : "هنوز گروه پنلی ساخته نشده"}</h3>
        <p className="max-w-sm text-sm leading-7 text-[var(--mu)]">{counts.all ? "جستجو یا فیلتر را تغییر دهید." : "گروه لازم نیست؛ فقط اگر می‌خواهید فروش را بین چند پنل مشخص تقسیم یا محدود کنید بسازید."}</p>
        {!counts.all && <button className="btn" onClick={() => setDrawer("add")}><Plus size={16} />ساخت اولین گروه</button>}</div>
      : <><div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{shown.map((g) => <GroupCard key={g.id} g={g} panelById={panelById} stat={idx.groupStat(g)} products={idx.productsByGroup.get(g.id) || []} busy={busy.has(g.id)} onEdit={(x) => setDrawer(x.id)} onToggle={toggle} />)}</div><Paginator page={page} setPage={setPage} total={filtered.length} pageSize={PAGE_SIZE} /></>}
    {drawer && (drawer === "add" || editing) && <GroupDrawer key={drawer} group={editing} panels={panels} products={products} idx={idx} onClose={() => setDrawer(null)} onSubmit={save} />}
  </div>;
}
