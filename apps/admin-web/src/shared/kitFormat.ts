import type { Json } from './types.ts';

export const num = (v: Json) => Number(v || 0).toLocaleString('fa-IR');
export const tint = (t: Json) => ({ background: `var(--${t}b, var(--mb))`, color: `var(--${t}, var(--mu))` });
/** Tone for a capacity ratio: red ≥100%, amber ≥80%, green otherwise. */
export const capTone = (u: Json) => (u >= 1 ? 'bd' : u >= 0.8 ? 'wn' : 'ok');

// Accept Persian / Arabic-Indic digits typed by the admin and normalise them to ASCII.
export const toEn = (s: Json) =>
  String(s ?? '')
    .replace(/[۰-۹]/g, (d) => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)))
    .replace(/[٠-٩]/g, (d) => String('٠١٢٣٤٥٦٧٨٩'.indexOf(d)));
export const digits = (s: Json) => toEn(s).replace(/\D/g, '');
