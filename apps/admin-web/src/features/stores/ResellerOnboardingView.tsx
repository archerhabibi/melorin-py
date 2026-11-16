// «درخواست‌های نمایندگی» — the reseller onboarding desk, two tabs (audit 5.2: manual tasks are part of onboarding, not a menu of their own):
//   applications «درخواست‌ها»        the review queue: approve (creates the store) or reject
//   tasks        «اقدامات تکمیلی»    what a human must still do outside Melorin after sign-up (Google, Telegram, domain)
import { lazy, Suspense, useEffect, useState } from 'react';
import { getJson } from '../../api/api.ts';
import { Segmented, num } from '../../shared/kit.tsx';
import { can } from '../../app/adminAccess.ts';
import type { Toast, ViewApi } from '../../shared/types.ts';

const ResellerApplicationsView = lazy(() => import('../resellers/ResellerApplicationsView.tsx'));
const ManualTasksView = lazy(() => import('../resellers/ManualTasksView.tsx'));

const TABS = ['applications', 'tasks'];
const tabFromHash = () => {
  const q = typeof window === 'undefined' ? '' : window.location.hash.split('?')[1] || '';
  const t = new URLSearchParams(q).get('tab');
  return TABS.includes(t ?? '') ? (t as string) : 'applications';
};

export default function ResellerOnboardingView({ api, toast }: { api: ViewApi; toast: Toast }) {
  // The server decides every request; this only hides a tab the role could not use (manual tasks sit in the «customers» area).
  const perms = api.me?.permissions;
  const tasksAllowed = can(perms, 'customers');
  const [tab, setTab] = useState(() => (tabFromHash() === 'tasks' && !tasksAllowed ? 'applications' : tabFromHash()));
  const [open, setOpen] = useState(0); // manual tasks still waiting for a human (badge on the second tab)
  useEffect(() => {
    if (!tasksAllowed) return;
    let alive = true;
    getJson<{ open?: number }>(api.base, '/api/v1/admin/manual-tasks?status=open')
      .then((x) => alive && setOpen(x?.open || 0))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [api.base, tab, tasksAllowed]);
  const pick = (v: string) => {
    setTab(v);
    // deep link: #/reseller-applications?tab=tasks (replaceState: switching tabs adds no history entry)
    window.history.replaceState(
      null,
      '',
      `${window.location.pathname}${window.location.search}#/reseller-applications${v === 'applications' ? '' : `?tab=${v}`}`,
    );
  };
  return (
    <div className="space-y-5">
      {tasksAllowed && (
        <Segmented
          label="بخش درخواست‌های نمایندگی"
          value={tab}
          onChange={pick}
          options={[
            ['applications', 'درخواست‌ها'],
            ['tasks', <>اقدامات تکمیلی {open > 0 && <b className="num">{num(open)}</b>}</>],
          ]}
        />
      )}
      <Suspense fallback={<div className="skel h-44" />}>
        {tab === 'applications' && <ResellerApplicationsView api={api} toast={toast} />}
        {tab === 'tasks' && tasksAllowed && <ManualTasksView api={api} toast={toast} />}
      </Suspense>
    </div>
  );
}
