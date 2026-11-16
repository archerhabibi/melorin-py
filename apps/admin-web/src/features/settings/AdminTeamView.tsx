import { useMemo, useState } from 'react';
import { Mail, ShieldCheck, ShieldOff, UserCog, UserPlus, Users } from 'lucide-react';
import { Empty, ErrorBar, KpiBar, Pills, SearchBox, Stat, useRows } from '../../shared/kit.tsx';
import { Avatar, Cell2, DataGrid, ScreenHead, Toolbar, When, matches, useCall } from '../../shared/dataKit.tsx';
import { ROLE_TONE } from '../../app/adminAccess.ts';
import { AdminMember, AdminRoleInfo, Toast, ViewApi } from '../../shared/types.ts';
import { BASE, RoleBadge, StateBadge, RoleGuide, InviteDrawer, AdminDrawer } from './AdminTeamParts.tsx';

export default function AdminTeamView({ api, toast }: { api: ViewApi; toast: Toast }) {
  const call = useCall(api);
  const admins = useRows<AdminMember>(call, BASE);
  const roles = useRows<AdminRoleInfo>(call, `${BASE}/roles`);
  const [filter, setFilter] = useState('all');
  const [q, setQ] = useState('');
  const [selId, setSelId] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);

  const loading = admins.rows === null;
  const all = useMemo(() => admins.rows || [], [admins.rows]);
  const count = (s: string) => all.filter((a) => a.state === s).length;
  const rows = all.filter(
    (a) => (filter === 'all' || a.state === filter) && matches(q, a.email, a.display_name, a.role_label),
  );
  const selected = all.find((a) => a.id === selId) || null;
  const roleList = roles.rows || [];

  return (
    <div className="space-y-5">
      <ScreenHead
        title="تیم مدیریت"
        hint="چه کسانی وارد این پنل می‌شوند و هرکدام چه کاری می‌توانند بکنند. ادمین جدید با لینک دعوت یک‌بارمصرف خودش رمز و TOTP می‌سازد."
        count={loading ? null : all.length}
        onRefresh={() => {
          admins.load();
          roles.load();
        }}
        busy={loading}
      >
        <button className="btn !py-2" onClick={() => setInviting(true)} disabled={!roleList.length}>
          <UserPlus size={16} />
          دعوت ادمین
        </button>
      </ScreenHead>

      {admins.failed && <ErrorBar onRetry={admins.load}>دریافت فهرست ادمین‌ها ناموفق بود.</ErrorBar>}

      <KpiBar cols={4}>
        <Stat label="همه‌ی ادمین‌ها" value={loading ? null : all.length} tone="in" Icon={Users} />
        <Stat label="فعال" value={loading ? null : count('active')} tone="ok" Icon={ShieldCheck} />
        <Stat
          label="در انتظار پذیرش"
          value={loading ? null : count('invited') + count('invite_expired')}
          tone="wn"
          Icon={Mail}
        />
        <Stat label="معلق" value={loading ? null : count('suspended')} tone="mu" Icon={ShieldOff} />
      </KpiBar>

      <Toolbar>
        <SearchBox value={q} onChange={setQ} placeholder="جستجوی ایمیل، نام یا نقش…" />
        <Pills
          label="وضعیت"
          value={filter}
          onChange={setFilter}
          options={[
            ['all', 'همه', all.length],
            ['active', 'فعال', count('active')],
            ['invited', 'دعوت‌شده', count('invited')],
            ['invite_expired', 'دعوت منقضی', count('invite_expired'), { warn: true }],
            ['suspended', 'معلق', count('suspended')],
          ]}
        />
      </Toolbar>

      <DataGrid
        caption="فهرست ادمین‌ها"
        loading={loading}
        rows={rows}
        minWidth={720}
        onRowClick={(a: AdminMember) => setSelId(a.id)}
        columns={[
          {
            key: 'who',
            label: 'ادمین',
            m: 'title',
            render: (a: AdminMember) => (
              <span className="flex items-center gap-3">
                <Avatar name={a.display_name || a.email} tone={ROLE_TONE[a.role ?? ''] || 'mu'} />
                <Cell2 main={a.display_name || a.email} sub={a.display_name ? a.email : null} dir="auto" />
              </span>
            ),
          },
          {
            key: 'role',
            label: 'نقش',
            m: 'head',
            render: (a: AdminMember) => <RoleBadge role={a.role} label={a.role_label} />,
          },
          {
            key: 'state',
            label: 'وضعیت',
            render: (a: AdminMember) => (
              <span className="flex flex-wrap items-center gap-1.5">
                <StateBadge state={a.state} />
                {a.is_self && <span className="badge b-in">شما</span>}
              </span>
            ),
          },
          {
            key: 'login',
            label: 'آخرین ورود',
            render: (a: AdminMember) =>
              a.last_login_at ? <When v={a.last_login_at} /> : <span className="text-[var(--mu)]">—</span>,
          },
        ]}
        emptyNode={
          <Empty
            Icon={UserCog}
            title={q || filter !== 'all' ? 'موردی پیدا نشد' : 'هنوز ادمین دیگری ندارید'}
            text={
              q || filter !== 'all'
                ? 'جستجو یا فیلتر را تغییر دهید.'
                : 'با «دعوت ادمین» همکارتان را با نقشی محدود به پنل اضافه کنید.'
            }
          />
        }
      />

      <section className="card rise p-5">
        <h3 className="mb-1 font-extrabold">نقش‌ها چه دسترسی‌ای دارند؟</h3>
        <p className="mb-3 text-xs leading-6 text-[var(--mu)]">
          دسترسی هر نقش در سرور اعمال می‌شود؛ مخفی‌بودن یک منو تنها راحتی کاربر است. هر تلاش خارج از نقش در ممیزی ثبت
          می‌شود.
        </p>
        {roleList.length ? <RoleGuide roles={roleList} /> : <div className="skel h-24 w-full" />}
      </section>

      {inviting && (
        <InviteDrawer call={call} roles={roleList} onClose={() => setInviting(false)} onDone={admins.load} />
      )}
      {selected && (
        <AdminDrawer
          key={selected.id}
          call={call}
          admin={selected}
          roles={roleList}
          toast={toast}
          onClose={() => setSelId(null)}
          onChanged={admins.load}
        />
      )}
    </div>
  );
}

export { RoleBadge, inviteLink } from './AdminTeamParts.tsx';
