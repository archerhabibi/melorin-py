// Destination ("مقصد") helpers shared by the server form, the wizard, the panel list and the account drawer.
// A destination is a server slot's `target`: {group_ids} | {user_template_id} | {inbound_ids}; null = the panel's own config.

export const BALANCING = {
  round_robin: ['چرخشی', 'هر فروش جدید به مقصدِ بعدی می‌رود؛ همه‌ی مقصدها سهم برابر دارند.'],
  least_fill: ['کمترین پُری', 'مقصدی که نسبت «اکانت فعال ÷ ظرفیت» آن کمتر است انتخاب می‌شود.'],
  fill_first: ['پُر کردن به ترتیب', 'اول مقصد اول تا پر شدن، بعد مقصد بعدی.'],
};

export const balancingText = (v) => (BALANCING[v] || BALANCING.round_robin)[0];

/** Which kind of destination a target (or a panel kind) is: group | template | inbound | mixed. */
export function targetKind(panelKind, target) {
  if (target?.user_template_id != null) return 'template';
  if (Array.isArray(target?.inbound_ids)) return 'inbound';
  if (Array.isArray(target?.group_ids)) return 'group';
  return panelKind === 'sanaei' ? 'inbound' : panelKind === 'pasarguard' ? 'group' : 'mixed';
}

/** One central place for the capacity label (D7): گروه / تمپلیت / اینباند, or مقصد when unknown. */
export function capacityLabel(panelKind, target) {
  const k = targetKind(panelKind, target);
  return k === 'group'
    ? 'ظرفیت گروه'
    : k === 'template'
      ? 'ظرفیت تمپلیت'
      : k === 'inbound'
        ? 'ظرفیت اینباند'
        : 'ظرفیت مقصد';
}

const faNum = (n) => Number(n).toLocaleString('fa-IR');

/** Short human text for a target, e.g. «گروه ۲، ۳» or «تمپلیت ۵»; names win when a listing is given. */
export function describeTarget(target, listing) {
  if (!target) return 'ارث‌بری از تنظیمات پنل';
  const label = (rows, id, key) => rows?.find((r) => r.id === id)?.[key] || faNum(id);
  if (target.user_template_id != null) return `تمپلیت ${label(listing?.templates, target.user_template_id, 'name')}`;
  if (Array.isArray(target.inbound_ids))
    return `اینباند ${target.inbound_ids.map((i) => label(listing?.inbounds, i, 'remark')).join('، ')}`;
  if (Array.isArray(target.group_ids))
    return `گروه ${target.group_ids.map((i) => label(listing?.groups, i, 'name')).join('، ')}`;
  return 'ارث‌بری از تنظیمات پنل';
}

/** The first line a support agent needs from an account's creation snapshot. */
export function placementSummary(p) {
  if (!p) return null;
  return {
    where: `${p.panel?.name || '—'} · ${p.server?.name || '—'}`,
    target: describeTarget(p.target),
    how: `${p.selected_by === 'manual' ? 'انتخاب مشتری' : 'خودکار'} · ${balancingText(p.balancing)}`,
  };
}

export const ago = (iso) => {
  if (!iso) return 'هنوز تخصیص نیافته';
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 90) return 'همین الان';
  if (s < 5400) return `${faNum(Math.round(s / 60))} دقیقه پیش`;
  if (s < 129600) return `${faNum(Math.round(s / 3600))} ساعت پیش`;
  return `${faNum(Math.round(s / 86400))} روز پیش`;
};
