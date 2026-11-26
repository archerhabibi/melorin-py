// Mandatory channel membership ("force join") of the main Telegram bot: one switch, up to five channels, the message users
// see, how long a confirmed membership is remembered, a live preview of the join screen and a Telegram check of every channel.
// Core enforces it at bot sign-in (modules/channel_gate); reseller bots are never gated.
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Info,
  Lock,
  Plus,
  RotateCcw,
  Save,
  ShieldCheck,
  Trash2,
  TriangleAlert,
} from 'lucide-react';
import { API_BASE, errorMessage, typedClient } from '../../api/api.ts';
import { ErrorBar, Field, Section, Switch } from '../../shared/kit.tsx';
import { confirmDialog } from '../../shared/ui.tsx';
import type { Toast } from '../../shared/types.ts';
import {
  DEFAULT_LIMITS,
  blankChannel,
  channelProblem,
  draftProblem,
  fromConfig,
  isPrivate,
  joinUrl,
  move,
  parseChat,
  sameDraft,
  toPayload,
} from './channelJoin.ts';
import type { ChannelCheck, ChannelDraft, ChannelJoinCheck, ChannelJoinView as Payload, Draft } from './channelJoin.ts';

const PATH = '/api/v1/admin/telegram/channel-join' as const;
const CHECK_PATH = '/api/v1/admin/telegram/channel-join/check' as const;
const EMPTY: Draft = { enabled: false, channels: [], message: '', cache_seconds: 300 };

export default function ChannelJoinView({ api, toast }: { api?: { base?: string }; toast: Toast }) {
  const base = api?.base || API_BASE;
  const client = useMemo(() => typedClient(base), [base]);
  const [data, setData] = useState<Payload | null>(null);
  const [saved, setSaved] = useState<Draft>(EMPTY);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<'' | 'save' | 'check'>('');
  const [error, setError] = useState('');
  const [check, setCheck] = useState<ChannelJoinCheck | null>(null);

  const load = useCallback(async () => {
    try {
      const { data: d } = await client.get(PATH);
      if (!d) throw new Error('load');
      setData(d);
      setSaved(fromConfig(d.config));
      setDraft(fromConfig(d.config));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [client]);
  useEffect(() => {
    load();
  }, [load]);

  const limits = data?.limits ?? DEFAULT_LIMITS;
  const defaultMessage = data?.defaults.message ?? '';
  const dirty = !sameDraft(draft, saved);
  const problem = draftProblem(draft, limits);

  const patchChannel = (i: number, p: Partial<ChannelDraft>) => {
    setCheck(null);
    setDraft((d) => ({ ...d, channels: d.channels.map((c, j) => (j === i ? { ...c, ...p } : c)) }));
  };
  const removeChannel = (i: number) => {
    setCheck(null);
    setDraft((d) => ({ ...d, channels: d.channels.filter((_, j) => j !== i) }));
  };

  /** Probe the channels in the editor (saved or not). Returns the result, or null when the check itself failed. */
  const runCheck = async (): Promise<ChannelJoinCheck | null> => {
    setError('');
    setBusy('check');
    try {
      const { data: d, error: e } = await client.post(CHECK_PATH, { body: toPayload({ ...draft, enabled: false }) });
      if (!d) {
        setError(errorMessage(e, 'بررسی کانال‌ها ناموفق بود'));
        return null;
      }
      setCheck(d);
      return d;
    } catch {
      setError('ارتباط با سرور برقرار نشد');
      return null;
    } finally {
      setBusy('');
    }
  };

  const save = async () => {
    if (draft.enabled && draft.channels.length) {
      const result = await runCheck();
      const bad = result ? result.channels.filter((c) => !c.ok).length : -1;
      if (bad !== 0) {
        const ok = await confirmDialog(
          bad > 0
            ? `ربات اصلی در ${bad} کانال آماده نیست (جزئیات زیر هر کانال). تا رفع مشکل، عضویت در آن کانال‌ها بررسی نمی‌شود و کاربران از آن‌ها رد می‌شوند. باز هم ذخیره شود؟`
            : 'بررسی کانال‌ها با تلگرام انجام نشد. بدون بررسی ذخیره شود؟',
          { title: 'ذخیرهٔ عضویت اجباری', ok: 'ذخیره کن' },
        );
        if (!ok) return;
      }
    }
    setError('');
    setBusy('save');
    try {
      const { data: d, error: e } = await client.put(PATH, { body: toPayload(draft) });
      if (!d) return setError(errorMessage(e, 'ذخیره ناموفق بود'));
      setData(d);
      setSaved(fromConfig(d.config));
      setDraft(fromConfig(d.config));
      toast(
        d.config.enabled ? 'ذخیره شد؛ عضویت اجباری از همین حالا اعمال می‌شود' : 'ذخیره شد (عضویت اجباری خاموش است)',
      );
    } catch {
      setError('ارتباط با سرور برقرار نشد');
    } finally {
      setBusy('');
    }
  };

  if (failed) return <ErrorBar onRetry={load}>دریافت تنظیمات عضویت اجباری ناموفق بود.</ErrorBar>;
  if (!data) return <div className="card p-6 text-sm text-[var(--mu)]">در حال بارگذاری…</div>;

  const checkOf = (ch: ChannelDraft): ChannelCheck | undefined =>
    check?.channels.find((c) => c.chat.toLowerCase() === (parseChat(ch.chat) ?? '').toLowerCase());

  return (
    <div className="space-y-5">
      <Section
        title="عضویت اجباری در کانال"
        hint="کاربران ربات اصلی تا وقتی در همهٔ کانال‌های زیر عضو نشوند، به منوی ربات دسترسی ندارند. ربات‌های نمایندگان تحت تأثیر نیستند."
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Switch
              checked={draft.enabled}
              onChange={(v: boolean) => setDraft({ ...draft, enabled: v })}
              label="فعال‌سازی عضویت اجباری"
            />
            <span className="text-sm font-bold">{draft.enabled ? 'فعال' : 'خاموش — همه بدون عضویت وارد می‌شوند'}</span>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn btn-g"
              disabled={!!busy || !draft.channels.length || draft.channels.some((c) => channelProblem(c))}
              onClick={runCheck}
            >
              <ShieldCheck size={15} /> {busy === 'check' ? 'در حال بررسی…' : 'بررسی کانال‌ها'}
            </button>
            <button
              type="button"
              className="btn btn-g"
              disabled={!dirty || !!busy}
              onClick={() => {
                setDraft(saved);
                setCheck(null);
              }}
            >
              <RotateCcw size={15} /> بازگردانی
            </button>
            <button type="button" className="btn" disabled={!dirty || !!busy || !!problem} onClick={save}>
              <Save size={15} /> {busy === 'save' ? 'در حال ذخیره…' : 'ذخیره'}
            </button>
          </div>
        </div>
        {dirty && <div className="text-xs font-bold text-[var(--wn)]">تغییرات ذخیره‌نشده دارید.</div>}
        {problem && dirty && <div className="text-xs font-bold text-[var(--bd)]">{problem}</div>}
        {error && <ErrorBar>{error}</ErrorBar>}
        {check && (
          <div
            role="status"
            className={`rounded-xl border p-3 text-xs font-bold ${check.ok ? 'border-[var(--ok)] text-[var(--ok)]' : 'border-[var(--wn)] text-[var(--wn)]'}`}
          >
            {check.ok
              ? `همهٔ کانال‌ها آماده‌اند؛ ربات ${check.bot_username ? '@' + check.bot_username : 'اصلی'} ادمین همهٔ آن‌هاست.`
              : 'بعضی کانال‌ها آماده نیستند؛ جزئیات زیر هر کانال آمده است.'}
          </div>
        )}
      </Section>

      <Section
        title={`کانال‌ها (${draft.channels.length} از ${limits.max_channels})`}
        hint="ترتیب کانال‌ها همان ترتیب دکمه‌ها در ربات است. ربات اصلی باید در هر کانال «ادمین» باشد (هیچ دسترسی خاصی لازم نیست)."
      >
        {draft.channels.length === 0 && (
          <div className="rounded-xl border border-dashed border-[var(--ln)] p-6 text-center text-sm text-[var(--mu)]">
            هنوز کانالی اضافه نشده است.
          </div>
        )}
        {draft.channels.map((ch, i) => (
          <ChannelCard
            key={i}
            index={i}
            ch={ch}
            count={draft.channels.length}
            result={checkOf(ch)}
            onPatch={(p) => patchChannel(i, p)}
            onRemove={() => removeChannel(i)}
            onMove={(to) => setDraft((d) => ({ ...d, channels: move(d.channels, i, to) }))}
          />
        ))}
        <button
          type="button"
          className="btn btn-g"
          disabled={draft.channels.length >= limits.max_channels}
          onClick={() => setDraft((d) => ({ ...d, channels: [...d.channels, blankChannel()] }))}
        >
          <Plus size={15} /> افزودن کانال
        </button>
      </Section>

      <div className="grid gap-5 lg:grid-cols-2">
        <Section title="پیام و رفتار" hint="متنی که کاربرِ عضونشده می‌بیند و مدت به‌خاطرسپاری عضویت تأییدشده.">
          <Field
            label="متن پیام"
            hint={`${draft.message.length} از ${limits.max_message} نویسه · خالی = متن پیش‌فرض`}
            error={draft.message.length > limits.max_message ? 'متن پیام بیش از حد طولانی است.' : ''}
          >
            <textarea
              className="inp min-h-28 leading-7"
              value={draft.message}
              placeholder={defaultMessage}
              onChange={(e) => setDraft({ ...draft, message: e.target.value })}
            />
          </Field>
          {draft.message.trim() !== defaultMessage && (
            <button
              type="button"
              className="btn btn-g !py-1.5 text-xs"
              onClick={() => setDraft({ ...draft, message: defaultMessage })}
            >
              <RotateCcw size={13} /> متن پیش‌فرض
            </button>
          )}
          <Field
            label="مدت به‌خاطرسپاری عضویت (ثانیه)"
            hint="عضویتِ تأییدشده تا این مدت دوباره از تلگرام پرسیده نمی‌شود (۰ = هر پیام بررسی شود). کسی که از کانال خارج شود حداکثر پس از همین مدت دوباره متوقف می‌شود."
          >
            <input
              className="inp"
              type="number"
              inputMode="numeric"
              min={0}
              max={limits.max_cache_seconds}
              value={draft.cache_seconds}
              onChange={(e) => setDraft({ ...draft, cache_seconds: Math.trunc(Number(e.target.value) || 0) })}
            />
          </Field>
        </Section>

        <Section title="پیش‌نمایش در ربات" hint="کاربری که عضو نیست این پیام را می‌بیند.">
          <JoinPreview draft={draft} defaultMessage={defaultMessage} />
        </Section>
      </div>

      <div className="flex items-start gap-2 rounded-xl border border-[var(--ln)] p-3 text-[11px] leading-6 text-[var(--mu)]">
        <Info size={14} className="mt-1 shrink-0" />
        <span>
          بررسی در Core و هنگام ورود هر کاربر به ربات انجام می‌شود، پس با تغییر کد ربات دور زده نمی‌شود. ثبت‌نام و کد
          معرف کاربر حتی پیش از عضویت ذخیره می‌شود و لینک‌های شروع (مثل اتصال حساب) بعد از عضویت دوباره اجرا می‌شوند.
          اگر ربات به کانالی دسترسی نداشته باشد یا تلگرام در دسترس نباشد، آن کانال موقتاً نادیده گرفته می‌شود تا هیچ
          مشتری‌ای پشت در نماند؛ با «بررسی کانال‌ها» این وضعیت را ببینید.
        </span>
      </div>
    </div>
  );
}

function ChannelCard({
  index,
  ch,
  count,
  result,
  onPatch,
  onRemove,
  onMove,
}: {
  index: number;
  ch: ChannelDraft;
  count: number;
  result?: ChannelCheck;
  onPatch: (p: Partial<ChannelDraft>) => void;
  onRemove: () => void;
  onMove: (to: number) => void;
}) {
  const problem = ch.chat.trim() || ch.url.trim() ? channelProblem(ch) : '';
  const priv = isPrivate(ch);
  return (
    <div className="space-y-3 rounded-xl border border-[var(--ln)] p-3" data-testid="channel-card">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-extrabold">
          کانال {index + 1}
          {priv && <span className="ms-2 rounded-md bg-[var(--sf2)] px-1.5 text-[10px] text-[var(--mu)]">خصوصی</span>}
        </span>
        <div className="flex gap-1">
          <button
            type="button"
            className="btn btn-g !p-1.5"
            aria-label="بالاتر"
            disabled={index === 0}
            onClick={() => onMove(index - 1)}
          >
            <ArrowUp size={14} />
          </button>
          <button
            type="button"
            className="btn btn-g !p-1.5"
            aria-label="پایین‌تر"
            disabled={index === count - 1}
            onClick={() => onMove(index + 1)}
          >
            <ArrowDown size={14} />
          </button>
          <button
            type="button"
            className="btn btn-g !p-1.5 text-[var(--bd)]"
            aria-label={`حذف کانال ${index + 1}`}
            onClick={onRemove}
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <Field
          label="شناسهٔ کانال"
          hint="کانال عمومی: یوزرنیم یا لینک کانال · کانال خصوصی: شناسهٔ عددی"
          error={problem}
        >
          <input
            className="inp font-mono text-xs"
            dir="ltr"
            value={ch.chat}
            placeholder="@my_channel"
            aria-invalid={!!problem}
            onChange={(e) => onPatch({ chat: e.target.value })}
          />
        </Field>
        <Field label="عنوان دکمه" hint="خالی = شناسهٔ کانال">
          <input
            className="inp"
            value={ch.title}
            maxLength={64}
            placeholder={result?.telegram_title || parseChat(ch.chat) || 'کانال ما'}
            onChange={(e) => onPatch({ title: e.target.value })}
          />
        </Field>
        <Field label="لینک عضویت" hint={priv ? 'لینک دعوت کانال خصوصی (الزامی)' : 'اختیاری؛ پیش‌فرض ‎t.me/username‎'}>
          <input
            className="inp font-mono text-xs"
            dir="ltr"
            value={ch.url}
            placeholder={priv ? 'https://t.me/+AbCdEf…' : joinUrl({ ...ch, url: '' }) || 'https://t.me/…'}
            onChange={(e) => onPatch({ url: e.target.value })}
          />
        </Field>
      </div>
      {result && (
        <div
          className={`flex items-start gap-2 text-[11px] font-bold ${result.ok ? 'text-[var(--ok)]' : 'text-[var(--wn)]'}`}
        >
          {result.ok ? (
            <CheckCircle2 size={14} className="mt-0.5 shrink-0" />
          ) : (
            <TriangleAlert size={14} className="mt-0.5 shrink-0" />
          )}
          <span>
            {result.ok ? `آماده${result.telegram_title ? ` — «${result.telegram_title}»` : ''}` : result.problem}
          </span>
        </div>
      )}
    </div>
  );
}

function JoinPreview({ draft, defaultMessage }: { draft: Draft; defaultMessage: string }) {
  const channels = draft.channels.filter((c) => !channelProblem(c));
  return (
    <div className="mx-auto max-w-sm space-y-1.5" aria-label="پیش‌نمایش پیام ربات">
      <div className="rounded-2xl rounded-be-sm border border-[var(--ln)] p-3 text-[13px] leading-7">
        <Lock size={13} className="me-1 inline" />
        {draft.message.trim() || defaultMessage}
      </div>
      {channels.map((c, i) => (
        <div key={i} className="rounded-xl border border-[var(--ln)] py-2 text-center text-xs font-bold">
          📢 {(c.title.trim() || parseChat(c.chat) || '').slice(0, 48)} ↗
        </div>
      ))}
      <div className="rounded-xl border border-[var(--ln)] py-2 text-center text-xs font-bold">✅ عضو شدم</div>
    </div>
  );
}
