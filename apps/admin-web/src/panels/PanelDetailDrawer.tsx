import { useCallback, useState } from 'react';
import { Activity } from 'lucide-react';
import { Drawer } from '../kit.tsx';
import { authFetch } from '../api.ts';
import PanelNodesTab from '../PanelNodesTab.tsx';
import PanelConsoleTab from '../PanelConsoleTab.tsx';
import PanelEventsTab from '../PanelEventsTab.tsx';
import PanelCapacityTab from '../PanelCapacityTab.tsx';
import PanelTemplatesTab from '../PanelTemplatesTab.tsx';
import PanelPhase5Tab from '../PanelPhase5Tab.tsx';
import PanelAccessTab from '../PanelAccessTab.tsx';
import type { Toast } from '../types.ts';

export const DETAIL_TABS: [string, string][] = [
  ['nodes', 'نودها'],
  ['console', 'کنسول و اشتراک'],
  ['events', 'رویدادهای زنده'],
  ['capacity', 'ظرفیت و فروش'],
  ['templates', 'تمپلیت‌ها'],
  ['observe', 'شاخص و پشتیبان'],
  ['access', 'دسترسی'],
];

/** The panel-scoped tabs. ``panelId`` may be empty: each tab then shows its own "choose a panel" state. */
export function PanelDetailTabs({
  api,
  toast,
  panelId,
  panelName,
  tab: first,
}: {
  panelName?: string;
  api: { base: string };
  toast: Toast;
  panelId?: string;
  tab?: string | null;
}) {
  const call = useCallback((p: string, o?: RequestInit) => authFetch(api.base, p, o), [api.base]);
  const [tab, setTab] = useState(DETAIL_TABS.some(([k]) => k === first) ? (first as string) : 'nodes');
  return (
    <>
      <div className="flex flex-wrap gap-2 pb-3">
        {DETAIL_TABS.map(([key, text]) => (
          <button key={key} className={`btn ${tab === key ? '' : 'btn-g'}`} onClick={() => setTab(key)}>
            {text}
          </button>
        ))}
      </div>
      {tab === 'nodes' && <PanelNodesTab call={call} panelId={panelId} toast={toast} />}
      {tab === 'console' && <PanelConsoleTab call={call} panelId={panelId} toast={toast} />}
      {tab === 'events' && <PanelEventsTab call={call} panelId={panelId} toast={toast} />}
      {tab === 'capacity' && <PanelCapacityTab call={call} panelId={panelId} toast={toast} />}
      {tab === 'templates' && <PanelTemplatesTab call={call} panelId={panelId} toast={toast} />}
      {tab === 'observe' && <PanelPhase5Tab call={call} panelId={panelId} toast={toast} />}
      {tab === 'access' && <PanelAccessTab call={call} panelId={panelId} panelName={panelName} toast={toast} />}
    </>
  );
}

/** Everything an admin does TO one panel, as tabs of that panel (was the panel-ops screen with a panel selector). */
export function PanelDetailDrawer({
  api,
  toast,
  panel,
  tab,
  onClose,
}: {
  api: { base: string };
  toast: Toast;
  panel: { id: string; name: string };
  tab?: string | null;
  onClose: () => void;
}) {
  return (
    <Drawer title={panel.name} subtitle="عملیات پنل" icon={<Activity size={18} />} onClose={onClose}>
      <PanelDetailTabs api={api} toast={toast} panelId={panel.id} panelName={panel.name} tab={tab} />
    </Drawer>
  );
}
