import { health, serverState, free } from '../panel-operations/infra.tsx';
import { kindOf } from './panelUi.tsx';
import type { Json, Rec } from '../../shared/types.ts';

type Row = Json;
type Dict = Rec;

/** A panel needs attention when it is enabled but not healthy. */
export const attention = (p: Row) => p.is_enabled && health(p) !== 'healthy';

export function countPanels(rows: Row[]) {
  const c = { all: 0, healthy: 0, attention: 0 };
  rows.forEach((p) => {
    c.all++;
    if (health(p) === 'healthy') c.healthy++;
    if (attention(p)) c.attention++;
  });
  return c;
}

export function capacityOf(allServers: Row[], idx: Row) {
  let freeN = 0,
    total = 0;
  allServers.forEach((s) => {
    total += s.capacity || 0;
    if (serverState(s, idx.panelById.get(s.panel_id)).ok) freeN += free(s);
  });
  return { free: freeN, total };
}

export function filterPanels(
  rows: Row[],
  f: { filter: string; q: string; only: string; groupPanels: Set<unknown> | null; productPanels: Set<unknown> | null },
  idx: Row,
) {
  const needle = f.q.trim().toLowerCase();
  return rows.filter(
    (p) =>
      (!f.only || p.id === f.only) &&
      (f.filter === 'all' || (f.filter === 'healthy' ? health(p) === 'healthy' : attention(p))) &&
      (!f.groupPanels || f.groupPanels.has(p.id)) &&
      (!f.productPanels || f.productPanels.has(p.id)) &&
      `${p.name} ${p.base_url} ${kindOf(p.kind).title} ${(idx.serversByPanel.get(p.id) || []).map((s: Row) => `${s.name} ${s.location || ''}`).join(' ')}`
        .toLowerCase()
        .includes(needle),
  );
}

export function sortPanels(filtered: Row[], sort: string, idx: Row) {
  const rank = (p: Row) =>
    !p.is_enabled ? 4 : health(p) === 'unhealthy' ? 0 : health(p) === 'degraded' ? 1 : health(p) === 'unknown' ? 2 : 3;
  const by: Dict = {
    attention: (a: Row, b: Row) => rank(a) - rank(b) || a.name.localeCompare(b.name, 'fa'),
    name: (a: Row, b: Row) => a.name.localeCompare(b.name, 'fa'),
    free: (a: Row, b: Row) =>
      idx.panelStat(b.id).capacity -
      idx.panelStat(b.id).active -
      (idx.panelStat(a.id).capacity - idx.panelStat(a.id).active),
    usage: (a: Row, b: Row) => {
      const f = (p: Row) => {
        const x = idx.panelStat(p.id);
        return x.capacity ? x.active / x.capacity : 0;
      };
      return f(b) - f(a);
    },
  };
  return [...filtered].sort(by[sort]);
}
