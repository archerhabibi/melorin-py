import {
  AlertTriangle,
  Check,
  ExternalLink,
  Info,
  Keyboard,
  MousePointerClick,
  RotateCcw,
  ShieldCheck,
} from 'lucide-react';
import { Field, NumInput, Secret, Toggle, num } from '../../shared/kit.tsx';
import { PRICE_PRESETS, UB_NUM, UB_RENEW, UB_TEXT, botLooksLikeBot, botUrl, ubBot } from './upstreamBot.ts';
import type { Json } from '../../shared/types.ts';
import { Fold, TextOverride, WordChips, PlansEditor } from './UpstreamEditors.tsx';
import { UpstreamGuide } from './UpstreamGuide.tsx';

export function UpstreamBotLink({ ub, setUb, error }: { ub?: Json; setUb?: Json; error?: Json }) {
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
            onChange={(e) => setUb((u: Json) => ({ ...u, bot: e.target.value }))}
            onBlur={() => bot && bot !== typed && setUb((u: Json) => ({ ...u, bot }))}
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
export function UpstreamCredentials({ ub, setUb, show, edit }: { ub?: Json; setUb?: Json; show?: Json; edit?: Json }) {
  const set = (k: Json) => (v: Json) => setUb((u: Json) => ({ ...u, [k]: v }));
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

export function UpstreamSettings({ ub, setUb, err, show }: { ub?: Json; setUb?: Json; err?: Json; show?: Json }) {
  const t = (k: Json) => (v: Json) => setUb((u: Json) => ({ ...u, t: { ...u.t, [k]: v } }));
  const n = (k: Json) => (v: Json) => setUb((u: Json) => ({ ...u, n: { ...u.n, [k]: v } }));
  const r = (k: Json) => (v: Json) => setUb((u: Json) => ({ ...u, r: { ...u.r, [k]: v } }));
  const overrides = Object.keys(UB_TEXT).filter((k) => (ub.t[k] ?? '').trim() && ub.t[k].trim() !== UB_TEXT[k]).length;
  const price = parseInt(String(ub.maxPrice).replace(/\D/g, ''), 10) || 0;
  return (
    <>
      <Field label="سقف مبلغ هر خرید یا تمدید" error={show('maxPrice') || undefined}>
        <NumInput
          value={ub.maxPrice}
          onChange={(v: Json) => setUb((u: Json) => ({ ...u, maxPrice: v }))}
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
            onClick={() => setUb((u: Json) => ({ ...u, maxPrice: String(v) }))}
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
          onChange={(v: Json) => setUb((u: Json) => ({ ...u, renewOn: v }))}
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
                onChange={(v: Json) => setUb((u: Json) => ({ ...u, rWords: v }))}
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
        <PlansEditor
          plans={ub.plans}
          onChange={(v: Json) => setUb((u: Json) => ({ ...u, plans: v }))}
          error={show('plans')}
        />
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
