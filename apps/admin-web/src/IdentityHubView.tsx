// «هویت» — one screen for everything about identity (docs/21), three tabs:
//   review  «نیاز به بررسی»      conflicts Core could not settle: an admin decides (IdentityReviewsView)
//   auto    «انجام‌شده خودکار»   accounts Core folded together by itself (read-only report)
//   devices «دستگاه‌های مورداعتماد» browsers that sign visitors in without a manual step; trust can be revoked
import { lazy, Suspense, useEffect, useState } from 'react';
import { authFetch } from './api.ts';
import { Segmented, num } from './kit.tsx';
import type { Json, Toast } from './types.ts';

const IdentityReviewsView = lazy(() => import('./IdentityReviewsView.tsx'));
const IdentityAutoView = lazy(() => import('./IdentityAutoView.tsx'));

const GoogleLoginSettings = lazy(() => import('./GoogleLoginSettings.tsx'));
const TelegramLoginSettings = lazy(() => import('./TelegramLoginSettings.tsx'));

const TABS = ['review', 'auto', 'devices', 'login'];
const tabFromHash = () => {
  const q = typeof window === 'undefined' ? '' : window.location.hash.split('?')[1] || '';
  const t = new URLSearchParams(q).get('tab');
  return TABS.includes(t ?? '') ? t : 'review';
};

export default function IdentityHubView({ api, toast }: { api?: Json; toast: Toast }) {
  const [tab, setTab] = useState(tabFromHash);
  const [open, setOpen] = useState<Json>(null); // number of conflicts waiting for a decision (badge on the first tab)
  useEffect(() => {
    let alive = true;
    authFetch(api.base, '/api/v1/admin/identity-link-reviews?status=open')
      .then((r) => (r.ok ? r.json() : []))
      .then((rows) => alive && setOpen((rows || []).filter((x: Json) => !x.auto).length))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [api.base, tab]);
  const pick = (v: Json) => {
    setTab(v);
    // deep link: #/identity?tab=auto (replaceState: switching tabs adds no history entry)
    window.history.replaceState(
      null,
      '',
      `${window.location.pathname}${window.location.search}#/identity${v === 'review' ? '' : `?tab=${v}`}`,
    );
  };
  return (
    <div className="space-y-5">
      <Segmented
        label="بخش هویت"
        value={tab}
        onChange={pick}
        options={[
          ['review', <>نیاز به بررسی {open > 0 && <b className="num">{num(open)}</b>}</>],
          ['auto', 'انجام‌شده خودکار'],
          ['devices', 'دستگاه‌های مورداعتماد'],
          ['login', 'روش‌های ورود'], // Google / Telegram sign-in: an identity topic, not a system setting
        ]}
      />
      <Suspense fallback={<div className="skel h-44" />}>
        {tab === 'review' && <IdentityReviewsView api={api} toast={toast} />}
        {tab === 'auto' && <IdentityAutoView key="merges" api={api} toast={toast} section="merges" />}
        {tab === 'devices' && <IdentityAutoView key="devices" api={api} toast={toast} section="devices" />}
        {tab === 'login' && (
          <div className="space-y-5">
            <GoogleLoginSettings api={api} toast={toast} />
            <TelegramLoginSettings api={api} toast={toast} />
          </div>
        )}
      </Suspense>
    </div>
  );
}
