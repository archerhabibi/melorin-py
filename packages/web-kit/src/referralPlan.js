// Headless logic of one referral plan card (first-purchase reward / later-purchase commission). Admin-web (one store at a time) and
// store-web (the reseller's own store) render their own markup; parsing, validation and the save flow are written once.
// Core validates and stores the plan; percent values are basis points (1000 = 10%).
import { useState } from 'react';
import { toEn } from './format.js';

const UNITS = { IRT: 'تومان', IRR: 'ریال' };
export const unitOf = (currency) => (currency ? UNITS[currency] || currency : '');

/** Typed amounts may use Persian digits; a non-negative integer, or null when empty/invalid. */
export function toInt(v) {
  const s = toEn(v).replace(/[,٬\s]/g, '');
  return /^\d+$/.test(s) ? Number(s) : null;
}

/** "۱۲٫۵" (percent) -> basis points 1250; null when empty/invalid. */
export function percentToBp(v) {
  const s = toEn(v).replace('٫', '.').replace(/\s/g, '');
  return /^\d+(\.\d{1,2})?$/.test(s) ? Math.round(Number(s) * 100) : null;
}

/** @param {{ kind: string, rule?: any, onSave: (plan: any) => Promise<void> | void }} cfg */
export function usePlanForm({ kind, rule, onSave }) {
  const [model, setModel] = useState(rule?.model || 'percent');
  const [value, setValue] = useState(rule ? String(rule.model === 'percent' ? rule.value / 100 : rule.value) : '');
  const [cap, setCap] = useState(rule?.max_amount ? String(rule.max_amount) : '');
  const [active, setActive] = useState(rule ? rule.is_active : true);
  const [busy, setBusy] = useState(false);
  const v = model === 'percent' ? percentToBp(value) : toInt(value);
  const bad = value !== '' && (v == null || (cap !== '' && toInt(cap) == null));
  const canSave = !busy && !bad && value !== '';
  async function save() {
    if (v == null || bad) return;
    setBusy(true);
    try {
      await onSave({ kind, model, value: v, max_amount: cap ? toInt(cap) : null, is_active: active });
    } finally {
      setBusy(false);
    }
  }
  return { model, setModel, value, setValue, cap, setCap, active, setActive, busy, bad, canSave, save };
}
