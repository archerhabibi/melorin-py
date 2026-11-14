export function useLoyaltyClub(cfg: {
  call: (path: string, init?: RequestInit) => Promise<Response>;
  url: string | null;
  notify: (msg: string) => void;
}): {
  data: { prog: any; rewards: any; sum: any } | null;
  failed: boolean;
  rev: number;
  load: () => Promise<void>;
  write: (path: string, method: string, payload: unknown, okText: string, failText: string) => Promise<boolean>;
};
export function tiersOf(prog: { tiers: any[]; default_tiers: any[] }): any[];
