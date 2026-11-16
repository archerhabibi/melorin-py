import type { Json } from '../../shared/types.ts';
import { Switch } from '../../shared/kit.tsx';

export function Switches({
  p,
  busy,
  hasResellers,
  onToggle,
  onToggleReseller,
}: {
  p?: Json;
  busy?: Json;
  hasResellers?: Json;
  onToggle?: Json;
  onToggleReseller?: Json;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <label className="flex cursor-pointer items-center gap-2 text-xs font-bold">
        <Switch
          checked={p.is_active}
          disabled={busy}
          onChange={(v: Json) => onToggle(p, v)}
          label={`فعال‌سازی ${p.name} در فروشگاه اصلی`}
        />
        {hasResellers ? 'فروشگاه اصلی' : p.is_active ? 'فعال' : 'غیرفعال'}
      </label>
      {hasResellers && (
        <label
          className={`flex cursor-pointer items-center gap-2 text-xs font-bold ${p.is_active ? '' : 'opacity-50'}`}
          title={p.is_active ? '' : 'ابتدا در فروشگاه اصلی فعال کنید'}
        >
          <Switch
            checked={p.is_active && p.reseller_enabled !== false}
            disabled={busy || !p.is_active}
            onChange={(v: Json) => onToggleReseller(p, v)}
            label={`فعال‌سازی ${p.name} برای نمایندگان`}
          />
          نمایندگان
        </label>
      )}
    </div>
  );
}
