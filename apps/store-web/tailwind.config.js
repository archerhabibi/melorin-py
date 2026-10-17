const c = (v) => `rgb(var(--${v}) / <alpha-value>)`;
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    extend: {
      fontFamily: { sans: ['"Vazirmatn Variable"', 'Vazirmatn', 'Tahoma', 'system-ui', 'sans-serif'] },
      colors: {
        bg: c('bg'), surface: c('surface'), surface2: c('surface2'), ink: c('ink'), muted: c('muted'), line: c('line'),
        primary: c('primary'), onprimary: c('onprimary'), accent: c('accent'), 'accent-soft': c('accent-soft'),
        coral: c('coral'), mint: c('mint'), 'mint-soft': c('mint-soft'), danger: c('danger'), 'danger-soft': c('danger-soft'), navy: c('navy'), tg: c('tg'), tgtext: c('tg-text'),
      },
      borderRadius: { '4xl': '2rem' },
      boxShadow: { soft: '0 1px 2px rgb(var(--shadow) / .06), 0 8px 24px -12px rgb(var(--shadow) / .18)', lift: '0 2px 4px rgb(var(--shadow) / .06), 0 22px 44px -18px rgb(var(--shadow) / .35)' },
    },
  },
  plugins: [],
};
