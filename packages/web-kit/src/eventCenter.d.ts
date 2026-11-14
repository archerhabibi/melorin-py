import type { Dispatch, SetStateAction } from 'react';

export function useEventCenter(cfg: {
  call: (path: string, init?: RequestInit) => Promise<Response>;
  url: string;
  notify: (msg: string) => void;
  confirm: (msg: string) => Promise<boolean> | boolean;
}): {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any; chat: string; setChat: Dispatch<SetStateAction<string>>; threads: Record<string, string>;
  setThreads: Dispatch<SetStateAction<Record<string, string>>>; enabled: boolean; setEnabled: Dispatch<SetStateAction<boolean>>;
  note: string; setNote: Dispatch<SetStateAction<string>>; busy: string; error: string; failed: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  results: any; check: any; made: any;
  save: () => Promise<void>; test: () => Promise<void>; inspect: () => Promise<void>;
  provision: () => Promise<void>; remove: () => Promise<void>; reload: () => Promise<void>;
};
