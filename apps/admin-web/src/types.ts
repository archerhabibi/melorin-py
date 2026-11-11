import type { ReactNode } from 'react';
// Shared structural types for admin-web (TypeScript migration, T-O03 / T-R11).
// Server payloads that are not yet bound to a generated @melorin/api-client schema use these aliases, so every
// remaining loose spot is greppable (`Json`) and can be tightened one view at a time.

/** A JSON object returned by the Core API whose shape is not yet generated into api-client types. */
export type Rec = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
/** Any JSON value from the Core API (to be replaced by generated schema types). */
export type Json = any; // eslint-disable-line @typescript-eslint/no-explicit-any
/** Fetch-like function used by views: authFetch or a test double. */
export type CallFn = (path: string, init?: RequestInit) => Promise<Response>;
/** React children-bearing props helper. */
export type WithChildren<P = unknown> = P & { children?: import('react').ReactNode };
/** Toast notifier supplied by App. */
export type Toast = (msg: string) => void;
/** Entity id as the Core API emits it. */
export type Id = string | number;

/** Row of GET /api/v1/admin/orders (mirrors apps/api/melorin/modules/admin/orders.py). */
export interface AdminOrderRow {
  id: string;
  number: string;
  user_id: string;
  store_id: string;
  status: string;
  total: number;
  currency: string;
  needs_review: boolean;
  created_at: string;
}
