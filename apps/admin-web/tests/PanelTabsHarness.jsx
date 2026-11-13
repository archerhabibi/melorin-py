import { useEffect, useState } from 'react';
import { PanelDetailTabs } from '../src/panels/PanelDetailDrawer.tsx';

/** Test-only stand-in for the former panel-ops screen: a panel selector above the panel-scoped tabs. */
export default function PanelOpsView({ api, toast }) {
  const [panels, setPanels] = useState([]);
  const [panelId, setPanelId] = useState('');
  useEffect(() => {
    fetch(`${api.base}/api/v1/admin/panels`)
      .then((r) => r.json())
      .then(setPanels);
  }, [api.base]);
  return (
    <>
      <select aria-label="پنل" value={panelId} onChange={(e) => setPanelId(e.target.value)}>
        <option value="">همهٔ پنل‌ها</option>
        {panels.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
      <PanelDetailTabs api={api} toast={toast} panelId={panelId} />
    </>
  );
}
