import { useCallback, useEffect, useMemo, useState } from 'react';
import { Info, Paintbrush, RotateCcw, Save, Send, Sparkles } from 'lucide-react';
import { useCall } from '../../api/api.ts';
import { Empty, ErrorBar, Section, Switch, errText, num } from '../../shared/kit.tsx';
import { confirmDialog } from '../../shared/ui.tsx';
import { fromPreset, ruleId, ruleProblem, sameConfig, toPayload } from './buttonStyles.ts';
import type { ButtonRule, ButtonStyleConfig, ButtonStylesPayload } from './buttonStyles.ts';
import type { Toast } from '../../shared/types.ts';
import { Preview } from './ButtonStylePreview';
import { RuleCard, AddRule } from './ButtonStyleRules';

const EMPTY: ButtonStyleConfig = { enabled: false, rules: [] };

export default function ButtonStylesView({ api, toast }: { api: { base: string }; toast: Toast }) {
  const call = useCall(api);
  const [data, setData] = useState<ButtonStylesPayload | null>(null);
  const [saved, setSaved] = useState<ButtonStyleConfig>(EMPTY);
  const [cfg, setCfg] = useState<ButtonStyleConfig>(EMPTY);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<'' | 'save' | 'preview'>('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const r = await call('/api/v1/admin/telegram/button-styles');
      if (!r.ok) throw new Error('load');
      const d: ButtonStylesPayload = await r.json();
      setData(d);
      setSaved(d.config);
      setCfg(d.config);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [call]);
  useEffect(() => {
    load();
  }, [load]);

  const catalogByKey = useMemo(() => new Map((data?.catalog ?? []).map((c) => [ruleId(c), c])), [data]);
  const maxDecor = data?.limits.max_decor ?? 6;
  const maxRules = data?.limits.max_rules ?? 120;
  const dirty = !sameConfig(cfg, saved);
  const problems = cfg.rules.filter((r) => ruleProblem(r, maxDecor)).length;
  const used = useMemo(() => new Set(cfg.rules.map(ruleId)), [cfg.rules]);

  const patch = (id: string, p: Partial<ButtonRule>) =>
    setCfg((c) => ({ ...c, rules: c.rules.map((r) => (ruleId(r) === id ? { ...r, ...p } : r)) }));
  const add = (r: ButtonRule) => {
    if (used.has(ruleId(r))) return toast('برای این دکمه قبلاً قانون ساخته‌اید');
    setCfg((c) => ({ ...c, rules: [...c.rules, r] }));
  };

  const applyPreset = async (id: string) => {
    const preset = data?.presets.find((p) => p.id === id);
    if (!preset) return;
    if (cfg.rules.length) {
      const ok = await confirmDialog(
        `قانون‌های فعلی با الگوی «${preset.name}» جایگزین شود؟ (تا قبل از ذخیره می‌توانید بازگردانید)`,
        {
          title: 'اعمال الگو',
          ok: 'جایگزین کن',
        },
      );
      if (!ok) return;
    }
    setCfg({ enabled: true, rules: fromPreset(preset) });
  };

  const save = async () => {
    setError('');
    setBusy('save');
    try {
      const r = await call('/api/v1/admin/telegram/button-styles', {
        method: 'PUT',
        body: JSON.stringify(toPayload(cfg)),
      });
      if (!r.ok) return setError(await errText(r, 'ذخیره ناموفق بود'));
      const d: ButtonStylesPayload = await r.json();
      setData(d);
      setSaved(d.config);
      setCfg(d.config);
      toast(
        d.config.enabled ? 'ذخیره شد؛ ربات‌ها تا حدود یک دقیقه دیگر اعمال می‌کنند' : 'ذخیره شد (رنگی‌سازی خاموش است)',
      );
    } catch {
      setError('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy('');
    }
  };

  const sendPreview = async () => {
    setError('');
    setBusy('preview');
    try {
      const r = await call('/api/v1/admin/telegram/button-styles/preview', {
        method: 'POST',
        body: JSON.stringify(toPayload(cfg)),
      });
      if (!r.ok) return setError(await errText(r, 'ارسال پیش‌نمایش ناموفق بود'));
      toast('پیش‌نمایش به تلگرام شما ارسال شد');
    } catch {
      setError('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy('');
    }
  };

  if (failed) return <ErrorBar onRetry={load}>دریافت تنظیمات دکمه‌ها ناموفق بود.</ErrorBar>;
  if (!data) return <div className="card p-6 text-sm text-[var(--mu)]">در حال بارگذاری…</div>;

  const titleOf = (r: ButtonRule) => catalogByKey.get(ruleId(r))?.label || r.note || r.key;

  return (
    <div className="space-y-5">
      <Section
        title="رنگی‌سازی دکمه‌های تلگرام"
        hint="رنگ (آبی، سبز، قرمز)، ایموجی پریمیوم و تزئین متن دکمه‌ها را برای ربات اصلی و همهٔ ربات‌های نمایندگان یک‌جا تعیین کنید."
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Switch
              checked={cfg.enabled}
              onChange={(v: boolean) => setCfg({ ...cfg, enabled: v })}
              label="فعال‌سازی رنگی‌سازی دکمه‌ها"
            />
            <span className="text-sm font-bold">{cfg.enabled ? 'فعال' : 'خاموش — دکمه‌ها ساده ارسال می‌شوند'}</span>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn btn-g" disabled={!!busy} onClick={sendPreview}>
              <Send size={15} /> {busy === 'preview' ? 'در حال ارسال…' : 'ارسال نمونه به تلگرام من'}
            </button>
            <button type="button" className="btn btn-g" disabled={!dirty || !!busy} onClick={() => setCfg(saved)}>
              <RotateCcw size={15} /> بازگردانی
            </button>
            <button type="button" className="btn" disabled={!dirty || !!busy || problems > 0} onClick={save}>
              <Save size={15} /> {busy === 'save' ? 'در حال ذخیره…' : 'ذخیره'}
            </button>
          </div>
        </div>
        {dirty && <div className="text-xs font-bold text-[var(--wn)]">تغییرات ذخیره‌نشده دارید.</div>}
        {error && <ErrorBar>{error}</ErrorBar>}
        <div className="flex items-start gap-2 rounded-xl border border-[var(--ln)] p-3 text-[11px] leading-6 text-[var(--mu)]">
          <Info size={14} className="mt-1 shrink-0" />
          <span>
            رنگ دکمه‌ها (Bot API 9.4) برای همهٔ کاربران نمایش داده می‌شود. ایموجی پریمیوم فقط وقتی دیده می‌شود که صاحب
            ربات اشتراک Telegram Premium داشته باشد (یا ربات نام کاربری اضافه از Fragment خریده باشد)؛ در غیر این صورت
            تلگرام آن را نشان نمی‌دهد. اگر تلگرام دکمهٔ رنگی را نپذیرد، ربات همان پیام را بدون رنگ ارسال می‌کند و پیامی
            گم نمی‌شود.
          </span>
        </div>
      </Section>

      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-5">
          <Section
            title="الگوهای آماده"
            hint="با یک کلیک همهٔ قانون‌ها را از یک الگو بسازید و بعد جزئیات را تغییر دهید."
          >
            <div className="grid gap-3 sm:grid-cols-3">
              {data.presets.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className="card p-3 text-start transition hover:ring-2 hover:ring-[var(--ac)]"
                  onClick={() => applyPreset(p.id)}
                >
                  <span className="flex items-center gap-1.5 text-sm font-extrabold">
                    <Sparkles size={14} /> {p.name}
                  </span>
                  <span className="mt-1 block text-[11px] leading-5 text-[var(--mu)]">{p.description}</span>
                </button>
              ))}
            </div>
          </Section>

          <Section
            title={`قانون‌ها (${num(cfg.rules.length)} از ${num(maxRules)})`}
            hint="قانون دقیق بر قانون پیشوندی و پیشوند بلندتر بر کوتاه‌تر مقدم است."
          >
            <AddRule catalog={data.catalog} used={used} disabled={cfg.rules.length >= maxRules} onAdd={add} />
            {cfg.rules.length === 0 ? (
              <Empty
                Icon={Paintbrush}
                title="هنوز قانونی ندارید"
                text="یک الگو را اعمال کنید یا دکمه‌ای را از فهرست بالا اضافه کنید."
              />
            ) : (
              <ul className="space-y-3">
                {cfg.rules.map((r) => (
                  <RuleCard
                    key={ruleId(r)}
                    rule={r}
                    title={titleOf(r)}
                    maxDecor={maxDecor}
                    onChange={(p) => patch(ruleId(r), p)}
                    onRemove={() => setCfg((c) => ({ ...c, rules: c.rules.filter((x) => ruleId(x) !== ruleId(r)) }))}
                  />
                ))}
              </ul>
            )}
          </Section>
        </div>

        <div className="lg:sticky lg:top-4">
          <Section
            title="پیش‌نمایش زنده"
            hint={
              cfg.enabled
                ? 'همان چیزی که مشتری در تلگرام می‌بیند.'
                : 'رنگی‌سازی خاموش است؛ دکمه‌ها ساده نمایش داده می‌شوند.'
            }
          >
            <Preview cfg={cfg} />
          </Section>
        </div>
      </div>
    </div>
  );
}
