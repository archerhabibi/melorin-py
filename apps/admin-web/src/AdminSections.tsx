import { Suspense } from 'react';
import { extraRoutes } from './AdminExtra.tsx';
import { sectionAllowed } from './adminAccess.ts';
import type { Json, Rec, Toast } from './types.ts';

function SectionFallback() {
  return (
    <div className="card p-6" role="status" aria-live="polite" aria-label="در حال بارگذاری بخش">
      <div className="skel h-5 w-full" />
      <div className="skel mt-3 h-5 w-2/3" />
    </div>
  );
}

/** Every section is a lazy view in ``extraRoutes`` (keyed by its Persian label); an unknown key shows the empty state. */
export function AdminSectionView({ section, api, toast }: { section?: Json; api?: Json; toast: Toast }) {
  // Permissions still loading: show the skeleton. A role that may not open the screen never mounts it (so it never fires its
  // API calls); App redirects it to the first screen it may open. The server stays the authority either way.
  if (api?.perms === undefined && api?.loading) return <SectionFallback />;
  if (api?.perms !== undefined && !sectionAllowed(api.perms, section)) return null;
  const Extra = (extraRoutes as Rec)[section];
  if (Extra)
    return (
      <Suspense fallback={<SectionFallback />}>
        <Extra api={api} toast={toast} />
      </Suspense>
    );
  return (
    <div className="rounded-2xl border border-[var(--ln)] bg-[var(--sf)] p-6 shadow-xs">
      <h3 className="font-extrabold">داده‌ای برای این بخش تعریف نشده</h3>
      <p className="mt-2 text-sm text-[var(--mu)]">از داشبورد یا API مرتبط استفاده کنید.</p>
    </div>
  );
}
