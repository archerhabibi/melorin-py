import { ServerForm } from './ServerForm.tsx';
import { ServerImport } from './ServerImport.tsx';
import { TargetWizard } from './TargetPicker.tsx';
import { PanelDrawer } from './PanelDrawer.tsx';
import { PanelDetailDrawer } from './PanelDetailDrawer.tsx';
import type { Json } from '../../shared/types.ts';

export function PanelsOverlays({
  api,
  toast,
  infra,
  idx,
  drawer,
  setDrawer,
  editing,
  busy,
  save,
  toggle,
  removePanel,
  detailFor,
  setDetailFor,
  srvDrawer,
  setSrvDrawer,
  srvPanel,
  srvEditing,
  locations,
  srvBusy,
  srvToggle,
  removeServer,
  wizardFor,
  setWizardFor,
  importFor,
  setImportFor,
}: Record<string, any>) {
  return (
    <>
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
    </>
  );
}
