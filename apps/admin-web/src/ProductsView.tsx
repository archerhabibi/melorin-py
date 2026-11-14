import { useEffect, useMemo, useState } from 'react';
import { confirmDialog } from './ui.tsx';
import { AlertTriangle, Boxes, CheckCircle2, PowerOff, Plus, Save, ShieldAlert, Tag, Wallet, X } from 'lucide-react';
import { asList } from './adminHubTypes.ts';
import type { StoreRow } from './adminHubTypes.ts';
import type { Json, Rec, Toast } from './types.ts';
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
  useRows,
} from './kit.tsx'; // #4
import { InfraChain, clearParam, useHashParams, useInfra } from './infra.tsx';

import { API } from './productsShared.tsx';
import { ProductDrawer, ProductCard, ProductTable } from './ProductParts.tsx';

export default function ProductsView({ api, toast }: { api?: Json; toast: Toast }) {
  const infra = useInfra(api);
  const { call, idx } = infra;
  const prods = infra.products,
    storesQ = useRows(call, '/api/v1/admin/stores');
  const params = useHashParams();
  const [q, setQ] = useState(params.get('q') || '');
  // #4 Pagination
  const PAGE_SIZE = 20;
  const [page, setPage] = useState(0);
  useEffect(() => {
    setPage(0);
  }, [q]);
  const [filter, setFilter] = useState(
      ['on', 'off', 'broken', 'test'].includes(params.get('filter') ?? '') ? params.get('filter') : 'all',
    ),
    [layout, setLayout] = useState('grid'),
    [sort, setSort] = useState('attention'),
    [drawer, setDrawer] = useState<Json>(null),
    [busy, setBusy] = useState(new Set());
  const [quick, setQuick] = useState(false),
    [draft, setDraft] = useState<Rec>({}),
    [saving, setSaving] = useState(false);
  const alive = useAlive();
  const rows = prods.rows;
  const hasResellers = (storesQ.rows || []).some((s) => s.kind === 'reseller'); // no resellers yet = no cooperation switches at all
  useEffect(() => {
    setQ(params.get('q') || '');
    if (params.get('filter'))
      setFilter(['on', 'off', 'broken', 'test'].includes(params.get('filter') ?? '') ? params.get('filter') : 'all');
    if (params.get('add') === '1') {
      setDrawer('add');
      clearParam('add');
    }
  }, [params]);
  const counts = useMemo(() => {
    const c = { all: 0, on: 0, off: 0, test: 0, broken: 0 };
    (rows || []).forEach((p) => {
      c.all++;
      p.is_active ? c.on++ : c.off++;
      if (p.is_test) c.test++;
      if (p.is_active && !idx.reach(p).ok) c.broken++;
    });
    return c;
  }, [rows, idx]);
  const shown = useMemo(
    () =>
      (rows || []).filter(
        (p) =>
          (filter === 'all' ||
            (filter === 'on'
              ? p.is_active
              : filter === 'off'
                ? !p.is_active
                : filter === 'broken'
                  ? p.is_active && !idx.reach(p).ok
                  : p.is_test)) &&
          `${p.name} ${p.code} ${p.category || ''}`.toLowerCase().includes(q.trim().toLowerCase()),
      ),
    [rows, filter, q, idx],
  );
  const ordered = useMemo(() => {
    const by: Rec = {
      attention: (a: Json, b: Json) =>
        Number(b.is_active && !idx.reach(b).ok) - Number(a.is_active && !idx.reach(a).ok) ||
        Number(b.is_active) - Number(a.is_active) ||
        a.duration_days - b.duration_days ||
        a.main_price - b.main_price,
      price: (a: Json, b: Json) => a.main_price - b.main_price,
      price_desc: (a: Json, b: Json) => b.main_price - a.main_price,
      duration: (a: Json, b: Json) => a.duration_days - b.duration_days || a.main_price - b.main_price,
      traffic: (a: Json, b: Json) => (a.traffic_gb || 1e9) - (b.traffic_gb || 1e9),
      name: (a: Json, b: Json) => a.name.localeCompare(b.name, 'fa'),
    };
    return [...shown].sort(by[sort]);
  }, [shown, sort, idx]);
  const editing = drawer && drawer !== 'add' ? (rows || []).find((p) => p.id === drawer) : null;
  const table = layout === 'table' || quick;

  const save = async (body: Json, active: Json, product: Json) => {
    const r = await call(product ? `${API}/${product.id}` : API, {
      method: product ? 'PATCH' : 'POST',
      body: JSON.stringify(product ? { ...body, is_active: active } : body),
    });
    if (!r.ok) return errText(r, product ? 'ذخیره تغییرات ناموفق بود' : 'ساخت محصول ناموفق بود');
    if (!product && !active) {
      const c = await r.json().catch(() => null);
      if (c?.id) await call(`${API}/${c.id}`, { method: 'PATCH', body: JSON.stringify({ is_active: false }) });
    }
    setDrawer(null);
    toast(product ? 'تغییرات محصول ذخیره شد' : 'محصول ساخته شد');
    await infra.reload();
    return '';
  };
  const toggle = async (p: Json, next: Json) => {
    if (
      !next &&
      !(await confirmDialog(
        `«${p.name}» غیرفعال شود؟ دیگر برای خرید جدید نمایش داده نمی‌شود${hasResellers ? ' و برای نمایندگان هم غیرفعال می‌شود' : ''}.`,
        { title: 'غیرفعال‌سازی محصول', danger: true, ok: 'غیرفعال‌سازی' },
      ))
    )
      return;
    setBusy((s) => new Set(s).add(p.id));
    let ok = false;
    try {
      ok = (await call(`${API}/${p.id}`, { method: 'PATCH', body: JSON.stringify({ is_active: next }) })).ok;
    } catch {
      /* network */
    }
    if (alive.current)
      setBusy((s) => {
        const n = new Set(s);
        n.delete(p.id);
        return n;
      });
    toast(ok ? (next ? `«${p.name}» فعال شد` : `«${p.name}» غیرفعال شد`) : 'تغییر وضعیت ناموفق بود');
    if (ok) await infra.reload();
  };
  const toggleReseller = async (p: Json, next: Json) => {
    setBusy((s) => new Set(s).add(p.id));
    let ok = false;
    try {
      ok = (await call(`${API}/${p.id}`, { method: 'PATCH', body: JSON.stringify({ reseller_enabled: next }) })).ok;
    } catch {
      /* network */
    }
    if (alive.current)
      setBusy((s) => {
        const n = new Set(s);
        n.delete(p.id);
        return n;
      });
    toast(
      ok
        ? next
          ? `«${p.name}» برای نمایندگان فعال شد`
          : `«${p.name}» برای نمایندگان غیرفعال شد`
        : 'تغییر وضعیت ناموفق بود',
    );
    if (ok) await infra.reload();
  };
  const remove = async (p: Json) => {
    setBusy((s) => new Set(s).add(p.id));
    const ok = await removeEntity(call, `${API}/${p.id}`, {
      toast,
      title: 'حذف محصول',
      done: `«${p.name}» حذف شد`,
      message: `«${p.name}» برای همیشه حذف شود؟ این کار قابل بازگشت نیست. اگر برای این محصول سفارش یا اکانتی ثبت شده باشد حذف انجام نمی‌شود و باید آن را غیرفعال کنید.`,
    });
    if (alive.current)
      setBusy((s) => {
        const n = new Set(s);
        n.delete(p.id);
        return n;
      });
    if (ok) {
      setDrawer(null);
      await infra.reload();
    }
  };
  const changes = (rows || []).flatMap((p) => {
    const d = draft[p.id];
    if (!d || d.main_price === undefined || d.main_price === '' || d.main_price === String(p.main_price)) return [];
    return [[p, { main_price: +d.main_price }]];
  });
  const endQuick = async () => {
    if (
      changes.length &&
      !(await confirmDialog('تغییرات قیمت ذخیره‌نشده از بین می‌رود. خارج می‌شوید؟', {
        title: 'خروج از ویرایش سریع',
        danger: true,
        ok: 'خروج',
      }))
    )
      return;
    setDraft({});
    setQuick(false);
  };
  const saveQuick = async () => {
    if (
      !(await confirmDialog(
        `قیمت ${num(changes.length)} محصول به‌روزرسانی شود؟ قیمت جدید فوراً در فروشگاه اعمال می‌شود.`,
        { title: 'ذخیره‌ی قیمت‌ها', ok: 'ذخیره' },
      ))
    )
      return;
    setSaving(true);
    let bad = 0;
    for (const [p, b] of changes) {
      try {
        if (!(await call(`${API}/${p.id}`, { method: 'PATCH', body: JSON.stringify(b) })).ok) bad++;
      } catch {
        bad++;
      }
    }
    if (alive.current) setSaving(false);
    toast(bad ? `${num(bad)} مورد از ${num(changes.length)} ذخیره نشد` : 'قیمت‌ها به‌روزرسانی شد');
    await infra.reload();
    if (!bad) {
      setDraft({});
      setQuick(false);
    }
  };

  return (
    <div className="space-y-5">
      <InfraChain current="products" infra={infra} />
      <KpiBar cols={5}>
        <Stat
          label="همه محصولات"
          value={counts.all}
          tone="in"
          Icon={Boxes}
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
          Icon={PowerOff}
          active={filter === 'off'}
          onClick={() => setFilter(filter === 'off' ? 'all' : 'off')}
        />
        <Stat
          label="بدون مسیر تخصیص"
          value={counts.broken}
          tone={counts.broken ? 'bd' : 'mu'}
          Icon={AlertTriangle}
          active={filter === 'broken'}
          onClick={() => setFilter(filter === 'broken' ? 'all' : 'broken')}
        />
        <Stat
          label="آزمایشی"
          value={counts.test}
          tone="wn"
          Icon={Tag}
          active={filter === 'test'}
          onClick={() => setFilter(filter === 'test' ? 'all' : 'test')}
        />
      </KpiBar>
      <div className="tool">
        <SearchBox label="جستجوی محصول" placeholder="جستجوی نام، کد یا دسته…" value={q} onChange={setQ} />
        <SortSelect
          value={sort}
          onChange={setSort}
          options={[
            ['attention', 'مشکل‌دارها اول'],
            ['price', 'ارزان‌ترین'],
            ['price_desc', 'گران‌ترین'],
            ['duration', 'کم‌ترین مدت'],
            ['traffic', 'کم‌ترین حجم'],
            ['name', 'نام'],
          ]}
        />
        <ViewToggle
          value={table ? 'table' : 'grid'}
          onChange={setLayout}
          disabled={quick}
          options={[
            ['grid', 'کارتی'],
            ['table', 'جدولی'],
          ]}
        />
        <div className="mr-auto flex flex-wrap items-center gap-2">
          {quick ? (
            <>
              <span className="text-xs text-[var(--mu)]">
                {changes.length ? `${num(changes.length)} تغییر` : 'قیمت فروشگاه را مستقیم در جدول ویرایش کنید'}
              </span>
              <button className="btn !py-2 !text-sm" disabled={!changes.length || saving} onClick={saveQuick}>
                <Save size={14} />
                {saving ? 'در حال ذخیره…' : 'ذخیره قیمت‌ها'}
              </button>
              <button className="btn btn-g !py-2 !text-sm" disabled={saving} onClick={endQuick}>
                <X size={14} />
                خروج
              </button>
            </>
          ) : (
            <>
              <button
                className="btn btn-g !py-2 !text-sm"
                disabled={!counts.all}
                onClick={() => {
                  setLayout('table');
                  setQuick(true);
                }}
              >
                <Wallet size={14} />
                ویرایش سریع قیمت‌ها
              </button>
              <button className="btn" onClick={() => setDrawer('add')}>
                <Plus size={16} />
                افزودن محصول
              </button>
            </>
          )}
        </div>
      </div>
      {prods.failed && (
        <ErrorBar onRetry={prods.load}>
          <ShieldAlert size={16} />
          دریافت محصولات ناموفق بود.
        </ErrorBar>
      )}
      {rows === null || infra.loading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card skel h-80" />
          ))}
        </div>
      ) : !ordered.length ? (
        <Empty
          Icon={Boxes}
          title={counts.all ? 'محصولی با این فیلتر پیدا نشد' : 'هنوز محصولی تعریف نشده'}
          text={
            counts.all
              ? 'جستجو یا فیلتر را تغییر دهید.'
              : 'هر محصول یک پلن قابل فروش با مدت، حجم و قیمت مشخص است. ابتدا باید حداقل یک پنل سالم با سرور داشته باشید.'
          }
        >
          {!counts.all && (
            <button className="btn" onClick={() => setDrawer('add')}>
              <Plus size={16} />
              ساخت اولین محصول
            </button>
          )}
        </Empty>
      ) : table ? (
        <ProductTable
          idx={idx}
          rows={ordered}
          busy={busy}
          hasResellers={hasResellers}
          onEdit={(x: Json) => setDrawer(x.id)}
          onToggle={toggle}
          onToggleReseller={toggleReseller}
          onDelete={remove}
          quick={quick}
          draft={draft}
          setDraft={setDraft}
        />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {ordered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE).map((p) => (
              <ProductCard
                key={p.id}
                p={p}
                idx={idx}
                busy={busy.has(p.id)}
                hasResellers={hasResellers}
                onEdit={(x: Json) => setDrawer(x.id)}
                onToggle={toggle}
                onToggleReseller={toggleReseller}
                onDelete={remove}
              />
            ))}
          </div>
          <Paginator page={page} setPage={setPage} total={ordered.length} pageSize={PAGE_SIZE} />
        </>
      )}
      {drawer && (drawer === 'add' || editing) && (
        <ProductDrawer
          key={drawer}
          product={editing}
          products={rows || []}
          hasResellers={hasResellers}
          call={call}
          stores={asList<StoreRow>(storesQ.rows)}
          toast={toast}
          onClose={() => setDrawer(null)}
          onSubmit={save}
          onDelete={remove}
        />
      )}
    </div>
  );
}
