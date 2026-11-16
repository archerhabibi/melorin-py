import { buildInsights, foldTail } from './reportsLogic.ts';
import type { Json, Toast } from '../../shared/types.ts';
import type { Dispatch, ReactNode, SetStateAction } from 'react';

// Everything the report sections read from ReportsView (state, API payload, derived rows). Each section picks what it needs.
export type ReportModel = {
  days: number;
  setDays: Dispatch<SetStateAction<number>>;
  currency: string;
  setCurrency: Dispatch<SetStateAction<string>>;
  storeId: string;
  setStoreId: Dispatch<SetStateAction<string>>;
  metric: string;
  setMetric: Dispatch<SetStateAction<string>>;
  compare: boolean;
  setCompare: Dispatch<SetStateAction<boolean>>;
  table: boolean;
  setTable: Dispatch<SetStateAction<boolean>>;
  stores: { id: string; name: string }[];
  data: Json;
  err: boolean;
  loading: boolean;
  refresh: () => void;
  exportCsv: (section: string) => void;
  cur: string;
  k: Json;
  s: Json;
  f: Json;
  insights: ReturnType<typeof buildInsights>;
  dim: string;
  mainSeries: { key: string; label: string; values: number[]; color: string; dashed?: boolean; area?: boolean }[];
  unit: string;
  mainTitle: string;
  lead: number[];
  periodTotal: number;
  statusItems: ReturnType<typeof foldTail>;
  split: (
    rows: { key: string; revenue: number }[] | undefined,
    map: Record<string, string>,
  ) => ReturnType<typeof foldTail>;
  total: number;
  productRows: { key: string; label: string; sub?: string; value: number; display?: ReactNode }[];
  storeRows: { key: string; label: string; sub?: string; value: number; display?: ReactNode }[];
  query: string;
  tz: string;
  api: { tick?: number } | undefined;
  toast: Toast;
};
