import { useEffect, useMemo, useState } from 'react';
import { confirmDialog } from './ui.jsx';
import { CheckCircle2, Layers, Plus, ShieldAlert } from 'lucide-react';
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
  removeEntity,
  useAlive,
  useRows,
} from './kit.jsx';
import { InfraChain, clearParam, memberIds, useHashParams, useInfra } from './infra.jsx';
import { API, groupIssue, GroupCard, GroupTable } from './bundles/BundleParts.jsx';
import { GroupDrawer } from './bundles/BundleDrawer.jsx';

// A sales bundle is a SALES BUNDLE (بسته فروش): panels + connection kind + the packages it sells, each with
// its own price. Customers pick a bundle, so the bundle is the only way an account gets sold; there is no
// bundle-less route. Selection / naming / reseller policy are advanced options: most bundles never change them.
export default function BundlesView({ api, toast }) {
  const infra = useInfra(api);
  const { call, idx } = infra;
  const groups = infra.groups,
    panelsQ = infra.panels,
    storesQ = useRows(call, '/api/v1/admin/stores');
  const hasResellers = (storesQ.rows || []).some((x) => x.kind === 'reseller'); // no resellers yet = no cooperation switches or prices
  const params = useHashParams();
  const [q, setQ] = useState(params.get('q') || ''),
    [filter, setFilter] = useState('all'),
    [drawer, setDrawer] = useState(null),
    [busy, setBusy] = useState(new Set()),
    [sort, setSort] = useState('attention'),
    [layout, setLayout] = useState('cards');
  const PAGE_SIZE = 20;
  const [page, setPage] = useState(0);
  useEffect(() => {
    setPage(0);
  }, [filter, q]);
  const alive = useAlive();
  useEffect(() => {
    setQ(params.get('q') || '');
    if (params.get('add') === '1') {
      setDrawer('add');
      clearParam('add');
    }
  }, [params]);
  const rows = groups.rows,
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
    panels = panelsQ.rows || [],
    products = infra.products.rows || [];
  const panelById = useMemo(() => Object.fromEntries(panels.map((p) => [p.id, p])), [panels]);
  const attention = (g) => !!groupIssue(g, idx.groupStat(g));
  const counts = useMemo(() => {
    const c = { all: 0, on: 0, off: 0, bad: 0 };
    (rows || []).forEach((g) => {
      c.all++;
      g.is_enabled ? c.on++ : c.off++;
      if (attention(g)) c.bad++;
    });
    return c;
  }, [rows, idx]); // eslint-disable-line react-hooks/exhaustive-deps
  const filtered = useMemo(
    () =>
      (rows || []).filter(
        (g) =>
          (filter === 'all' || (filter === 'on' ? g.is_enabled : filter === 'off' ? !g.is_enabled : attention(g))) &&
          g.name.toLowerCase().includes(q.trim().toLowerCase()),
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- T-W08: reviewed, dependency list intentionally limited (adding the flagged value risks refetch loops); verify in a browser before changing
    [rows, filter, q, idx],
  );
  const sorted = useMemo(() => {
    const by = {
      attention: (a, b) =>
        Number(!!groupIssue(b, idx.groupStat(b))) - Number(!!groupIssue(a, idx.groupStat(a))) ||
        Number(b.is_enabled) - Number(a.is_enabled) ||
        a.name.localeCompare(b.name, 'fa'),
      name: (a, b) => a.name.localeCompare(b.name, 'fa'),
      sold: (a, b) => (b.sold_count || 0) - (a.sold_count || 0),
      free: (a, b) => idx.groupStat(b).free - idx.groupStat(a).free,
    };
    return [...filtered].sort(by[sort]);
  }, [filtered, sort, idx]);
  const shown = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const editing = drawer && drawer !== 'add' ? (rows || []).find((g) => g.id === drawer) : null;

  const save = async (f, group) => {
    const labels = Object.fromEntries(f.panel_ids.map((id) => [id, (f.member_labels[id] || '').trim()]));
    const same = group && JSON.stringify(memberIds(group)) === JSON.stringify(f.panel_ids);
    const body = {
      name: f.name,
      selection_mode: f.selection_mode,
      balancing: f.balancing,
      naming_mode: f.naming_mode,
      kind_label: f.kind_label,
      is_enabled: f.is_enabled,
      reseller_enabled: f.reseller_enabled,
      sales_limit: f.sales_limit,
      member_labels: labels,
      ...(group ? (same ? {} : { panel_ids: f.panel_ids }) : { panel_ids: f.panel_ids }),
    };
    const r = await call(group ? `${API}/${group.id}` : API, {
      method: group ? 'PATCH' : 'POST',
      body: JSON.stringify(body),
    });
    if (!r.ok) return errText(r, group ? 'ذخیره تغییرات ناموفق بود' : 'ساخت بسته ناموفق بود');
    if (group) {
      setDrawer(null);
      toast('تغییرات بسته ذخیره شد');
    } else {
      const created = await r.json();
      setDrawer(created.id);
      toast('بسته ساخته شد؛ حالا پکیج‌هایش را اضافه کنید');
    }
    await infra.reload();
    return '';
  };
  const remove = async (g) => {
    setBusy((s) => new Set(s).add(g.id));
    const ok = await removeEntity(call, `${API}/${g.id}`, {
      toast,
      title: 'حذف بسته فروش',
      done: `«${g.name}» حذف شد`,
      message: `«${g.name}» برای همیشه حذف شود؟ فقط خودِ بسته و اتصالش به فروشگاه‌ها پاک می‌شود؛ پنل‌های عضو دست‌نخورده می‌مانند. اگر بستهِ پیش‌فرضِ یک محصول باشد یا سفارشی از آن ساخته شده باشد، حذف انجام نمی‌شود.`,
    });
    if (alive.current)
      setBusy((s) => {
        const n = new Set(s);
        n.delete(g.id);
        return n;
      });
    if (ok) {
      setDrawer(null);
      await infra.reload();
    }
  };
  const toggleReseller = async (g, next) => {
    setBusy((s) => new Set(s).add(g.id));
    let ok = false;
    try {
      ok = (await call(`${API}/${g.id}`, { method: 'PATCH', body: JSON.stringify({ reseller_enabled: next }) })).ok;
    } catch {
      /* network */
    }
    if (alive.current)
      setBusy((s) => {
        const n = new Set(s);
        n.delete(g.id);
        return n;
      });
    toast(
      ok
        ? next
          ? `«${g.name}» برای نمایندگان فعال شد`
          : `«${g.name}» برای نمایندگان غیرفعال شد`
        : 'تغییر وضعیت ناموفق بود',
    );
    if (ok) await infra.reload();
  };
  const toggle = async (g, next) => {
    if (
      !next &&
      !(await confirmDialog(
        `«${g.name}» غیرفعال شود؟ تا فعال‌سازی مجدد برای فروش جدید استفاده نمی‌شود${hasResellers ? ' و برای نمایندگان هم غیرفعال می‌شود' : ''}.`,
        { title: 'غیرفعال‌سازی بسته', danger: true, ok: 'غیرفعال‌سازی' },
      ))
    )
      return;
    setBusy((s) => new Set(s).add(g.id));
    let ok = false;
    try {
      ok = (await call(`${API}/${g.id}`, { method: 'PATCH', body: JSON.stringify({ is_enabled: next }) })).ok;
    } catch {
      /* network */
    }
    if (alive.current)
      setBusy((s) => {
        const n = new Set(s);
        n.delete(g.id);
        return n;
      });
    toast(ok ? (next ? `«${g.name}» فعال شد` : `«${g.name}» غیرفعال شد`) : 'تغییر وضعیت ناموفق بود');
    if (ok) await infra.reload();
  };

  return (
    <div className="space-y-5">
      <InfraChain current="groups" infra={infra} />
      <KpiBar cols={4}>
        <Stat
          label="همه بسته‌ها"
          value={counts.all}
          tone="in"
          Icon={Layers}
          active={filter === 'all'}
          onClick={() => setFilter('all')}
        />
        <Stat
          label="فعال"
          value={counts.on}
          tone="ok"
          Icon={CheckCircle2}
          active={filter === 'on'}
          onClick={() => setFilter(filter === 'on' ? 'all' : 'on')}
        />
        <Stat
          label="غیرفعال"
          value={counts.off}
          tone="mu"
          Icon={Layers}
          active={filter === 'off'}
          onClick={() => setFilter(filter === 'off' ? 'all' : 'off')}
        />
        <Stat
          label="نمی‌تواند بفروشد"
          value={counts.bad}
          tone={counts.bad ? 'bd' : 'mu'}
          Icon={ShieldAlert}
          active={filter === 'bad'}
          onClick={() => setFilter(filter === 'bad' ? 'all' : 'bad')}
        />
      </KpiBar>
      <div className="tool">
        <SearchBox label="جستجوی بسته" placeholder="جستجوی نام بسته…" value={q} onChange={setQ} />
        <SortSelect
          value={sort}
          onChange={setSort}
          options={[
            ['attention', 'مشکل‌دارها اول'],
            ['name', 'نام'],
            ['sold', 'بیشترین فروش'],
            ['free', 'بیشترین ظرفیت آزاد'],
          ]}
        />
        <ViewToggle
          value={layout}
          onChange={setLayout}
          options={[
            ['cards', 'کارتی'],
            ['table', 'جدولی'],
          ]}
        />
        <button className="btn mr-auto" onClick={() => setDrawer('add')}>
          <Plus size={16} />
          افزودن بسته
        </button>
      </div>
      {groups.failed && (
        <ErrorBar onRetry={groups.load}>
          <ShieldAlert size={16} />
          دریافت بسته‌ها ناموفق بود.
        </ErrorBar>
      )}
      {rows === null ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card skel h-72" />
          ))}
        </div>
      ) : !shown.length ? (
        <Empty
          Icon={Layers}
          title={counts.all ? 'بسته‌ای با این فیلتر پیدا نشد' : 'هنوز بسته‌ای ساخته نشده'}
          text={
            counts.all
              ? 'جستجو یا فیلتر را تغییر دهید.'
              : 'بدون بسته هیچ اکانتی فروخته نمی‌شود. اولین بسته را بسازید، پنل‌ها و پکیج‌هایش را اضافه کنید.'
          }
        >
          {!counts.all && (
            <button className="btn" onClick={() => setDrawer('add')}>
              <Plus size={16} />
              ساخت اولین بسته
            </button>
          )}
        </Empty>
      ) : (
        <>
          {layout === 'table' ? (
            <GroupTable
              rows={shown}
              panelById={panelById}
              idx={idx}
              busy={busy}
              hasResellers={hasResellers}
              onEdit={(x) => setDrawer(x.id)}
              onToggle={toggle}
              onToggleReseller={toggleReseller}
              onDelete={remove}
            />
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {shown.map((g) => (
                <GroupCard
                  key={g.id}
                  g={g}
                  stat={idx.groupStat(g)}
                  products={idx.productsByGroup.get(g.id) || []}
                  busy={busy.has(g.id)}
                  hasResellers={hasResellers}
                  onEdit={(x) => setDrawer(x.id)}
                  onToggle={toggle}
                  onToggleReseller={toggleReseller}
                  onDelete={remove}
                />
              ))}
            </div>
          )}
          <Paginator page={page} setPage={setPage} total={filtered.length} pageSize={PAGE_SIZE} />
        </>
      )}
      {drawer && (drawer === 'add' || editing) && (
        <GroupDrawer
          key={drawer}
          group={editing}
          panels={panels}
          products={products}
          idx={idx}
          hasResellers={hasResellers}
          resellerStores={(storesQ.rows || []).filter((x) => x.kind === 'reseller')}
          call={call}
          toast={toast}
          onChanged={infra.reload}
          onClose={() => setDrawer(null)}
          onSubmit={save}
          onDelete={remove}
        />
      )}
    </div>
  );
}
