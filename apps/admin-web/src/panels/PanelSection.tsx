import { useState } from 'react';
import { describeTarget, ago as lastAssigned } from '../targets.ts';
import { Badge, dt } from '../ui.tsx';
import { Dot, HLABEL, RelChip, health, serverState, usage } from '../infra.tsx';
import { Ring, CopyButton, Switch, DeleteButton, capTone, num, tint } from '../kit.tsx';
import {
  AlertTriangle,
  ChevronDown,
  ExternalLink,
  FolderInput,
  Layers,
  MapPin,
  Pencil,
  Plus,
  RefreshCw,
  ServerCog,
} from 'lucide-react';
import { UpstreamSpecs } from '../UpstreamBotFields.tsx';
import { ubSummary } from '../upstreamBot.ts';
import { ago, isStale, kindOf, Meter } from './panelUi.tsx';
import type { Json, Rec } from '../types.ts';

// ---------- one panel with its servers ----------
function ServerRow({ s, panel, busy, onEdit, onToggle, onDelete }: { s?: Json; panel?: Json; busy?: Json; onEdit?: Json; onToggle?: Json; onDelete?: Json }) {
  const st = serverState(s, panel),
    dim = s.is_enabled ? '' : 'opacity-60';
  const limited = (s.product_codes || []).length;
  return (
    <li className="grid gap-3 px-4 py-3 transition-colors hover:bg-[var(--sf2)] md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_auto] md:items-center">
      <div className={`flex min-w-0 items-center gap-3 ${dim}`}>
        <span className="tile h-9 w-9" style={tint(st.tone)}>
          <ServerCog size={16} />
        </span>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <b className="truncate" title={s.name}>
              {s.name}
            </b>
            {!s.allow_test && (
              <span className="badge b-mu" title="اکانت تست روی این سرور ساخته نمی‌شود">
                بدون تست
              </span>
            )}
            {limited > 0 && (
              <span className="badge b-wn" title="این سرور فقط برای محصولات انتخاب‌شده استفاده می‌شود">
                فقط {num(limited)} محصول
              </span>
            )}
          </div>
          <div className="mt-1 flex items-center gap-2 text-[11px] text-[var(--mu)]">
            {s.location ? (
              <span className="flex items-center gap-1">
                <MapPin size={11} />
                {s.location}
              </span>
            ) : null}
            <span className={`badge b-${st.tone}`}>{st.label}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-[var(--mu)]">
            <span className="badge b-in" title="مقصد اتصال این سرور">
              {describeTarget(
                s.effective_target && Object.keys(s.effective_target).length ? s.effective_target : s.target,
              )}
            </span>
            <span title="آخرین فروش جدید که به این مقصد رسید">آخرین تخصیص: {lastAssigned(s.last_assigned_at)}</span>
          </div>
        </div>
      </div>
      <div className={dim}>
        <Meter s={s} panelKind={panel?.kind} />
      </div>
      <div className="flex items-center justify-end gap-2">
        <Switch
          checked={s.is_enabled}
          disabled={busy}
          onChange={(v: Json) => onToggle(s, v)}
          label={`${s.is_enabled ? 'غیرفعال‌سازی' : 'فعال‌سازی'} ${s.name}`}
        />
        <button className="btn btn-g" onClick={() => onEdit(s)}>
          <Pencil size={13} />
          ویرایش
        </button>
        <DeleteButton compact label={`حذف ${s.name}`} busy={busy} onClick={() => onDelete(s)} />
      </div>
    </li>
  );
}

const STRIPE: Rec = { healthy: 'var(--ok)', degraded: 'var(--wn)', unhealthy: 'var(--bd)', unknown: 'var(--wn)' };
export function PanelSection({
  p,
  servers,
  stat,
  groups,
  busy,
  srvBusy,
  filtered,
  dense,
  onCheck,
  onEdit,
  onToggle,
  onDelete,
  onSrvAdd,
  onSrvEdit,
  onSrvToggle,
  onSrvDelete,
  onImport,
  onWizard,
}: { p?: Json; servers?: Json; stat?: Json; groups?: Json; busy?: Json; srvBusy?: Json; filtered?: Json; dense?: Json; onCheck?: Json; onEdit?: Json; onToggle?: Json; onDelete?: Json; onSrvAdd?: Json; onSrvEdit?: Json; onSrvToggle?: Json; onSrvDelete?: Json; onImport?: Json; onWizard?: Json }) {
  const h = health(p),
    k = kindOf(p.kind),
    u = stat.capacity ? stat.active / stat.capacity : 0,
    t = capTone(u),
    stale = isStale(p) && p.is_enabled;
  const [open, setOpen] = useState(true);
  const showServers = !dense && open;
  return (
    <section
      id={`panel-${p.id}`}
      className={`card card-i rise stripe overflow-hidden ${p.is_enabled ? '' : 'off'}`}
      style={{ '--stripe': p.is_enabled ? STRIPE[h] : 'var(--ln)' }}
    >
      <header
        className={`space-y-3 border-b border-[var(--ln)] bg-[linear-gradient(180deg,var(--sf2),var(--sf))] px-5 py-4 ${p.is_enabled ? '' : 'opacity-80'}`}
      >
        <div className="flex flex-wrap items-center gap-4">
          <span className="tile h-12 w-12" style={tint(k.tone)}>
            <k.Icon size={22} />
          </span>
          <div className="min-w-0 flex-1 basis-60">
            <div className="flex flex-wrap items-center gap-2">
              <b className="truncate text-base font-extrabold" title={p.name}>
                {p.name}
              </b>
              <span className="hp" style={tint(h === 'healthy' ? 'ok' : h === 'unhealthy' ? 'bd' : 'wn')}>
                <Dot s={h} ping />
                {HLABEL[h]}
              </span>
              {!p.is_enabled && <Badge s="disabled" />}
            </div>
            <div className="mt-1.5 flex min-w-0 items-center gap-1.5">
              <span className="shrink-0 text-[11px] font-bold text-[var(--mu)]">{k.title}</span>
              <span className="text-[var(--ln)]">·</span>
              <span dir="ltr" className="min-w-0 truncate font-mono text-[11px] text-[var(--mu)]" title={p.base_url}>
                {p.base_url}
              </span>
              <CopyButton text={p.base_url} />
              <a
                className="btn btn-g !px-2"
                href={p.base_url}
                target="_blank"
                rel="noopener noreferrer"
                aria-label="باز کردن پنل"
                title="باز کردن پنل"
              >
                <ExternalLink size={13} />
              </a>
            </div>
          </div>
          {stat.n > 0 && (
            <div
              className="flex items-center gap-3"
              title={`${num(stat.active)} اکانت فعال از ظرفیت ${num(stat.capacity)}`}
            >
              <Ring value={u} size={54} stroke={6} tone={t} label={`ظرفیت پر: ${Math.round(u * 100)} درصد`}>
                <b className="num text-xs font-extrabold">{num(Math.round(u * 100))}٪</b>
              </Ring>
              <div className="text-[11px] leading-5 text-[var(--mu)]">
                <b className="num block text-sm text-[var(--tx)]">
                  {num(stat.active)} <span className="font-normal text-[var(--mu)]">/ {num(stat.capacity)}</span>
                </b>
                {num(stat.n)} سرور
              </div>
            </div>
          )}
          <div className="flex items-center gap-1.5">
            <Switch
              checked={p.is_enabled}
              disabled={busy}
              onChange={(v: Json) => onToggle(p, v)}
              label={`${p.is_enabled ? 'غیرفعال‌سازی' : 'فعال‌سازی'} ${p.name}`}
            />
            <button className="btn btn-g" onClick={() => onEdit(p)}>
              <Pencil size={13} />
              ویرایش
            </button>
            <button
              className="btn btn-g !px-2"
              aria-label="بررسی سلامت"
              title={`بررسی سلامت · آخرین بررسی ${ago(p.last_health_at)}`}
              disabled={busy}
              onClick={() => onCheck(p)}
            >
              <RefreshCw size={13} className={busy ? 'animate-spin' : ''} />
            </button>
            <DeleteButton compact label={`حذف پنل ${p.name}`} busy={busy} onClick={() => onDelete(p)} />
          </div>
        </div>
        {p.kind === 'upstream_bot' && <UpstreamSpecs summary={ubSummary(p)} />}
        <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
          <span className="text-[var(--mu)]">بسته‌ها:</span>
          {groups.length ? (
            groups.slice(0, 4).map((g: Json) => (
              <RelChip key={g.id} to="bundles" params={{ q: g.name }} tone="wn" Icon={Layers} dim={!g.is_enabled}>
                {g.name}
              </RelChip>
            ))
          ) : (
            <span className="font-bold text-[var(--wn)]">هیچ — این پنل چیزی نمی‌فروشد</span>
          )}
          {groups.length > 4 && <span className="text-[var(--mu)]">+{num(groups.length - 4)}</span>}
          <span
            className={`mr-auto flex items-center gap-1 ${stale ? 'font-bold text-[var(--wn)]' : 'text-[var(--mu)]'}`}
            title={p.last_health_at ? dt(p.last_health_at) : ''}
          >
            {stale && <AlertTriangle size={12} />}آخرین بررسی: {ago(p.last_health_at)}
          </span>
        </div>
        {h === 'unhealthy' && p.last_health_error && (
          <p
            dir="auto"
            className="break-words rounded-lg bg-[var(--bdb)] px-3 py-2 text-[11px] leading-5 text-[var(--bd)]"
          >
            {p.last_health_error}
          </p>
        )}
      </header>
      {dense ? (
        <div className="flex flex-wrap items-center gap-1.5 px-5 py-3">
          {servers.length ? (
            servers.map((sv: Json) => {
              const st = serverState(sv, p);
              return (
                <span
                  key={sv.id}
                  className="spec"
                  title={`${st.label} · ${num(sv.active_accounts)} از ${num(sv.capacity)}`}
                >
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ background: `var(--${st.ok ? capTone(usage(sv)) : st.tone})` }}
                  />
                  {sv.name}
                  <span className="num font-normal text-[var(--mu)]">
                    {num(sv.active_accounts)}/{num(sv.capacity)}
                  </span>
                </span>
              );
            })
          ) : (
            <span className="text-xs font-bold text-[var(--wn)]">بدون سرور</span>
          )}
        </div>
      ) : (
        <>
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
            className="flex w-full items-center gap-2 border-b border-[var(--hair)] px-5 py-2 text-[11px] font-bold text-[var(--mu)] hover:text-[var(--tx)]"
          >
            <ChevronDown size={14} className={open ? '' : '-rotate-90'} />
            مقصدها (گروه/اینباند)<span className="badge b-mu num">{num(servers.length)}</span>
          </button>
          {showServers &&
            (servers.length ? (
              <ul className="divide-y divide-[var(--hair)]">
                {servers.map((sv: Json) => (
                  <ServerRow
                    key={sv.id}
                    s={sv}
                    panel={p}
                    busy={srvBusy.has(sv.id)}
                    onEdit={onSrvEdit}
                    onToggle={onSrvToggle}
                    onDelete={onSrvDelete}
                  />
                ))}
              </ul>
            ) : (
              <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-5 text-sm">
                <span className="flex items-center gap-2 text-[var(--wn)]">
                  <AlertTriangle size={15} />
                  {filtered
                    ? 'سروری با این فیلتر روی این پنل نیست'
                    : 'این پنل هنوز مقصد ندارد؛ تا ظرفیت تعریف نشود اکانتی روی آن ساخته نمی‌شود.'}
                </span>
                {!filtered && (
                  <button className="btn" onClick={() => onSrvAdd(p)}>
                    <Plus size={15} />
                    افزودن اولین مقصد
                  </button>
                )}
              </div>
            ))}
          {showServers && servers.length > 0 && (
            <footer className="flex flex-wrap items-center gap-2 bg-[var(--sf2)] px-5 py-2.5">
              <button className="btn btn-g" onClick={() => onSrvAdd(p)}>
                <Plus size={13} />
                مقصد جدید
              </button>
              <button className="btn btn-g" onClick={() => onWizard(p)}>
                <Layers size={13} />
                ساخت از روی گروه/اینباندها
              </button>
              <button className="btn btn-g" onClick={() => onImport(p)}>
                <FolderInput size={13} />
                ورود دسته‌جمعی
              </button>
            </footer>
          )}
        </>
      )}
    </section>
  );
}
