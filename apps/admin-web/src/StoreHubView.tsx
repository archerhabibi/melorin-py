// «فروشگاه‌ها» — the store hub: everything about a store (and its reseller) behind one menu entry, four tabs:
//   stores    «فروشگاه‌ها»       the list of stores
//   resellers «نمایندگان»        reseller accounts of those stores
//   panels    «دسترسی پنل»       panel operators (PanelAdmin) and sub branding, per store x panel
//   volume    «حجم و سیاست»      store volume governance and the suspend policy
// Each tab keeps its own permission area (SECTION_AREA of the section it came from), so a role sees only what it may open.
// Deep link: #/stores?tab=resellers (old #/resellers, #/panel-admins and #/store-governance are rewritten by legacyHash).
import type { LazyExoticComponent, ReactNode } from 'react';
import { lazy, Suspense, useState } from 'react';
import { sectionAllowed } from './adminAccess.ts';
import { Segmented } from './kit.tsx';
import type { Toast } from './types.ts';

/** The slice of the app-shell api the hub itself reads; the tab views get the whole object. */
interface HubApi {
  base?: string;
  perms?: string[];
  pendingPanelReq?: number;
}

const StoresView = lazy(() => import('./StoresView.tsx'));
const ResellersView = lazy(() => import('./ResellersView.tsx'));
const PanelAdminsView = lazy(() => import('./PanelAdminsView.tsx'));
const StoreGovernanceView = lazy(() => import('./StoreGovernanceView.tsx'));

type HubView = LazyExoticComponent<(p: { api?: HubApi; toast: Toast }) => ReactNode>;
// tab id -> [label, section key used for the permission check, component]
const TAB_DEFS: [string, string, string, HubView][] = [
  ['stores', 'فروشگاه‌ها', 'فروشگاه‌ها', StoresView],
  ['resellers', 'نمایندگان', 'نمایندگان', ResellersView],
  ['panels', 'دسترسی پنل', 'ادمین‌های پنل', PanelAdminsView],
  ['volume', 'حجم و سیاست', 'حجم فروشگاه‌ها', StoreGovernanceView],
];

const tabFromHash = (ids: string[]) => {
  const q = typeof window === 'undefined' ? '' : window.location.hash.split('?')[1] || '';
  const t = new URLSearchParams(q).get('tab') ?? '';
  return ids.includes(t) ? t : ids[0];
};

export default function StoreHubView({ api, toast }: { api?: HubApi; toast: Toast }) {
  const tabs = TAB_DEFS.filter(([, , section]) => sectionAllowed(api?.perms, section));
  const ids = tabs.map(([id]) => id);
  const [tab, setTab] = useState(() => tabFromHash(ids));
  const pick = (v: string) => {
    setTab(v);
    // replaceState: switching tabs adds no history entry
    window.history.replaceState(
      null,
      '',
      `${window.location.pathname}${window.location.search}#/stores${v === ids[0] ? '' : `?tab=${v}`}`,
    );
  };
  const active = tabs.find(([id]) => id === tab) ?? tabs[0];
  if (!active) return null;
  const View = active[3];
  return (
    <div className="space-y-5">
      <Segmented
        label="بخش فروشگاه"
        value={active[0]}
        onChange={pick}
        options={tabs.map(([id, label]) => [
          id,
          <>
            {label}
            {id === 'panels' && (api?.pendingPanelReq ?? 0) > 0 && <b className="num mr-1">{api?.pendingPanelReq}</b>}
          </>,
        ])}
      />
      <Suspense fallback={<div className="skel h-44" />}>
        <View key={active[0]} api={api} toast={toast} />
      </Suspense>
    </div>
  );
}
