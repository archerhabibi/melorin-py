import { useEffect, useMemo, useRef, useState } from 'react';
import { Boxes, ChevronDown, Save } from 'lucide-react';
import type { CallFn, Json } from '../../shared/types.ts';
import type { StoreRow } from '../../app/adminHubTypes.ts';
import { Drawer, Field, NumInput, Section, Segmented, Toggle, DeleteButton, tint } from '../../shared/kit.tsx';
import { focusOnMount } from '../../shared/useDialog.ts';
import ProductAvailability from './ProductAvailability.tsx';
import { CUR, dur, EMPTY, fromProduct, payload, validate } from './productsShared.tsx';

export function ProductDrawer({
  product,
  products,
  hasResellers,
  onClose,
  onSubmit,
  onDelete,
  call,
  stores,
  toast,
}: {
  call?: CallFn;
  stores?: StoreRow[];
  toast?: (m: string) => void;
  product?: Json;
  products?: Json;
  hasResellers?: Json;
  onClose?: Json;
  onSubmit?: Json;
  onDelete?: Json;
}) {
  const edit = !!product;
  const taken = useMemo(
    () => new Set((products || []).filter((x: Json) => x.id !== product?.id).map((x: Json) => x.code)),
    [products, product],
  );
  const suggestCode = (f: Json) => {
    const base = `vpn-${+f.duration_days || 0}d-${f.unlimited_traffic ? 'unl' : `${+f.traffic_gb || 0}g`}`;
    let code = base,
      n = 2;
    while (taken.has(code)) code = `${base}-${n++}`;
    return code;
  };
  const [f, setF] = useState(() => (product ? fromProduct(product) : { ...EMPTY, code: suggestCode(EMPTY) }));
  const base = useRef(JSON.stringify(f));
  const [tried, setTried] = useState(false),
    [busy, setBusy] = useState(false),
    [srv, setSrv] = useState('');
  const [codeTouched, setCodeTouched] = useState(edit),
    [more, setMore] = useState(false);
  const set = (k: Json) => (v: Json) => {
    setSrv('');
    setF((x) => ({ ...x, [k]: v }));
  };
  // New product: the code follows the plan (duration + traffic) until the admin edits it by hand.
  useEffect(() => {
    if (!edit && !codeTouched) setF((x) => ({ ...x, code: suggestCode(x) }));
  }, [f.duration_days, f.traffic_gb, f.unlimited_traffic, codeTouched, edit, taken]); // eslint-disable-line react-hooks/exhaustive-deps
  const err = useMemo(() => validate(f), [f]);
  const dirty = JSON.stringify(f) !== base.current;
  const submit = async () => {
    setTried(true);
    if (Object.keys(err).length) {
      if (err.code) setMore(true);
      return;
    }
    setBusy(true);
    const m = await onSubmit(payload(f), f.is_active, product);
    setBusy(false);
    if (m) setSrv(m);
  };
  const show = (k: Json) => tried && err[k];
  return (
    <Drawer
      title={edit ? `ویرایش «${product.name}»` : 'افزودن محصول'}
      subtitle={edit ? `کد ${product.code}` : 'مدت، حجم و قیمت فروشگاه'}
      icon={
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={tint('ok')}>
          <Boxes size={20} />
        </span>
      }
      dirty={dirty}
      busy={busy}
      onClose={onClose}
      error={srv}
      footer={
        <button className="btn !py-2 !text-sm" disabled={busy} onClick={submit}>
          <Save size={15} />
          {busy ? 'در حال ذخیره…' : edit ? 'ذخیره تغییرات' : 'ساخت محصول'}
        </button>
      }
      danger={edit && <DeleteButton label="حذف محصول" busy={busy} onClick={() => onDelete(product)} />}
    >
      <Section title="مشخصات">
        <Field label="نام محصول" error={show('name')}>
          <input
            ref={focusOnMount}
            className="inp"
            maxLength={200}
            placeholder="مثلاً: ۳۰ روزه ۵۰ گیگ"
            value={f.name}
            onChange={(e) => set('name')(e.target.value)}
          />
        </Field>
        <Field label="مدت اعتبار" error={show('duration_days')}>
          <div className="space-y-2">
            <div className="flex flex-wrap gap-1.5">
              {[7, 30, 60, 90, 180, 365].map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => set('duration_days')(String(d))}
                  className={`btn btn-g ${+f.duration_days === d ? '!border-[var(--ac)] !text-[var(--ac)]' : ''}`}
                >
                  {dur(d)}
                </button>
              ))}
            </div>
            <NumInput value={f.duration_days} onChange={set('duration_days')} suffix="روز" />
          </div>
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="حجم ترافیک" error={show('traffic_gb')}>
            <div className="space-y-2">
              <NumInput
                value={f.unlimited_traffic ? '' : f.traffic_gb}
                disabled={f.unlimited_traffic}
                placeholder={f.unlimited_traffic ? 'نامحدود' : ''}
                onChange={set('traffic_gb')}
                suffix="گیگ"
              />
              <Toggle checked={f.unlimited_traffic} onChange={set('unlimited_traffic')} label="نامحدود" />
            </div>
          </Field>
          <Field label="تعداد دستگاه هم‌زمان" error={show('max_devices')}>
            <div className="space-y-2">
              <NumInput
                value={f.unlimited_devices ? '' : f.max_devices}
                disabled={f.unlimited_devices}
                placeholder={f.unlimited_devices ? 'بدون محدودیت' : ''}
                onChange={set('max_devices')}
                suffix="دستگاه"
              />
              <Toggle checked={f.unlimited_devices} onChange={set('unlimited_devices')} label="بدون محدودیت" />
            </div>
          </Field>
        </div>
      </Section>
      <Section
        title="قیمت فروشگاه"
        hint={
          hasResellers
            ? 'قیمت نماینده و قیمت هر بسته از صفحه‌ی «بسته‌های فروش» تنظیم می‌شود؛ قیمت فروش هر نماینده را خودش تعیین می‌کند.'
            : 'قیمت هر بسته را هم می‌توانید از صفحه‌ی «بسته‌های فروش» جدا تنظیم کنید.'
        }
      >
        <div className="grid gap-4 sm:grid-cols-[auto_1fr]">
          <Field label="واحد پول">
            <Segmented label="واحد پول" value={f.currency} onChange={set('currency')} options={Object.entries(CUR)} />
          </Field>
          <Field label="قیمت فروشگاه" error={show('main_price')}>
            <NumInput value={f.main_price} onChange={set('main_price')} suffix={CUR[f.currency]} />
          </Field>
        </div>
      </Section>
      <Section
        title="وضعیت"
        hint="این محصول به‌صورت پیش‌فرض در همه‌ی بسته‌های فروش فعال است. هر بسته را می‌توانید از صفحه‌ی همان بسته پنهان کنید."
      >
        <Toggle
          checked={f.is_active}
          onChange={set('is_active')}
          label="فعال در فروشگاه اصلی"
          hint={
            hasResellers
              ? 'با غیرفعال‌کردن، برای نمایندگان هم نمایش داده نمی‌شود.'
              : 'محصول غیرفعال برای خرید جدید نمایش داده نمی‌شود.'
          }
        />
        {hasResellers && (
          <div className={f.is_active ? '' : 'pointer-events-none opacity-50'}>
            <Toggle
              checked={f.is_active && f.reseller_enabled}
              onChange={set('reseller_enabled')}
              label="فعال برای نمایندگان"
              hint={
                f.is_active
                  ? 'خاموش = فقط فروشگاه اصلی این محصول را می‌فروشد.'
                  : 'ابتدا محصول را در فروشگاه اصلی فعال کنید.'
              }
            />
          </div>
        )}
      </Section>
      <section>
        <button
          type="button"
          className="flex items-center gap-1.5 text-xs font-bold text-[var(--mu)]"
          aria-expanded={more}
          onClick={() => setMore(!more)}
        >
          <ChevronDown size={14} className={more ? '' : '-rotate-90'} />
          کد، دسته‌بندی و توضیح
          <span dir="ltr" className="font-mono font-normal">
            {f.code}
          </span>
          {f.is_test && <span className="badge b-wn">تست</span>}
        </button>
        {more && (
          <div className="mt-3 space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                label="کد محصول"
                error={show('code')}
                hint={
                  edit
                    ? 'تغییر کد روی اتصال‌های بیرونی (API/بات) اثر می‌گذارد.'
                    : 'خودکار از مدت و حجم ساخته می‌شود؛ در صورت نیاز ویرایش کنید.'
                }
              >
                <input
                  dir="ltr"
                  spellCheck={false}
                  className="inp font-mono"
                  maxLength={50}
                  value={f.code}
                  onChange={(e) => {
                    setCodeTouched(true);
                    set('code')(e.target.value);
                  }}
                />
              </Field>
              <Field label="دسته‌بندی" hint="اختیاری">
                <input
                  className="inp"
                  maxLength={100}
                  value={f.category}
                  onChange={(e) => set('category')(e.target.value)}
                />
              </Field>
            </div>
            <Field label="توضیحات" hint="اختیاری">
              <input className="inp" value={f.description} onChange={(e) => set('description')(e.target.value)} />
            </Field>
            <Toggle
              checked={f.is_test}
              onChange={set('is_test')}
              label="محصول آزمایشی (تست)"
              hint="برای اکانت‌های آزمایشی؛ برای فروش عادی خاموش بماند."
            />
          </div>
        )}
      </section>
      {edit && call && (
        <ProductAvailability call={call} productId={product.id} stores={stores || []} toast={toast ?? (() => {})} />
      )}
    </Drawer>
  );
}
