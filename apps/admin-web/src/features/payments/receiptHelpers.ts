import { num } from '../../shared/kit.tsx';
import type { Json, Rec } from '../../shared/types.ts';

export const JSON_H = { 'Content-Type': 'application/json' };
export const CUR: Rec = { IRT: 'تومان', IRR: 'ریال' };
export const toInt = (s: Json) => {
  const t = String(s ?? '')
    .replace(/[۰-۹]/g, (d) => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)))
    .replace(/\D/g, '');
  return t === '' ? null : Number(t);
};
export const clock = (sec: Json) => {
  const s = Math.max(0, Math.floor(sec));
  return `${num(Math.floor(s / 60)).padStart(2, '۰')}:${num(s % 60).padStart(2, '۰')}`;
};
export const ago = (sec: Json) => {
  const m = Math.floor(sec / 60);
  if (m < 1) return 'لحظاتی پیش';
  if (m < 60) return `${num(m)} دقیقه پیش`;
  return `${num(Math.floor(m / 60))} ساعت و ${num(m % 60)} دقیقه پیش`;
};
