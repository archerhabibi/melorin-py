import { Plus, RefreshCw, Server, ServerCog, ShieldAlert, ShieldCheck } from 'lucide-react';
import { KpiBar, SearchBox, SortSelect, Stat, ViewToggle, num } from '../../shared/kit.tsx';
import type { Json } from '../../shared/types.ts';

// KPI strip, search / filter / sort toolbar and the scope banner of the panels screen (pure move out of PanelsView).
export function PanelsToolbar({
  counts,
  cap,
  filter,
  setFilter,
  q,
  setQ,
  groups,
  groupF,
  setGroupF,
  sort,
  setSort,
  dense,
  setDense,
  bulk,
  checkAll,
  onAdd,
  hasScope,
  only,
  group,
  productObj,
  clearScope,
}: {
  counts: { all: number; healthy: number; attention: number };
  cap: { free: number; total: number };
  filter: string;
  setFilter: (v: string) => void;
  q: string;
  setQ: (v: string) => void;
  groups: Json[];
  groupF: string;
  setGroupF: (v: string) => void;
  sort: string;
  setSort: (v: string) => void;
  dense: string;
  setDense: (v: string) => void;
  bulk: Json;
  checkAll: () => void;
  onAdd: () => void;
  hasScope: boolean;
  only: string;
  group: Json;
  productObj: Json;
  clearScope: () => void;
}) {
  return (
    <>
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
        {!!groups.length && (
          <select
            aria-label="فیلتر بسته"
            className="inp !w-auto !py-2 !text-xs font-bold"
            value={groupF}
            onChange={(e) => setGroupF(e.target.value)}
          >
            <option value="">همه بسته‌ها</option>
            {groups.map((g) => (
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
          <button className="btn" onClick={() => onAdd()}>
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
    </>
  );
}
