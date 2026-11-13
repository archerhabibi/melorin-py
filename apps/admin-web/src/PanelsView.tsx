import { useCallback, useEffect, useMemo, useState } from 'react';
import { authFetch } from './api.ts';
import { ServerForm, ServerImport } from './ServerForm.tsx';
import { TargetWizard } from './TargetPicker.tsx';
import { confirmDialog } from './ui.tsx';
import {
  InfraChain,
  clearParam,
  free,
  health,
  memberIds,
  saveGroupPanels,
  serverState,
  serves,
  useHashParams,
  useInfra,
} from './infra.tsx';
import {
  Empty,
  ErrorBar,
  KpiBar,
  Paginator,
  SearchBox,
  SortSelect,
  Stat,
  ViewToggle,
  errText,
  num,
  removeEntity,
  useAlive,
} from './kit.tsx';
import { AlertTriangle, Plus, RefreshCw, Server, ServerCog, ShieldAlert, ShieldCheck } from 'lucide-react';
import { kindOf } from './panels/panelUi.tsx';
import { PanelDrawer } from './panels/PanelDrawer.tsx';
import { PanelDetailDrawer } from './panels/PanelDetailDrawer.tsx';
import { PanelSection } from './panels/PanelSection.tsx';
import type { Json, Rec, Toast } from './types.ts';

// Panels and their servers are ONE screen: a server is only a capacity slot of a single panel,
// so it is created, edited and enabled right under the panel it belongs to. Group membership of a
// panel can be set here too (it is saved through the same API the group screen uses).

// ---------- page ----------
// Deep links: #/panels?id=<panel> · ?group=<group id> · ?product=<code> · ?add=1 (new panel) · ?id=<panel>&add=server
const PAGE_SIZE = 10;
export default function PanelsView({ api, toast }: { api?: Json; toast: Toast }) {
  const infra = useInfra(api);
  const { idx } = infra;
  const params = useHashParams();
  const alive = useAlive();
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState('all');
  const [only, setOnly] = useState(params.get('id') || '');
  const [groupF, setGroupF] = useState(params.get('group') || '');
  const [productF, setProductF] = useState(params.get('product') || '');
  const [drawer, setDrawer] = useState<Json>(null);
  const [busy, setBusy] = useState(new Set());
  const [bulk, setBulk] = useState<Json>(null);
  const [srvDrawer, setSrvDrawer] = useState<Json>(null);
  const [srvBusy, setSrvBusy] = useState(new Set());
  const [importFor, setImportFor] = useState<Json>(null);
  const [wizardFor, setWizardFor] = useState<Json>(null);
  const [detailFor, setDetailFor] = useState<Json>(null); // {id, tab}: panel operations, opened by #/panels?detail=<id>[&tab=]
  const [page, setPage] = useState(0);
  const [sort, setSort] = useState('attention');
  const [dense, setDense] = useState('full');
  useEffect(() => {
    setOnly(params.get('id') || '');
    setGroupF(params.get('group') || '');
    setProductF(params.get('product') || '');
  }, [params]);
  useEffect(() => {
    if (params.get('detail')) {
      setDetailFor({ id: params.get('detail'), tab: params.get('tab') });
      clearParam('detail');
      clearParam('tab');
    }
  }, [params]); // eslint-disable-line react-hooks/exhaustive-deps -- same pattern as the add-deep-link effect below
  useEffect(() => {
    if (params.get('add') === '1') {
      setDrawer('add');
      clearParam('add');
    } else if (params.get('add') === 'server' && params.get('id')) {
      setSrvDrawer({ panelId: params.get('id'), serverId: null });
      clearParam('add');
    }
  }, [params]);
  useEffect(() => {
    setPage(0);
  }, [filter, q, only, groupF, productF]);

  const rows = infra.panels.rows,
    failed = infra.panels.failed,
    load = infra.panels.load;
  // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
  const allServers = infra.servers.rows || [];

  const probe = useCallback(
    async (p: Json) => {
      setBusy((s) => new Set(s).add(p.id));
      let ok = false,
        healthy = false;
      try {
        const r = await authFetch(api.base, `/api/v1/admin/panels/${p.id}/health`, { method: 'POST' });
        ok = r.ok;
        healthy = ok && (await r.json()).healthy;
      } catch {
        /* network */
      }
      if (alive.current)
        setBusy((s) => {
          const n = new Set(s);
          n.delete(p.id);
          return n;
        });
      return { ok, healthy };
    },
    [api.base, alive],
  );
  const healthToast = useCallback(
    (p: Json, { ok, healthy }: Json) =>
      toast(!ok ? `بررسی «${p.name}» ناموفق بود` : healthy ? `«${p.name}» سالم است` : `«${p.name}» پاسخ سالم نداد`),
    [toast],
  );
  const check = useCallback(
    async (p: Json, quiet: Json) => {
      const res = await probe(p);
      if (!quiet) {
        healthToast(p, res);
        await infra.reload();
      }
      return res.healthy;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
    [probe, healthToast],
  );

  const checkAll = async () => {
    const list = (rows || []).filter((p) => p.is_enabled);
    if (!list.length) return;
    if (
      !(await confirmDialog(`سلامت ${num(list.length)} پنل فعال بررسی شود؟`, { title: 'بررسی همه پنل‌ها', ok: 'شروع' }))
    )
      return;
    let done = 0,
      bad = 0;
    setBulk({ done, total: list.length });
    const queue = [...list];
    await Promise.all(
      Array.from({ length: Math.min(3, queue.length) }, async () => {
        for (let p = queue.shift(); p; p = queue.shift()) {
          if (!(await check(p, true))) bad++;
          done++;
          if (alive.current) setBulk({ done, total: list.length });
        }
      }),
    );
    if (alive.current) setBulk(null);
    toast(bad ? `${num(bad)} پنل از ${num(list.length)} مورد ناسالم است` : 'همه پنل‌ها سالم هستند');
    await infra.reload();
  };

  // One save = panel (+ first server on create) (+ group membership). Every step reports its own failure.
  const save = async (payload: Json, withCheck: Json, { server, gids, was }: Json) => {
    const editing = drawer !== 'add';
    const r = await authFetch(api.base, editing ? `/api/v1/admin/panels/${drawer}` : '/api/v1/admin/panels', {
      method: editing ? 'PATCH' : 'POST',
      body: JSON.stringify(payload),
    });
    if (!r.ok) return errText(r, editing ? 'ذخیره تغییرات ناموفق بود' : 'ثبت پنل ناموفق بود');
    const id = editing ? drawer : (await r.json())?.id;
    const notes: Json[] = [];
    if (!editing && server && id) {
      const sr = await authFetch(api.base, '/api/v1/admin/servers', {
        method: 'POST',
        body: JSON.stringify({
          name: server.name,
          panel_id: id,
          location: server.location || null,
          capacity: server.capacity,
          product_codes: null,
          allow_test: true,
        }),
      });
      if (!sr.ok) notes.push(`ساخت سرور ناموفق بود (${await errText(sr, 'خطا')}) — از «سرور جدید» اضافه کنید`);
    }
    const toAdd = gids.filter((g: Json) => !was.includes(g)),
      toDel = was.filter((g: Json) => !gids.includes(g));
    for (const gid of [...toAdd, ...toDel]) {
      const g = (infra.groups.rows || []).find((x) => x.id === gid);
      if (!g || !id) continue;
      const cur = memberIds(g),
        next = toAdd.includes(gid) ? [...cur.filter((x: Json) => x !== id), id] : cur.filter((x: Json) => x !== id);
      const m = await saveGroupPanels(infra.call, g, next);
      if (m) notes.push(`«${g.name}»: ${m}`);
    }
    setDrawer(null);
    toast(
      notes.length
        ? notes.join(' · ')
        : editing
          ? 'تغییرات ذخیره شد'
          : server
            ? 'پنل و سرور ثبت شد'
            : 'پنل ثبت شد — مرحله بعد: افزودن سرور',
    );
    // Health probe runs BEFORE the single reload so the reloaded list already shows the fresh status.
    if (withCheck && id) healthToast({ id, name: payload.name }, await probe({ id, name: payload.name }));
    await infra.reload();
    return '';
  };

  const toggle = async (p: Json, next: Json) => {
    if (
      !next &&
      !(await confirmDialog(
        `«${p.name}» غیرفعال شود؟ برای ساخت اکانت جدید استفاده نمی‌شود و بررسی سلامت خودکار آن هم متوقف می‌شود.`,
        { title: 'غیرفعال‌سازی پنل', danger: true, ok: 'غیرفعال کن' },
      ))
    )
      return;
    setBusy((x) => new Set(x).add(p.id));
    let ok = false;
    try {
      ok = (
        await authFetch(api.base, `/api/v1/admin/panels/${p.id}/state`, {
          method: 'POST',
          body: JSON.stringify({ is_enabled: next }),
        })
      ).ok;
    } catch {
      /* network */
    }
    if (alive.current)
      setBusy((x) => {
        const n = new Set(x);
        n.delete(p.id);
        return n;
      });
    toast(ok ? (next ? `«${p.name}» فعال شد` : `«${p.name}» غیرفعال شد`) : 'تغییر وضعیت ناموفق بود');
    if (ok) await load();
  };
  const srvToggle = async (s: Json, next: Json) => {
    if (
      !next &&
      !(await confirmDialog(
        `«${s.name}» غیرفعال شود؟ برای ساخت اکانت جدید انتخاب نمی‌شود؛ اکانت‌های موجود حذف نمی‌شوند.`,
        { title: 'غیرفعال‌سازی سرور', danger: true, ok: 'غیرفعال کن' },
      ))
    )
      return;
    setSrvBusy((x) => new Set(x).add(s.id));
    let ok = false;
    try {
      ok = (
        await authFetch(api.base, `/api/v1/admin/servers/${s.id}/state`, {
          method: 'POST',
          body: JSON.stringify({ is_enabled: next }),
        })
      ).ok;
    } catch {
      /* network */
    }
    if (alive.current)
      setSrvBusy((x) => {
        const n = new Set(x);
        n.delete(s.id);
        return n;
      });
    toast(ok ? (next ? `«${s.name}» فعال شد` : `«${s.name}» غیرفعال شد`) : 'تغییر وضعیت ناموفق بود');
    if (ok) await infra.servers.load();
  };

  const removePanel = async (p: Json) => {
    const n = (idx.serversByPanel.get(p.id) || []).length;
    setBusy((x) => new Set(x).add(p.id));
    const ok = await removeEntity(infra.call, `/api/v1/admin/panels/${p.id}`, {
      toast,
      title: 'حذف پنل',
      done: `«${p.name}» حذف شد`,
      message: `«${p.name}» برای همیشه حذف شود؟${n ? ` ${num(n)} سرور آن هم حذف می‌شود و` : ''} از بسته‌ها خارج می‌شود. پنل واقعی (سنایی/پاسارگارد) دست‌نخورده می‌ماند. اگر روی این پنل اکانت ساخته شده باشد حذف انجام نمی‌شود و باید آن را غیرفعال کنید.`,
    });
    if (alive.current)
      setBusy((x) => {
        const m = new Set(x);
        m.delete(p.id);
        return m;
      });
    if (ok) {
      setDrawer(null);
      setSrvDrawer(null);
      await infra.reload();
    }
  };
  const removeServer = async (s: Json) => {
    setSrvBusy((x) => new Set(x).add(s.id));
    const ok = await removeEntity(infra.call, `/api/v1/admin/servers/${s.id}`, {
      toast,
      title: 'حذف سرور',
      done: `«${s.name}» حذف شد`,
      message: `«${s.name}» برای همیشه حذف شود؟ اگر روی این سرور اکانت ساخته شده باشد حذف انجام نمی‌شود و باید آن را غیرفعال کنید.`,
    });
    if (alive.current)
      setSrvBusy((x) => {
        const m = new Set(x);
        m.delete(s.id);
        return m;
      });
    if (ok) {
      setSrvDrawer(null);
      await infra.reload();
    }
  };

  const attention = (p: Json) => p.is_enabled && health(p) !== 'healthy';
  const counts = useMemo(() => {
    const c = { all: 0, healthy: 0, attention: 0 };
    (rows || []).forEach((p) => {
      c.all++;
      if (health(p) === 'healthy') c.healthy++;
      if (attention(p)) c.attention++;
    });
    return c;
  }, [rows]);
  const cap = useMemo(() => {
    let freeN = 0,
      total = 0;
    allServers.forEach((s) => {
      total += s.capacity || 0;
      if (serverState(s, idx.panelById.get(s.panel_id)).ok) freeN += free(s);
    });
    return { free: freeN, total };
  }, [allServers, idx]);
  const group: Json = groupF ? idx.groupById.get(groupF) : null;
  const groupPanels = useMemo(() => (group ? new Set(memberIds(group)) : null), [group]);
  const productObj = productF ? (infra.products.rows || []).find((x) => x.code === productF) : null;
  const serversOf = (p: Json) =>
    (idx.serversByPanel.get(p.id) || []).filter((s: Json) => !productF || serves(s, productF));
  const filtered = useMemo(
    () =>
      (rows || []).filter(
        (p) =>
          (!only || p.id === only) &&
          (filter === 'all' || (filter === 'healthy' ? health(p) === 'healthy' : attention(p))) &&
          (!groupPanels || groupPanels.has(p.id)) &&
          (!productF || (idx.serversByPanel.get(p.id) || []).some((s: Json) => serves(s, productF))) &&
          `${p.name} ${p.base_url} ${kindOf(p.kind).title} ${(idx.serversByPanel.get(p.id) || []).map((s: Json) => `${s.name} ${s.location || ''}`).join(' ')}`
            .toLowerCase()
            .includes(q.trim().toLowerCase()),
      ),
    [rows, filter, q, only, groupPanels, productF, idx],
  );
  const sorted = useMemo(() => {
    const rank = (p: Json) =>
      !p.is_enabled
        ? 4
        : health(p) === 'unhealthy'
          ? 0
          : health(p) === 'degraded'
            ? 1
            : health(p) === 'unknown'
              ? 2
              : 3;
    const by: Rec = {
      attention: (a: Json, b: Json) => rank(a) - rank(b) || a.name.localeCompare(b.name, 'fa'),
      name: (a: Json, b: Json) => a.name.localeCompare(b.name, 'fa'),
      free: (a: Json, b: Json) =>
        idx.panelStat(b.id).capacity -
        idx.panelStat(b.id).active -
        (idx.panelStat(a.id).capacity - idx.panelStat(a.id).active),
      usage: (a: Json, b: Json) => {
        const f = (p: Json) => {
          const x = idx.panelStat(p.id);
          return x.capacity ? x.active / x.capacity : 0;
        };
        return f(b) - f(a);
      },
    };
    return [...filtered].sort(by[sort]);
  }, [filtered, sort, idx]);
  const shown = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const loading = rows === null || infra.loading;
  const editing = drawer && drawer !== 'add' ? (rows || []).find((p) => p.id === drawer) : null;
  const srvPanel = srvDrawer ? (rows || []).find((p) => p.id === srvDrawer.panelId) : null;
  const srvEditing = srvDrawer?.serverId ? allServers.find((s) => s.id === srvDrawer.serverId) : null;
  const locations = useMemo(() => [...new Set(allServers.map((s) => s.location).filter(Boolean))].sort(), [allServers]);
  const hasScope = only || groupF || productF;
  const clearScope = () => {
    setOnly('');
    setGroupF('');
    setProductF('');
    if (window.location.hash.includes('?'))
      window.history.replaceState(
        null,
        '',
        `${window.location.pathname}${window.location.search}${window.location.hash.split('?')[0]}`,
      );
  };

  return (
    <div className="space-y-5">
      <InfraChain current="panels" infra={infra} />
      <KpiBar cols={4}>
        <Stat
          label="همه پنل‌ها"
          value={counts.all}
          tone="in"
          Icon={Server}
          active={filter === 'all'}
          onClick={() => setFilter('all')}
        />
        <Stat
          label="سالم"
          value={counts.healthy}
          tone="ok"
          Icon={ShieldCheck}
          active={filter === 'healthy'}
          onClick={() => setFilter(filter === 'healthy' ? 'all' : 'healthy')}
        />
        <Stat
          label="نیازمند بررسی (ناسالم / بررسی‌نشده)"
          value={counts.attention}
          tone={counts.attention ? 'bd' : 'mu'}
          Icon={ShieldAlert}
          active={filter === 'attention'}
          onClick={() => setFilter(filter === 'attention' ? 'all' : 'attention')}
        />
        <Stat
          label={`ظرفیت آزاد قابل فروش از ${num(cap.total)}`}
          value={cap.free}
          tone={cap.free ? 'ok' : 'bd'}
          Icon={ServerCog}
          ring={cap.total ? cap.free / cap.total : 0}
        />
      </KpiBar>

      <div className="tool">
        <SearchBox
          label="جستجوی پنل یا سرور"
          placeholder="جستجو در پنل، سرور، موقعیت یا آدرس…"
          value={q}
          onChange={setQ}
        />
        {!!(infra.groups.rows || []).length && (
          <select
            aria-label="فیلتر بسته"
            className="inp !w-auto !py-2 !text-xs font-bold"
            value={groupF}
            onChange={(e) => setGroupF(e.target.value)}
          >
            <option value="">همه بسته‌ها</option>
            {(infra.groups.rows || []).map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        )}
        <SortSelect
          value={sort}
          onChange={setSort}
          options={[
            ['attention', 'مشکل‌دارها اول'],
            ['name', 'نام'],
            ['free', 'بیشترین ظرفیت آزاد'],
            ['usage', 'بیشترین پُری'],
          ]}
        />
        <ViewToggle
          value={dense}
          onChange={setDense}
          options={[
            ['full', 'کامل'],
            ['dense', 'فشرده'],
          ]}
        />
        <div className="mr-auto flex items-center gap-2">
          <button className="btn btn-g !py-2 !text-sm" onClick={checkAll} disabled={!!bulk || !counts.all}>
            <RefreshCw size={14} className={bulk ? 'animate-spin' : ''} />
            {bulk ? `${num(bulk.done)} از ${num(bulk.total)}` : 'بررسی همه'}
          </button>
          <button className="btn" onClick={() => setDrawer('add')}>
            <Plus size={16} />
            افزودن پنل
          </button>
        </div>
      </div>

      {hasScope && (
        <p className="flex flex-wrap items-center gap-2 rounded-xl bg-[var(--inb)] px-3 py-2 text-xs font-bold text-[var(--in)]">
          {only && <>فقط یک پنل نمایش داده می‌شود</>}
          {group && <>پنل‌های بسته «{group.name}»</>}
          {productObj && (
            <>
              {group || only ? ' · ' : ''}پنل‌ها و سرورهایی که «{productObj.name}» را پوشش می‌دهند
            </>
          )}
          <button className="mr-auto underline" onClick={clearScope}>
            نمایش همه
          </button>
        </p>
      )}

      {failed && (
        <ErrorBar onRetry={infra.reload}>
          <AlertTriangle size={16} />
          دریافت پنل‌ها ناموفق بود.
        </ErrorBar>
      )}

      {loading ? (
        <div className="space-y-4">
          {[0, 1].map((i) => (
            <div key={i} className="card skel h-56" />
          ))}
        </div>
      ) : !filtered.length ? (
        <Empty
          Icon={Server}
          title={counts.all ? 'پنلی با این فیلتر پیدا نشد' : 'هنوز پنلی اضافه نشده'}
          text={
            counts.all
              ? 'جستجو یا فیلتر را تغییر دهید.'
              : 'برای فروش اکانت، ابتدا یک پنل سنایی یا پاسارگارد به Core وصل کنید؛ ظرفیت (سرور) آن هم در همان مرحله تعریف می‌شود.'
          }
        >
          {!counts.all && (
            <button className="btn" onClick={() => setDrawer('add')}>
              <Plus size={16} />
              افزودن اولین پنل
            </button>
          )}
        </Empty>
      ) : (
        <>
          <div className="space-y-4">
            {shown.map((p) => (
              <PanelSection
                key={p.id}
                p={p}
                servers={serversOf(p)}
                stat={idx.panelStat(p.id)}
                groups={idx.groupsByPanel.get(p.id) || []}
                busy={busy.has(p.id)}
                srvBusy={srvBusy}
                filtered={!!productF || !!q.trim()}
                dense={dense === 'dense'}
                onCheck={check}
                onEdit={(x: Json) => setDrawer(x.id)}
                onToggle={toggle}
                onDelete={removePanel}
                onSrvDelete={removeServer}
                onSrvAdd={(x: Json) => setSrvDrawer({ panelId: x.id, serverId: null })}
                onSrvEdit={(s: Json) => setSrvDrawer({ panelId: s.panel_id, serverId: s.id })}
                onSrvToggle={srvToggle}
                onImport={setImportFor}
                onWizard={setWizardFor}
              />
            ))}
          </div>
          <Paginator page={page} setPage={setPage} total={filtered.length} pageSize={PAGE_SIZE} />
        </>
      )}

      {drawer && (drawer === 'add' || editing) && (
        <PanelDrawer
          key={drawer}
          panel={drawer === 'add' ? null : editing}
          groups={infra.groups.rows || []}
          idx={idx}
          onClose={() => setDrawer(null)}
          onSubmit={save}
          onToggle={toggle}
          onDelete={removePanel}
          toggling={editing ? busy.has(editing.id) : false}
        />
      )}
      {detailFor && (
        <PanelDetailDrawer
          api={api}
          toast={toast}
          panel={
            ((infra.panels?.rows || []).find((x: Json) => x.id === detailFor.id) as
              { id: string; name: string } | undefined) || {
              id: String(detailFor.id),
              name: 'پنل',
            }
          }
          tab={detailFor.tab}
          onClose={() => setDetailFor(null)}
        />
      )}
      {srvDrawer && srvPanel && (!srvDrawer.serverId || srvEditing) && (
        <ServerForm
          key={`${srvDrawer.panelId}:${srvDrawer.serverId || 'new'}`}
          api={api}
          toast={toast}
          infra={infra}
          panel={srvPanel}
          server={srvEditing || null}
          locations={locations}
          toggling={srvEditing ? srvBusy.has(srvEditing.id) : false}
          onToggle={srvToggle}
          onDelete={removeServer}
          onSaved={infra.reload}
          onClose={() => setSrvDrawer(null)}
        />
      )}
      {wizardFor && (
        <TargetWizard
          api={api}
          toast={toast}
          panel={wizardFor}
          onClose={() => setWizardFor(null)}
          onDone={infra.reload}
        />
      )}
      {importFor && (
        <ServerImport
          api={api}
          toast={toast}
          panel={importFor}
          onClose={() => setImportFor(null)}
          onDone={infra.reload}
        />
      )}
    </div>
  );
}
