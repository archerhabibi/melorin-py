import { useCallback, useEffect, useMemo, useState } from 'react';
import { typedClient } from '../../api/api.ts';
import { ServerForm } from './ServerForm.tsx';
import { ServerImport } from './ServerImport.tsx';
import { TargetWizard } from './TargetPicker.tsx';
import { confirmDialog } from '../../shared/ui.tsx';
import {
  clearParam,
  free,
  health,
  memberIds,
  saveGroupPanels,
  serverState,
  useHashParams,
  useInfra,
} from '../panel-operations/infra.tsx';
import { InfraChain } from '../panel-operations/InfraChain.tsx';
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
} from '../../shared/kit.tsx';
import { AlertTriangle, Plus, RefreshCw, Server, ServerCog, ShieldAlert, ShieldCheck } from 'lucide-react';
import { kindOf } from './panelUi.tsx';
import { PanelDrawer } from './PanelDrawer.tsx';
import { PanelDetailDrawer } from './PanelDetailDrawer.tsx';
import { PanelSection } from './PanelSection.tsx';
import { PanelsToolbar } from './PanelsToolbar.tsx';
import type { Json, Rec, Toast } from '../../shared/types.ts';

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
        const { response: r, data } = await typedClient(api.base).post('/api/v1/admin/panels/{panel_id}/health', {
          params: { path: { panel_id: p.id } },
        });
        ok = r.ok;
        healthy = ok && !!(data as { healthy?: boolean } | undefined)?.healthy;
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
    const client = typedClient(api.base);
    const {
      response: r,
      data,
      error,
    } = editing
      ? await client.patch('/api/v1/admin/panels/{panel_id}', { params: { path: { panel_id: drawer } }, body: payload })
      : await client.post('/api/v1/admin/panels', { body: payload });
    // the typed client already consumed the body, so errText reads the parsed error
    if (!r.ok) return errText({ json: async () => error }, editing ? 'ذخیره تغییرات ناموفق بود' : 'ثبت پنل ناموفق بود');
    const id = editing ? drawer : (data as { id?: string } | undefined)?.id;
    const notes: Json[] = [];
    if (!editing && server && id) {
      const { response: sr, error: serr } = await client.post('/api/v1/admin/servers', {
        body: {
          name: server.name,
          panel_id: id,
          location: server.location || null,
          capacity: server.capacity,
          allow_test: true,
        },
      });
      if (!sr.ok)
        notes.push(
          `ساخت سرور ناموفق بود (${await errText({ json: async () => serr }, 'خطا')}) — از «سرور جدید» اضافه کنید`,
        );
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
        await typedClient(api.base).post('/api/v1/admin/panels/{panel_id}/state', {
          params: { path: { panel_id: p.id } },
          body: { is_enabled: next },
        })
      ).response.ok;
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
        await typedClient(api.base).post('/api/v1/admin/servers/{server_id}/state', {
          params: { path: { server_id: s.id } },
          body: { is_enabled: next },
        })
      ).response.ok;
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
  const productPanels = productObj
    ? new Set((idx.groupsByProduct.get(productObj.id) || []).flatMap((g: Json) => memberIds(g)))
    : null;
  const serversOf = (p: Json) => idx.serversByPanel.get(p.id) || [];
  const filtered = useMemo(
    () =>
      (rows || []).filter(
        (p) =>
          (!only || p.id === only) &&
          (filter === 'all' || (filter === 'healthy' ? health(p) === 'healthy' : attention(p))) &&
          (!groupPanels || groupPanels.has(p.id)) &&
          (!productPanels || productPanels.has(p.id)) &&
          `${p.name} ${p.base_url} ${kindOf(p.kind).title} ${(idx.serversByPanel.get(p.id) || []).map((s: Json) => `${s.name} ${s.location || ''}`).join(' ')}`
            .toLowerCase()
            .includes(q.trim().toLowerCase()),
      ),
    [rows, filter, q, only, groupPanels, productF, idx, productObj],
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
      <PanelsToolbar
        counts={counts}
        cap={cap}
        filter={filter}
        setFilter={setFilter}
        q={q}
        setQ={setQ}
        groups={infra.groups.rows || []}
        groupF={groupF}
        setGroupF={setGroupF}
        sort={sort}
        setSort={setSort}
        dense={dense}
        setDense={setDense}
        bulk={bulk}
        checkAll={checkAll}
        onAdd={() => setDrawer('add')}
        hasScope={!!hasScope}
        only={only}
        group={group}
        productObj={productObj}
        clearScope={clearScope}
      />

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
