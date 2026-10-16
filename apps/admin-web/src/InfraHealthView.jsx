import { useState, useCallback } from "react";
import { ShieldCheck, AlertTriangle, RefreshCw, Loader, CheckCircle, XCircle } from "lucide-react";
import { useInfra } from "./infra.jsx";

// ---- Issue section helpers ----
function IssueSection({ title, items, color = "orange", children }) {
  if (!items.length) return null;
  const cls = {
    orange: "border-orange-200 bg-orange-50 text-orange-800",
    red:    "border-red-200 bg-red-50 text-red-700",
    blue:   "border-blue-200 bg-blue-50 text-blue-800",
    gray:   "border-[var(--ln)] bg-[var(--mb)] text-[var(--mu)]",
  }[color] || "";
  return (
    <section className={`rounded-xl border p-4 ${cls}`}>
      <h3 className="mb-2 font-bold">{title} ({items.length})</h3>
      <ul className="space-y-1 text-sm">{items.map((it, i) => <li key={i}>{children(it)}</li>)}</ul>
    </section>
  );
}

function Badge({ ok }) {
  return ok
    ? <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-bold text-green-700"><CheckCircle size={11} />سالم</span>
    : <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-bold text-red-700"><XCircle size={11} />ناسالم</span>;
}

// ---- Main component ----
export default function InfraHealthView({ api, toast }) {
  const infra = useInfra(api); // loads all (health needs full picture)
  const { panels, servers, groups, products, idx, reload } = infra;

  const [checking, setChecking] = useState(new Set());
  const [results, setResults]   = useState({}); // panelId -> { healthy, checkedAt }

  const checkPanel = useCallback(async (panelId) => {
    setChecking((p) => new Set(p).add(panelId));
    try {
      const r = await infra.call(`/api/v1/admin/panels/${panelId}/health`, { method: "POST" });
      const d = r.ok ? await r.json() : null;
      setResults((prev) => ({ ...prev, [panelId]: { healthy: !!d?.healthy, checkedAt: new Date() } }));
      if (r.ok) await reload();
    } catch {
      toast("بررسی ناموفق بود");
    }
    setChecking((p) => { const n = new Set(p); n.delete(panelId); return n; });
  }, [infra, reload]);

  const checkAllPanels = async () => {
    const ids = (panels.rows || []).map((p) => p.id);
    await Promise.all(ids.map(checkPanel));
    toast(`بررسی ${ids.length} پنل انجام شد`);
  };

  // ---- Derive issues ----
  const pRows = panels.rows  || [];
  const sRows = servers.rows || [];
  const gRows = groups.rows  || [];
  const prRows = products.rows || [];

  const disabledPanels  = pRows.filter((p) => !p.is_enabled);
  const noServerPanels  = pRows.filter((p) => !sRows.some((s) => s.panel_id === p.id));
  const disabledServers = sRows.filter((s) => !s.is_enabled);
  const orphanServers   = sRows.filter((s) => !pRows.some((p) => p.id === s.panel_id));
  const emptyGroups     = gRows.filter((g) => !(g.panels || []).length);
  // A product is "without server" when the allocation core finds no live server for it
  // (product → group → panels → server, incl. a server's optional product allow-list).
  const unusedProducts  = prRows.filter((pr) => pr.is_active && !idx.reach(pr).ok);

  const totalIssues = [
    disabledPanels, noServerPanels, disabledServers,
    orphanServers, emptyGroups, unusedProducts,
  ].reduce((a, b) => a + b.length, 0);

  const loading = infra.loading;

  return (
    <div dir="rtl" className="mx-auto max-w-3xl space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <ShieldCheck size={24} className="text-green-600" />
          <h1 className="text-xl font-extrabold">داشبورد سلامت زیرساخت</h1>
        </div>
        <div className="flex gap-2">
          <button className="btn btn-g" onClick={reload} disabled={loading}>
            {loading ? <Loader size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            به‌روزرسانی
          </button>
          <button className="btn" onClick={checkAllPanels} disabled={loading || checking.size > 0}>
            {checking.size > 0
              ? <><Loader size={14} className="animate-spin" />در حال بررسی…</>
              : <>✔ بررسی همه پنل‌ها</>}
          </button>
        </div>
      </div>

      {/* Summary banner */}
      {!loading && (
        <div className={`flex items-center gap-3 rounded-2xl p-4 ${
          totalIssues === 0
            ? "bg-green-50 border border-green-200"
            : "bg-orange-50 border border-orange-200"
        }`}>
          {totalIssues === 0
            ? <><CheckCircle size={20} className="text-green-600" /><p className="font-bold text-green-800">هیچ مشکلی شناسایی نشد — زیرساخت سالم است ✓</p></>
            : <><AlertTriangle size={20} className="text-orange-600" /><p className="font-bold text-orange-800">{totalIssues} مشکل شناسایی شد</p></>}
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center gap-2 py-12 text-[var(--mu)]">
          <Loader size={20} className="animate-spin" />در حال بارگذاری…
        </div>
      )}

      {/* Stats row */}
      {!loading && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: "پنل",     val: pRows.length,  color: "bg-blue-50  text-blue-700" },
            { label: "سرور",    val: sRows.length,  color: "bg-indigo-50 text-indigo-700" },
            { label: "استخر",    val: gRows.length,  color: "bg-purple-50 text-purple-700" },
            { label: "محصول",   val: prRows.length, color: "bg-teal-50   text-teal-700" },
          ].map((c) => (
            <div key={c.label} className={`rounded-xl p-3 text-center ${c.color}`}>
              <p className="text-2xl font-extrabold">{c.val}</p>
              <p className="text-xs font-bold">{c.label}</p>
            </div>
          ))}
        </div>
      )}

      {/* Panel health check results */}
      {Object.keys(results).length > 0 && (
        <section className="rounded-xl border border-[var(--ln)] p-4">
          <h3 className="mb-3 font-bold">نتایج بررسی سلامت</h3>
          <div className="space-y-2">
            {pRows.filter((p) => results[p.id]).map((p) => (
              <div key={p.id} className="flex items-center justify-between rounded-lg bg-[var(--mb)] px-3 py-2">
                <span className="text-sm font-medium">{p.name}</span>
                <div className="flex items-center gap-2">
                  <Badge ok={results[p.id]?.healthy} />
                  <span className="text-xs text-[var(--mu)]">
                    {results[p.id]?.checkedAt?.toLocaleTimeString("fa-IR")}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Issue sections */}
      {!loading && (<>
        <IssueSection title="پنل‌های غیرفعال" items={disabledPanels} color="gray">
          {(p) => (
            <div className="flex items-center justify-between">
              <span>{p.name}</span>
              <button className="btn !py-0.5 !text-xs" onClick={() => checkPanel(p.id)} disabled={checking.has(p.id)}>
                {checking.has(p.id) ? <Loader size={11} className="animate-spin" /> : "بررسی"}
              </button>
            </div>
          )}
        </IssueSection>

        <IssueSection title="پنل‌های بدون سرور" items={noServerPanels} color="orange">
          {(p) => <span>{p.name} — <span className="text-xs">هیچ سروری تعریف نشده</span></span>}
        </IssueSection>

        <IssueSection title="سرورهای غیرفعال" items={disabledServers} color="gray">
          {(s) => <span>{s.name} <span className="text-xs text-[var(--mu)]">— {(pRows.find((p) => p.id === s.panel_id) || {}).name || "پنل نامشخص"}</span></span>}
        </IssueSection>

        <IssueSection title="سرورهای یتیم (پنل حذف‌شده)" items={orphanServers} color="red">
          {(s) => <span>{s.name}</span>}
        </IssueSection>

        <IssueSection title="استخرهای خالی" items={emptyGroups} color="blue">
          {(g) => <span>{g.name}</span>}
        </IssueSection>

        <IssueSection title="محصولات فعال بدون مسیر تخصیص" items={unusedProducts} color="blue">
          {(pr) => <span>{pr.name} <span className="text-xs text-[var(--mu)]">— {idx.reach(pr).issue}</span></span>}
        </IssueSection>
      </>)}
    </div>
  );
}
