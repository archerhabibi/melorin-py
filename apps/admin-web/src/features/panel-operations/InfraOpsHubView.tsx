// «عملیات مدیریتی» - one screen for what an admin DOES to the panels (architecture audit 5.6), two tabs:
//   ops   «عملیات پنل»     console, access, events, backup, reconciliation of one panel (PanelOpsView)
//   bulk  «عملیات گروهی»   preview -> exact-count confirm -> resumable run over many accounts of one panel (BulkOperationsView)
// Both stay behind the `infrastructure` permission. Deep links: #/panel-ops (ops), #/panel-ops?tab=bulk.
import { lazy, Suspense, useState } from 'react';
import { Segmented } from '../../shared/kit.tsx';
import type { Json, Toast } from '../../shared/types.ts';

const PanelOpsView = lazy(() => import('./PanelOpsView.tsx'));
const BulkOperationsView = lazy(() => import('./BulkOperationsView.tsx'));

const TABS = ['ops', 'bulk'];
const tabFromHash = () => {
  const q = typeof window === 'undefined' ? '' : window.location.hash.split('?')[1] || '';
  const t = new URLSearchParams(q).get('tab');
  return TABS.includes(t ?? '') ? (t as string) : 'ops';
};

export default function InfraOpsHubView({ api, toast }: { api?: Json; toast: Toast }) {
  const [tab, setTab] = useState(tabFromHash);
  const pick = (v: string) => {
    setTab(v);
    // replaceState: switching tabs adds no history entry; a panel deep link (?panel=) belongs to the ops tab only
    window.history.replaceState(
      null,
      '',
      `${window.location.pathname}${window.location.search}#/panel-ops${v === 'ops' ? '' : `?tab=${v}`}`,
    );
  };
  return (
    <div className="space-y-5">
      <Segmented
        label="بخش عملیات مدیریتی"
        value={tab}
        onChange={pick}
        options={[
          ['ops', 'عملیات پنل'],
          ['bulk', 'عملیات گروهی'],
        ]}
      />
      <Suspense fallback={<div className="skel h-44" />}>
        {tab === 'ops' && <PanelOpsView api={api} toast={toast} />}
        {tab === 'bulk' && <BulkOperationsView api={api} toast={toast} />}
      </Suspense>
    </div>
  );
}
