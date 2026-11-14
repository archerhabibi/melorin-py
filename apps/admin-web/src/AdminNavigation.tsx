import { label } from './ui.tsx';
import { sectionAllowed } from './adminAccess.ts';
import type { Permissions } from './adminAccess.ts';
import type { Json } from './types.ts';
import { groups } from './adminNav.ts';

export function Nav({
  section,
  go,
  openTickets,
  pendingApps,
  pendingPanelReq,
  manualTasks,
  perms,
}: {
  perms?: Permissions;
  section?: Json;
  go?: Json;
  openTickets?: Json;
  pendingApps?: Json;
  pendingPanelReq?: Json;
  manualTasks?: Json;
}) {
  return (
    <nav aria-label="منوی اصلی" className="space-y-5 px-3 pb-6">
      {groups
        .map(
          ([g, items, sub]) =>
            [g, items.filter(([name]) => sectionAllowed(perms, name)), sub] as (typeof groups)[number],
        )
        .filter(([, items]) => items.length)
        .map(([g, items, sub]) => (
          <div key={g}>
            <div className="mb-1.5 px-3 text-[11px] font-bold tracking-wide text-white/35">
              {g}
              {sub && <span className="mt-0.5 block text-[10px] font-normal tracking-normal text-white/25">{sub}</span>}
            </div>
            {items.map(([name, Icon]) => (
              <button
                key={name}
                onClick={() => go(name)}
                aria-current={section === name ? 'page' : undefined}
                className={`navb ${section === name ? 'on' : ''}`}
              >
                <Icon size={18} />
                <span>{name}</span>
                {name === 'تیکت‌ها' && openTickets > 0 && (
                  <span className="mr-auto rounded-full bg-[#e8743b] px-2 py-0.5 text-[10px] font-bold text-white">
                    {openTickets}
                  </span>
                )}
                {name === 'درخواست‌های نمایندگی' && pendingApps > 0 && (
                  <span className="mr-auto rounded-full bg-[#e8743b] px-2 py-0.5 text-[10px] font-bold text-white">
                    {pendingApps}
                  </span>
                )}
                {name === 'فروشگاه‌ها' && pendingPanelReq > 0 && (
                  <span className="mr-auto rounded-full bg-[#e8743b] px-2 py-0.5 text-[10px] font-bold text-white">
                    {pendingPanelReq}
                  </span>
                )}
                {name === 'کارهای دستی' && manualTasks > 0 && (
                  <span className="mr-auto rounded-full bg-[#e8743b] px-2 py-0.5 text-[10px] font-bold text-white">
                    {manualTasks}
                  </span>
                )}
              </button>
            ))}
          </div>
        ))}
    </nav>
  );
}
