# Store Website

Next.js/React/TypeScript channel boundary specified by `docs/11-Channel-Specifications.md`.

Required pages: landing, services/catalog, FAQ/education/rules, guest checkout, payment/receipt, order status, dashboard, VPN accounts, wallet/transactions, referral, Telegram linking, tickets and Web Notifications. Use `packages/api-client`; never access PostgreSQL or duplicate Core rules.

## Design system v2
- Tokens (light/dark) live in `src/styles.css`; Tailwind maps them in `tailwind.config.js`. Theme toggle persists in `localStorage` (`melorin-theme`).
- Shared primitives (Modal, Toast, StatusBadge, Empty/Loading, ThemeToggle) are in `src/ui.jsx`.
- Font: Vazirmatn Variable, self-hosted via `@fontsource-variable/vazirmatn` (CSP-safe, no CDN).
