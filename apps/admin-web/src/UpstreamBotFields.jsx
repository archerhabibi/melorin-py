import { useState } from 'react';
import {
  AlertTriangle,
  Bot,
  Check,
  ChevronDown,
  ChevronLeft,
  CornerDownLeft,
  ExternalLink,
  Info,
  Keyboard,
  KeyRound,
  MousePointerClick,
  Plus,
  RotateCcw,
  ShieldCheck,
  Terminal,
  Trash2,
  X,
} from 'lucide-react';
import { CopyButton, Field, NumInput, Section, Secret, Segmented, Toggle, num, tint } from './kit.jsx';
import {
  PRICE_PRESETS,
  UB_NUM,
  UB_RENEW,
  UB_TEXT,
  botLooksLikeBot,
  botUrl,
  parseBot,
  ubBot,
  ubFlows,
} from './upstreamBot.js';

// Everything the admin needs to configure an `upstream_bot` panel (a parent Telegram bot without an API that Melorin
// drives through a dedicated Telegram user session). The pure logic (defaults, validation, payload) is in upstreamBot.js.

// ---------- bot link (replaces the generic "panel URL" field) ----------
export function UpstreamBotLink({ ub, setUb, error }) {
  const bot = ubBot(ub),
    typed = String(ub.bot ?? '').trim();
  return (
    <Field
      label="ربات والد (که اکانت را تحویل می‌دهد)"
      error={error}
      hint="نام کاربری یا لینک ربات را بچسبانید؛ فرمت @name، name یا https://t.me/name هر سه پذیرفته می‌شود"
    >
      <div className="flex items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <input
            dir="ltr"
            spellCheck={false}
            autoComplete="off"
            className="inp !pl-[3.6rem]"
            value={ub.bot}
            placeholder="parent_bot"
            aria-label="نام کاربری ربات والد"
            onChange={(e) => setUb((u) => ({ ...u, bot: e.target.value }))}
            onBlur={() => bot && bot !== typed && setUb((u) => ({ ...u, bot }))}
          />
          <span
            dir="ltr"
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 font-mono text-[11px] font-bold text-[var(--mu)]"
          >
            t.me/
          </span>
        </div>
        {bot && (
          <a
            className="btn btn-g !px-2"
            href={botUrl(bot)}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="باز کردن ربات در تلگرام"
            title="باز کردن ربات در تلگرام"
          >
            <ExternalLink size={14} />
          </a>
        )}
      </div>
      {bot && !botLooksLikeBot(bot) && (
        <span className="mt-1.5 flex items-start gap-1.5 text-[11px] font-normal leading-5 text-[var(--wn)]">
          <AlertTriangle size={12} className="mt-1 shrink-0" />
          نام کاربری ربات‌های تلگرام معمولاً به «bot» ختم می‌شود؛ مطمئن شوید این همان ربات والد است.
        </span>
      )}
    </Field>
  );
}

// ---------- credentials ----------
function Step({ n, children }) {
  return (
    <li className="flex items-start gap-2.5">
      <span className="sec-n mt-0.5 shrink-0">{n}</span>
      <span className="min-w-0 flex-1 leading-6">{children}</span>
    </li>
  );
}
function Cmd({ text }) {
  return (
    <span className="mt-1 flex items-center gap-1.5">
      <code
        dir="ltr"
        className="min-w-0 flex-1 break-all rounded-lg bg-[var(--sf2)] px-2.5 py-1.5 font-mono text-[11px]"
        title={text}
      >
        {text}
      </code>
      <CopyButton text={text} label="کپی دستور" />
    </span>
  );
}

export function UpstreamGuide() {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl border border-[var(--hair)] bg-[var(--sf2)]">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-xs font-bold"
      >
        <Terminal size={14} className="text-[var(--in)]" />
        راهنمای گرفتن api_id، api_hash و session
        <ChevronDown size={14} className={`mr-auto text-[var(--mu)] ${open ? '' : '-rotate-90'}`} />
      </button>
      {open && (
        <ol className="space-y-3 border-t border-[var(--hair)] px-3 py-3 text-xs">
          <Step n="۱">
            یک اکانت تلگرام <b>جداگانه</b> بسازید (نه شماره‌ی شخصی) و از همان اکانت، کیف پول ربات والد را شارژ کنید.
          </Step>
          <Step n="۲">
            در{' '}
            <a
              className="font-bold text-[var(--ac)] underline"
              dir="ltr"
              href="https://my.telegram.org/apps"
              target="_blank"
              rel="noopener noreferrer"
            >
              my.telegram.org/apps
            </a>{' '}
            با همان شماره وارد شوید و یک اپلیکیشن بسازید؛ <b>api_id</b> و <b>api_hash</b> همان‌جا نمایش داده می‌شود.
          </Step>
          <Step n="۳">
            روی سروری که کد پروژه دارد، اسکریپت ورود را اجرا کنید؛ شماره، کد تلگرام و (در صورت وجود) رمز دومرحله‌ای را
            می‌پرسد:
            <Cmd text="pip install telethon" />
            <Cmd text="python scripts/upstream_bot_login.py" />
          </Step>
          <Step n="۴">
            خروجی آخر اسکریپت (رشته‌ی طولانی <b>StringSession</b>) را در فیلد «Session» بچسبانید.
          </Step>
          <li className="flex items-start gap-2 rounded-lg bg-[var(--wnb)] p-2.5 leading-6 text-[var(--wn)]">
            <AlertTriangle size={14} className="mt-1 shrink-0" />
            Session دسترسی کامل به آن اکانت تلگرام است؛ مثل رمز عبور نگه دارید و جایی منتشر نکنید. اگر لو رفت، از
            تنظیمات تلگرام (Devices) نشست را ببندید و دوباره بگیرید.
          </li>
        </ol>
      )}
    </div>
  );
}

/** The three secrets, shown only while they are being (re)entered. All three are required together: the API replaces the whole secret. */
export function UpstreamCredentials({ ub, setUb, show, edit }) {
  const set = (k) => (v) => setUb((u) => ({ ...u, [k]: v }));
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="api_id" error={show('apiId') || undefined}>
          <input
            dir="ltr"
            inputMode="numeric"
            autoComplete="off"
            className="inp"
            value={ub.apiId}
            placeholder="1234567"
            onChange={(e) => set('apiId')(e.target.value.replace(/[^\d۰-۹٠-٩]/g, ''))}
          />
        </Field>
        <Field label="api_hash" error={show('apiHash') || undefined}>
          <Secret value={ub.apiHash} onChange={set('apiHash')} placeholder="0123456789abcdef0123456789abcdef" />
        </Field>
      </div>
      <Field label="Session (Telethon StringSession)" error={show('session') || undefined}>
        <Secret value={ub.session} onChange={set('session')} placeholder="1BVtsOKEBu7..." />
      </Field>
      {edit && (
        <p className="flex items-start gap-2 text-[11px] leading-5 text-[var(--mu)]">
          <Info size={13} className="mt-1 shrink-0" />
          هر سه مقدار با هم جایگزین اعتبارنامه‌ی ذخیره‌شده می‌شوند؛ اگر فقط تنظیمات را عوض می‌کنید، «انصراف از تغییر
          اعتبارنامه» را بزنید.
        </p>
      )}
      <UpstreamGuide />
    </>
  );
}

// ---------- settings ----------
function Fold({ title, hint, badge, children, defaultOpen = false, Icon }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-[var(--hair)]">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-xs font-bold"
      >
        {Icon && <Icon size={14} className="text-[var(--mu)]" />}
        {title}
        {badge}
        <ChevronDown size={14} className={`mr-auto text-[var(--mu)] ${open ? '' : '-rotate-90'}`} />
      </button>
      {open && (
        <div className="space-y-4 border-t border-[var(--hair)] px-3 py-3">
          {hint && <p className="text-[11px] leading-5 text-[var(--mu)]">{hint}</p>}
          {children}
        </div>
      )}
    </div>
  );
}

/** Text override: empty = adapter default (shown as placeholder), a reset button appears once it is changed. */
function TextOverride({ label, def, value, onChange, error, hint, ltr = false }) {
  const changed = !!(value ?? '').trim() && value.trim() !== def;
  return (
    <Field label={label} error={error} hint={hint}>
      <div className="relative">
        <input
          dir={ltr ? 'ltr' : 'auto'}
          spellCheck={false}
          className={`inp ${changed ? '!pl-9' : ''}`}
          value={value ?? ''}
          placeholder={def}
          onChange={(e) => onChange(e.target.value)}
        />
        {changed && (
          <button
            type="button"
            aria-label={`بازگشت به پیش‌فرض: ${def}`}
            title={`بازگشت به پیش‌فرض: ${def}`}
            onClick={() => onChange('')}
            className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--mu)] hover:text-[var(--tx)]"
          >
            <RotateCcw size={14} />
          </button>
        )}
      </div>
    </Field>
  );
}

function WordChips({ values, onChange, placeholder }) {
  const [t, setT] = useState('');
  const add = () => {
    const w = t.trim();
    if (w && !values.includes(w)) onChange([...values, w]);
    setT('');
  };
  return (
    <div className="inp flex flex-wrap items-center gap-1.5 !py-1.5">
      {values.map((w) => (
        <span
          key={w}
          className="inline-flex items-center gap-1 rounded-md bg-[var(--mb)] px-2 py-0.5 text-xs font-bold"
        >
          {w}
          <button type="button" aria-label={`حذف ${w}`} onClick={() => onChange(values.filter((x) => x !== w))}>
            <X size={12} />
          </button>
        </span>
      ))}
      <input
        dir="auto"
        className="min-w-[8rem] flex-1 bg-transparent py-1 text-sm outline-hidden"
        value={t}
        placeholder={values.length ? '' : placeholder}
        onChange={(e) => setT(e.target.value)}
        onBlur={add}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ',' || e.key === '،') {
            e.preventDefault();
            add();
          } else if (e.key === 'Backspace' && !t && values.length) onChange(values.slice(0, -1));
        }}
      />
    </div>
  );
}

function PlansEditor({ plans, onChange, error }) {
  const upd = (i, k, v) => onChange(plans.map((p, j) => (j === i ? { ...p, [k]: v } : p)));
  return (
    <div className="space-y-2">
      {plans.length === 0 && (
        <p className="text-[11px] leading-5 text-[var(--mu)]">
          بدون پلن دستی: دکمه‌ی پلن از روی متن خودِ ربات والد (مثل «10 گیگ یک ماهه 60,000 تومان») خوانده می‌شود. فقط اگر
          متن دکمه‌ها غیرعادی است پلن دستی تعریف کنید.
        </p>
      )}
      {plans.map((p, i) => (
        <div key={i} className="grid grid-cols-[5.5rem_4.5rem_1fr_auto] items-end gap-2">
          <Field label={i === 0 ? 'حجم (GB)' : ' '}>
            <input
              dir="ltr"
              inputMode="decimal"
              className="inp"
              aria-label={`حجم پلن ${i + 1}`}
              value={p.traffic_gb}
              placeholder="10"
              onChange={(e) => upd(i, 'traffic_gb', e.target.value.replace(/[^\d.٫۰-۹٠-٩]/g, ''))}
            />
          </Field>
          <Field label={i === 0 ? 'ماه' : ' '}>
            <input
              dir="ltr"
              inputMode="numeric"
              className="inp"
              aria-label={`ماه پلن ${i + 1}`}
              value={p.months}
              placeholder="1"
              onChange={(e) => upd(i, 'months', e.target.value.replace(/[^\d۰-۹٠-٩]/g, ''))}
            />
          </Field>
          <Field label={i === 0 ? 'متن دکمه‌ی پلن در ربات' : ' '}>
            <input
              dir="auto"
              className="inp"
              aria-label={`متن دکمه پلن ${i + 1}`}
              value={p.label}
              placeholder="10 گیگ یک ماهه"
              onChange={(e) => upd(i, 'label', e.target.value)}
            />
          </Field>
          <button
            type="button"
            className="btn btn-g mb-0.5 !px-2"
            aria-label={`حذف پلن ${i + 1}`}
            onClick={() => onChange(plans.filter((_, j) => j !== i))}
          >
            <Trash2 size={14} />
          </button>
        </div>
      ))}
      {error && <p className="text-[11px] text-[var(--bd)]">{error}</p>}
      <button
        type="button"
        className="btn btn-g"
        onClick={() => onChange([...plans, { traffic_gb: '', months: '1', label: '' }])}
      >
        <Plus size={13} />
        افزودن پلن
      </button>
    </div>
  );
}

const fmt = (n) => (n > 0 ? num(n) : '—');

export function UpstreamSettings({ ub, setUb, err, show }) {
  const t = (k) => (v) => setUb((u) => ({ ...u, t: { ...u.t, [k]: v } }));
  const n = (k) => (v) => setUb((u) => ({ ...u, n: { ...u.n, [k]: v } }));
  const r = (k) => (v) => setUb((u) => ({ ...u, r: { ...u.r, [k]: v } }));
  const overrides = Object.keys(UB_TEXT).filter((k) => (ub.t[k] ?? '').trim() && ub.t[k].trim() !== UB_TEXT[k]).length;
  const price = parseInt(String(ub.maxPrice).replace(/\D/g, ''), 10) || 0;
  return (
    <>
      <Field label="سقف مبلغ هر خرید یا تمدید" error={show('maxPrice') || undefined}>
        <NumInput
          value={ub.maxPrice}
          onChange={(v) => setUb((u) => ({ ...u, maxPrice: v }))}
          suffix="تومان"
          placeholder="100,000"
          aria-label="سقف مبلغ هر خرید یا تمدید"
        />
      </Field>
      <div className="-mt-1 flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] text-[var(--mu)]">پیشنهاد:</span>
        {PRICE_PRESETS.map((v) => (
          <button
            key={v}
            type="button"
            aria-pressed={price === v}
            className={`btn btn-g !py-1 !text-xs ${price === v ? '!border-[var(--ac)]' : ''}`}
            onClick={() => setUb((u) => ({ ...u, maxPrice: String(v) }))}
          >
            {price === v && <Check size={12} />}
            {num(v)}
          </button>
        ))}
      </div>
      <p className="flex items-start gap-2 rounded-lg bg-[var(--inb)] p-3 text-[11px] leading-5 text-[var(--in)]">
        <ShieldCheck size={14} className="mt-0.5 shrink-0" />
        سقف ایمنی پول شماست: اگر مبلغِ صفحه‌ی تایید ربات والد با قیمت پلن فرق کند یا از این سقف بیشتر باشد، خرید یا
        تمدید قبل از پرداخت لغو می‌شود. آن را کمی بالاتر از گران‌ترین پلنی که می‌فروشید بگذارید.
      </p>

      <Fold
        title="تمدید خودکار"
        Icon={RotateCcw}
        defaultOpen
        badge={<span className={`badge ${ub.renewOn ? 'b-ok' : 'b-mu'} mr-1`}>{ub.renewOn ? 'فعال' : 'غیرفعال'}</span>}
      >
        <Toggle
          checked={ub.renewOn}
          onChange={(v) => setUb((u) => ({ ...u, renewOn: v }))}
          label="تمدید از طریق ربات والد"
          hint="روشن: درخواست تمدید مشتری با «تمدید با حجم اولیه» در ربات والد انجام می‌شود (بسته از همان لحظه دوباره شروع می‌شود و روزهای باقی‌مانده اضافه نمی‌شود). خاموش: تمدید این پنل دستی/ردشده می‌ماند."
        />
        {ub.renewOn && (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              <TextOverride
                label="دکمه‌ی تمدید"
                def={UB_RENEW.renew_button}
                value={ub.r.renew_button}
                onChange={r('renew_button')}
              />
              <TextOverride
                label="دکمه‌ی تایید تمدید"
                def={UB_RENEW.confirm_button}
                value={ub.r.confirm_button}
                onChange={r('confirm_button')}
              />
              <TextOverride
                label="دکمه‌ی انصراف/بازگشت"
                def={UB_RENEW.cancel_button}
                value={ub.r.cancel_button}
                onChange={r('cancel_button')}
              />
            </div>
            <Field
              label="عبارت‌های پیام موفقیت تمدید"
              hint={`خالی = «${UB_RENEW.success_words.join('، ')}» · با Enter اضافه کنید`}
            >
              <WordChips
                values={ub.rWords}
                onChange={(v) => setUb((u) => ({ ...u, rWords: v }))}
                placeholder={UB_RENEW.success_words[0]}
              />
            </Field>
            <Field
              label="بازه‌ی انتظار پس از تایید"
              error={show('settle_window') || undefined}
              hint="اگر بعد از زدن تایید پاسخی نیامد، تا این مدت دوباره پرداخت نمی‌شود (به‌جای آن وضعیت اکانت خوانده می‌شود)"
            >
              <NumInput
                value={ub.r.settle_window ?? ''}
                onChange={r('settle_window')}
                suffix="ثانیه"
                placeholder={String(UB_RENEW.settle_window)}
              />
            </Field>
          </>
        )}
      </Fold>

      <Fold
        title="متن دکمه‌های ربات والد"
        Icon={MousePointerClick}
        defaultOpen={overrides > 0}
        badge={overrides ? <span className="badge b-wn mr-1">{num(overrides)} تغییر</span> : null}
        hint="خالی = پیش‌فرض. اگر ربات والد منوها را تغییر داد، همین‌جا اصلاح کنید؛ دکمه‌ها با «شامل این متن بودن» پیدا می‌شوند، پس ایموجی لازم نیست."
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <TextOverride
            label="دستور شروع"
            def={UB_TEXT.start_command}
            value={ub.t.start_command}
            onChange={t('start_command')}
            error={show('start_command') || undefined}
            ltr
          />
          <TextOverride label="منوی خرید" def={UB_TEXT.menu_buy} value={ub.t.menu_buy} onChange={t('menu_buy')} />
          <TextOverride
            label="دکمه‌ی سرویس"
            def={UB_TEXT.service_button}
            value={ub.t.service_button}
            onChange={t('service_button')}
          />
          <TextOverride
            label="تایید خرید"
            def={UB_TEXT.confirm_button}
            value={ub.t.confirm_button}
            onChange={t('confirm_button')}
          />
          <TextOverride
            label="انصراف از خرید"
            def={UB_TEXT.cancel_button}
            value={ub.t.cancel_button}
            onChange={t('cancel_button')}
          />
          <TextOverride
            label="منوی خریدهای من"
            def={UB_TEXT.menu_purchases}
            value={ub.t.menu_purchases}
            onChange={t('menu_purchases')}
          />
          <TextOverride
            label="جستجوی اکانت"
            def={UB_TEXT.search_button}
            value={ub.t.search_button}
            onChange={t('search_button')}
          />
          <TextOverride
            label="دکمه‌ی لینک"
            def={UB_TEXT.link_button}
            value={ub.t.link_button}
            onChange={t('link_button')}
          />
          <TextOverride
            label="مرجوعی اکانت"
            def={UB_TEXT.refund_button}
            value={ub.t.refund_button}
            onChange={t('refund_button')}
          />
          <TextOverride
            label="تایید مرجوعی"
            def={UB_TEXT.refund_confirm_button}
            value={ub.t.refund_confirm_button}
            onChange={t('refund_confirm_button')}
          />
        </div>
      </Fold>

      <Fold
        title="پلن‌های دستی (اختیاری)"
        Icon={Keyboard}
        defaultOpen={ub.plans.length > 0}
        badge={ub.plans.length ? <span className="badge b-in mr-1">{num(ub.plans.length)}</span> : null}
      >
        <PlansEditor plans={ub.plans} onChange={(v) => setUb((u) => ({ ...u, plans: v }))} error={show('plans')} />
      </Fold>

      <Fold
        title="زمان‌بندی"
        Icon={RotateCcw}
        hint="پیش‌فرض‌ها برای اغلب ربات‌ها مناسب است؛ فقط اگر ربات والد کند است تغییر دهید."
      >
        <div className="grid gap-3 sm:grid-cols-3">
          <Field
            label="اعتبار وضعیت زنده"
            error={show('status_ttl') || undefined}
            hint="نتیجه‌ی خواندن صفحه‌ی اکانت این مدت دوباره استفاده می‌شود"
          >
            <NumInput
              value={ub.n.status_ttl ?? ''}
              onChange={n('status_ttl')}
              suffix="ثانیه"
              placeholder={String(UB_NUM.status_ttl)}
            />
          </Field>
          <Field
            label="مهلت هر مرحله"
            error={show('step_timeout') || undefined}
            hint="انتظار برای پاسخ ربات به یک کلیک"
          >
            <NumInput
              value={ub.n.step_timeout ?? ''}
              onChange={n('step_timeout')}
              suffix="ثانیه"
              placeholder={String(UB_NUM.step_timeout)}
            />
          </Field>
          <Field
            label="مهلت تحویل"
            error={show('delivery_timeout') || undefined}
            hint="انتظار برای پیام تحویل/نتیجه بعد از تایید"
          >
            <NumInput
              value={ub.n.delivery_timeout ?? ''}
              onChange={n('delivery_timeout')}
              suffix="ثانیه"
              placeholder={String(UB_NUM.delivery_timeout)}
            />
          </Field>
        </div>
        <p className="text-[11px] leading-5 text-[var(--mu)]">
          فقط یک جریان در هر لحظه با ربات والد انجام می‌شود (قفل توزیع‌شده)؛ خریدها به‌ترتیب صف می‌شوند.
        </p>
      </Fold>
    </>
  );
}

// ---------- live preview of what the userbot does ----------
const STEP = {
  cmd: { Icon: Terminal, tone: 'mu', mono: true },
  btn: { Icon: MousePointerClick, tone: 'in' },
  in: { Icon: Keyboard, tone: 'mu' },
  chk: { Icon: ShieldCheck, tone: 'wn' },
  out: { Icon: CornerDownLeft, tone: 'ok' },
};

export function UpstreamFlowPreview({ ub }) {
  const flows = ubFlows(ub),
    [id, setId] = useState('buy'),
    flow = flows.find((x) => x.id === id) || flows[0];
  return (
    <>
      <Segmented
        label="اقدام"
        value={flow.id}
        onChange={setId}
        options={flows.map((x) => [x.id, x.off ? `${x.title} (خاموش)` : x.title])}
      />
      <ol
        className={`flex flex-wrap items-center gap-y-2 ${flow.off ? 'opacity-45' : ''}`}
        aria-label={`مسیر ${flow.title} در ربات والد`}
      >
        {flow.steps.map((s, i) => {
          const m = STEP[s.k];
          return (
            <li key={i} className="flex items-center">
              <span className="spec" style={tint(m.tone)}>
                <m.Icon size={12} className="shrink-0" />
                <span dir={m.mono ? 'ltr' : 'auto'} className={m.mono ? 'font-mono' : ''}>
                  {s.l}
                </span>
              </span>
              {i < flow.steps.length - 1 && (
                <ChevronLeft size={14} className="mx-1 shrink-0 text-[var(--mu)]" aria-hidden />
              )}
            </li>
          );
        })}
      </ol>
      <p className="text-[11px] leading-5 text-[var(--mu)]">
        هر جریان با <b dir="ltr">{(ub.t.start_command || UB_TEXT.start_command).trim() || UB_TEXT.start_command}</b>{' '}
        شروع می‌شود. دکمه‌های آبی روی منوی خودِ ربات والد زده می‌شوند و نیازی به تایپ دستی ندارند؛ موارد زرد بررسی ایمنی
        قبل از پرداخت‌اند.
      </p>
    </>
  );
}

export function UpstreamFlowSection({ ub }) {
  return (
    <Section
      title="پیش‌نمایش مسیر در ربات والد"
      hint="این همان مسیری است که اکانت تلگرام اختصاصی مثل یک مشتری طی می‌کند؛ با تغییر متن دکمه‌ها زنده به‌روز می‌شود."
    >
      <UpstreamFlowPreview ub={ub} />
    </Section>
  );
}

// ---------- panel card ----------
/** Facts for the panel card header (what this panel is allowed to do). */
export function UpstreamSpecs({ summary }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
      <span className="spec" style={tint('in')}>
        <Bot size={12} />
        <span dir="ltr">@{summary.bot}</span>
      </span>
      <span className="spec" title="سقف مبلغ هر خرید یا تمدید">
        <ShieldCheck size={12} />
        سقف خرید: <b className="num">{fmt(summary.maxPrice)}</b> تومان
      </span>
      <span className="spec" style={tint(summary.renewOn ? 'ok' : 'mu')}>
        <RotateCcw size={12} />
        تمدید {summary.renewOn ? 'فعال' : 'غیرفعال'}
      </span>
      {summary.plans > 0 && (
        <span className="spec">
          <Keyboard size={12} />
          {num(summary.plans)} پلن دستی
        </span>
      )}
      <span className="spec" title="این پنل تعلیق و ازسرگیری ندارد">
        <KeyRound size={12} />
        بدون تعلیق
      </span>
    </div>
  );
}

export { parseBot };
