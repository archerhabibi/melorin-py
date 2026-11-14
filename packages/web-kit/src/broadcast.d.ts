export const TITLE_MAX: number;
export const BODY_MAX: number;
export function usePollWhileQueued(items: { queued?: number }[] | undefined, reload: () => void): boolean;
export function useBroadcastComposer(cfg: {
  post: (payload: { title: string; body: string }) => Promise<Response>;
  confirm: (title: string) => Promise<boolean> | boolean;
  onSent: (result: any) => Promise<void> | void;
}): {
  title: string;
  setTitle: (v: string) => void;
  body: string;
  setBody: (v: string) => void;
  busy: boolean;
  error: string;
  filled: boolean;
  send: () => Promise<void>;
};
