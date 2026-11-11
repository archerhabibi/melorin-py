import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Layers, RefreshCw, Wand2 } from 'lucide-react';
import { authFetch } from './api.ts';
import { Drawer, Field, NumInput, Section, Segmented, Toggle, errText, num, tint } from './kit.tsx';
import { capacityLabel, targetKind } from './targets.ts';
import type { Json, Rec } from './types.ts';

/** GET /admin/panels/{id}/targets once per panel; `reload` re-asks (the panel may have new groups). */
export function usePanelTargets(api: Json, panelId: Json) {
  const [st, setSt] = useState<{ loading: boolean; data: Json; error: string }>({
    loading: !!panelId,
    data: null,
    error: '',
  });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!panelId) return undefined;
    let live = true;
    setSt((x) => ({ ...x, loading: true, error: '' }));
    authFetch(api.base, `/api/v1/admin/panels/${panelId}/targets`)
      .then(async (r) => {
        if (!live) return;
        if (r.ok) setSt({ loading: false, data: await r.json(), error: '' });
        else setSt({ loading: false, data: null, error: await errText(r, 'فهرست مقصدها از پنل خوانده نشد') });
      })
      .catch(() => live && setSt({ loading: false, data: null, error: 'ارتباط با سرور برقرار نشد' }));
    return () => {
      live = false;
    };
  }, [api.base, panelId, tick]);
  return { ...st, reload: () => setTick((t) => t + 1) };
}

const Chip = ({
  on,
  dim,
  onClick,
  title,
  sub,
  usedBy,
}: {
  on?: Json;
  dim?: Json;
  onClick?: Json;
  title?: Json;
  sub?: Json;
  usedBy?: Json;
}) => (
  <button
    type="button"
    aria-pressed={on}
    onClick={onClick}
    className={`rounded-xl border px-3 py-2 text-right text-xs transition ${on ? 'border-[var(--ac)] bg-[var(--sf)] font-bold ring-2 ring-[color-mix(in_srgb,var(--ac)_22%,transparent)]' : 'border-[var(--ln)] bg-[var(--sf2)] hover:border-[var(--mu)]'} ${dim ? 'opacity-60' : ''}`}
  >
    <span className="block">{title}</span>
    {sub && (
      <span dir="ltr" className="block text-right text-[10px] text-[var(--mu)]">
        {sub}
      </span>
    )}
    {usedBy?.length > 0 && (
      <span className="block text-[10px] text-[var(--wn)]">
        در «{usedBy[0].name}»{usedBy.length > 1 ? ` و ${num(usedBy.length - 1)} مورد دیگر` : ''}
      </span>
    )}
  </button>
);

/**
 * Choose a server's destination. `value` is the target object or null (= inherit the panel config).
 * Pasarguard: one or more groups, or one template. Sanaei: one or more inbounds (legacy panels: exactly one).
 */
export function TargetPicker({
  api,
  panel,
  value,
  onChange,
}: {
  api?: Json;
  panel?: Json;
  value?: Json;
  onChange?: Json;
}) {
  const { loading, data, error, reload } = usePanelTargets(api, panel?.id);
  const kind = panel?.kind;
  const mode = value == null ? 'inherit' : targetKind(kind, value) === 'template' ? 'template' : 'set';
  const legacy = kind === 'sanaei' && data?.api_style === 'legacy';
  const ids = value?.group_ids || value?.inbound_ids || [];
  const pickSet = (id: Json) => {
    const key = kind === 'sanaei' ? 'inbound_ids' : 'group_ids';
    const next = legacy ? [id] : ids.includes(id) ? ids.filter((x: Json) => x !== id) : [...ids, id];
    onChange(next.length ? { [key]: next } : { [key]: [] });
  };
  const rows = kind === 'sanaei' ? data?.inbounds : data?.groups;
  const modes = [
    ['inherit', 'ارث‌بری از پنل'],
    ['set', kind === 'sanaei' ? 'اینباند' : 'گروه'],
    ...(kind === 'pasarguard' ? [['template', 'تمپلیت']] : []),
  ];
  const setMode = (m: Json) => {
    if (m === 'inherit') onChange(null);
    else if (m === 'template') onChange({ user_template_id: data?.templates?.[0]?.id ?? 0 });
    else onChange(kind === 'sanaei' ? { inbound_ids: [] } : { group_ids: [] });
  };
  return (
    <div className="space-y-3">
      <Segmented label="نوع مقصد" value={mode} onChange={setMode} options={modes} />
      {mode === 'inherit' && (
        <p className="text-[11px] leading-5 text-[var(--mu)]">
          بدون مقصد اختصاصی: اکانت‌های جدید روی همان گروه/اینباندی ساخته می‌شوند که در تنظیمات خود پنل ثبت شده است.
        </p>
      )}
      {mode !== 'inherit' && loading && <div className="skel h-16" />}
      {mode !== 'inherit' && error && (
        <p className="flex items-start gap-2 rounded-lg bg-[var(--wnb)] p-3 text-xs leading-6 text-[var(--wn)]">
          <AlertTriangle size={15} className="mt-1 shrink-0" />
          <span>
            {error}. می‌توانید شناسه را دستی وارد کنید؛ ذخیره مسدود نمی‌شود.{' '}
            <button type="button" className="font-bold underline" onClick={reload}>
              تلاش دوباره
            </button>
          </span>
        </p>
      )}
      {mode === 'set' && data && (
        <div className="flex flex-wrap gap-2">
          {(rows || []).map((r: Json) => (
            <Chip
              key={r.id}
              on={ids.includes(r.id)}
              dim={r.disabled || r.enabled === false}
              onClick={() => pickSet(r.id)}
              title={r.name || r.remark || `#${r.id}`}
              sub={r.protocol ? `${r.protocol}:${r.port}` : `#${r.id}`}
              usedBy={r.used_by}
            />
          ))}
          {!rows?.length && <p className="text-xs text-[var(--mu)]">پنل موردی برای انتخاب برنگرداند.</p>}
        </div>
      )}
      {mode === 'set' && legacy && (
        <p className="text-[11px] text-[var(--wn)]">این پنل سنایی قدیمی است و فقط یک اینباند می‌پذیرد.</p>
      )}
      {mode === 'template' && data && (
        <>
          <div className="flex flex-wrap gap-2">
            {(data.templates || []).map((t: Json) => (
              <Chip
                key={t.id}
                on={value?.user_template_id === t.id}
                dim={t.disabled}
                onClick={() => onChange({ ...value, user_template_id: t.id })}
                title={t.name}
                sub={`#${t.id}`}
                usedBy={t.used_by}
              />
            ))}
          </div>
          <Segmented
            label="حجم و مدت از"
            value={value?.limits_from || 'product'}
            onChange={(v: Json) =>
              onChange({ user_template_id: value.user_template_id, ...(v === 'template' ? { limits_from: v } : {}) })
            }
            options={[
              ['product', 'پکیج فروش (پیشنهادی)'],
              ['template', 'خود تمپلیت'],
            ]}
          />
          <p className="text-[11px] leading-5 text-[var(--mu)]">
            با «پکیج فروش» یک تمپلیت برای همه‌ی پلن‌ها کافی است؛ حجم و مدت پکیج بلافاصله بعد از ساخت اعمال می‌شود. برای
            ۲۴ گروه یا بیشتر، گروه مسیر اصلی است.
          </p>
        </>
      )}
    </div>
  );
}

/**
 * Wizard (and "sync with panel"): tick several groups / templates / inbounds, one server slot is created for each
 * (POST /admin/panels/{id}/servers/from-targets). Targets that already have a server are marked and skipped.
 */
export function TargetWizard({
  api,
  panel,
  toast,
  onClose,
  onDone,
}: {
  api?: Json;
  panel?: Json;
  toast?: Json;
  onClose?: Json;
  onDone?: Json;
}) {
  const { loading, data, error, reload } = usePanelTargets(api, panel.id);
  const sanaei = panel.kind === 'sanaei';
  const [kind, setKind] = useState(sanaei ? 'inbound' : 'group');
  const [picked, setPicked] = useState<Rec[]>([]);
  const [cap, setCap] = useState('');
  const [allowTest, setAllowTest] = useState(true);
  const [asOne, setAsOne] = useState(false);
  const [limitsFrom, setLimitsFrom] = useState('product');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const rows = useMemo(
    () => (kind === 'group' ? data?.groups : kind === 'template' ? data?.templates : data?.inbounds) || [],
    [data, kind],
  );
  useEffect(() => setPicked([]), [kind]);
  const free = rows.filter((r: Json) => !r.used_by?.length);
  const capacity = Number(cap || data?.capacity_default || 500);
  const toggle = (id: Json) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  const run = async () => {
    setBusy(true);
    setMsg('');
    try {
      const body = {
        kind,
        ids: picked,
        capacity,
        allow_test: allowTest,
        ...(kind === 'inbound' ? { group_as_one: asOne } : {}),
        ...(kind === 'template' ? { limits_from: limitsFrom } : {}),
      };
      const r = await authFetch(api.base, `/api/v1/admin/panels/${panel.id}/servers/from-targets`, {
        method: 'POST',
        body: JSON.stringify(body),
      });
      if (!r.ok) return setMsg(await errText(r, 'ساخت مقصدها ناموفق بود'));
      const out = await r.json();
      toast(
        `${num(out.created.length)} مقصد ساخته شد${out.skipped.length ? ` · ${num(out.skipped.length)} مورد قبلاً وجود داشت` : ''}`,
      );
      await onDone();
      onClose();
    } catch {
      setMsg('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Drawer
      title="ساخت مقصد از روی انتخاب‌ها"
      subtitle={`روی پنل «${panel.name}»`}
      icon={
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint('in')}>
          <Wand2 size={20} />
        </span>
      }
      dirty={picked.length > 0}
      busy={busy}
      error={msg}
      onClose={onClose}
      footer={
        <button className="btn" disabled={busy || !picked.length} onClick={run}>
          {busy ? <RefreshCw size={15} className="animate-spin" /> : <Layers size={15} />}ساخت {num(picked.length)} مقصد
        </button>
      }
    >
      <Section
        title="مقصدهای پنل"
        hint="هرکدام یک مقصد جدا با ظرفیت خودش می‌شود؛ مواردی که قبلاً مقصد دارند علامت خورده‌اند."
      >
        {!sanaei && (
          <Segmented
            label="نوع"
            value={kind}
            onChange={setKind}
            options={[
              ['group', 'گروه‌ها'],
              ['template', 'تمپلیت‌ها'],
            ]}
          />
        )}
        {loading && <div className="skel h-20" />}
        {error && (
          <p className="text-xs text-[var(--wn)]">
            {error}{' '}
            <button className="font-bold underline" onClick={reload}>
              تلاش دوباره
            </button>
          </p>
        )}
        {data && (
          <>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <button type="button" className="btn btn-g" onClick={() => setPicked(free.map((r: Json) => r.id))}>
                انتخاب همه‌ی بدون مقصد ({num(free.length)})
              </button>
              <button type="button" className="btn btn-g" onClick={() => setPicked([])}>
                هیچ‌کدام
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              {rows.map((r: Json) => (
                <Chip
                  key={r.id}
                  on={picked.includes(r.id)}
                  dim={r.disabled || r.enabled === false || !!r.used_by?.length}
                  onClick={() => toggle(r.id)}
                  title={r.name || r.remark || `#${r.id}`}
                  sub={r.protocol ? `${r.protocol}:${r.port}` : `#${r.id}`}
                  usedBy={r.used_by}
                />
              ))}
            </div>
          </>
        )}
      </Section>
      <Section title="تنظیمات مشترک">
        <Field
          label={capacityLabel(
            panel.kind,
            kind === 'template'
              ? { user_template_id: 0 }
              : kind === 'inbound'
                ? { inbound_ids: [] }
                : { group_ids: [] },
          )}
          hint="برای همه‌ی مقصدهای ساخته‌شده؛ بعداً برای هرکدام قابل ویرایش است."
        >
          <NumInput value={cap} onChange={setCap} suffix="اکانت" placeholder={String(data?.capacity_default || 500)} />
        </Field>
        <Toggle checked={allowTest} onChange={setAllowTest} label="اکانت تست روی این مقصدها مجاز باشد" />
        {kind === 'inbound' && (
          <Toggle
            checked={asOne}
            onChange={setAsOne}
            label="همه‌ی اینباندهای انتخابی در «یک» مقصد باشند (ست)"
            hint="روشن: یک کلاینت روی همه‌ی آن‌ها ساخته می‌شود. خاموش: برای هر اینباند یک مقصد."
          />
        )}
        {kind === 'template' && (
          <Segmented
            label="حجم و مدت از"
            value={limitsFrom}
            onChange={setLimitsFrom}
            options={[
              ['product', 'پکیج فروش'],
              ['template', 'خود تمپلیت'],
            ]}
          />
        )}
      </Section>
    </Drawer>
  );
}
