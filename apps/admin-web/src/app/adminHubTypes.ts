// Narrow shapes for the store-hub / panel-access / order-attach screens (instead of the loose aliases in types.ts).
export interface HubApiProp {
  base?: string;
  perms?: string[];
}
export interface StoreRow {
  id: string;
  name: string;
  kind?: string;
}
export interface NoticeCfg {
  traffic_low_levels: number[];
  is_default: boolean;
  daily_digest?: boolean;
  has_owner?: boolean;
}
export interface NoticeTextMeta {
  texts: Record<string, { title: string; body: string }>;
  kinds: string[];
  placeholders: string[];
}
export interface ErrorBody {
  error?: { message?: string };
}
export const errMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));
export const asList = <T>(j: unknown): T[] => (Array.isArray(j) ? (j as T[]) : []);
