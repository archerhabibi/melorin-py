export const unitOf: (currency?: string | null) => string;
export function toInt(v: unknown): number | null;
export function percentToBp(v: unknown): number | null;
export function usePlanForm(cfg: { kind: string; rule?: any; onSave: (plan: any) => Promise<void> | void }): {
  model: string;
  setModel: (v: string) => void;
  value: string;
  setValue: (v: string) => void;
  cap: string;
  setCap: (v: string) => void;
  active: boolean;
  setActive: (v: boolean) => void;
  busy: boolean;
  bad: boolean;
  canSave: boolean;
  save: () => Promise<void>;
};
