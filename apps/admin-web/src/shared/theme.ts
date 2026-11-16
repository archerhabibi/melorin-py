// Theme lives in memory + the OS preference only (no browser storage by policy).
const mq = window.matchMedia?.('(prefers-color-scheme: dark)');
let theme = mq?.matches ? 'dark' : 'light';
const subs = new Set<(t: string) => void>();
const apply = () => {
  document.documentElement.dataset.theme = theme;
  subs.forEach((f) => f(theme));
};
mq?.addEventListener?.('change', (e) => {
  theme = e.matches ? 'dark' : 'light';
  apply();
});
export const getTheme = () => theme;
export const toggleTheme = () => {
  theme = theme === 'dark' ? 'light' : 'dark';
  apply();
};
export const onTheme = (f: (t: string) => void) => {
  subs.add(f);
  return () => {
    subs.delete(f);
  };
};
apply();
