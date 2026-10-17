# Reseller Telegram Bot

One process (`telegram_reseller`) hosts **every** reseller bot. It is driven by Core, not by environment variables:

1. Every ~30 s it calls `GET /api/v1/internal/reseller-bots` (header `X-Bot-Secret`, private network only) and receives the
   active reseller stores whose bot is enabled, with the decrypted token for the runner only.
2. It keeps exactly those bots polling, one isolated runner per store (own Telegram offset and chat state).
   A changed token restarts that bot; a suspended store, a switched-off bot or a removed token stops it.
3. It reports each bot's real state (`running`, `error` + reason, …) to `POST /api/v1/internal/reseller-bots/{store}/status`;
   Admin → نمایندگان shows it live, and marks a bot `offline` when reports stop.

So adding or editing a reseller (domain, token, texts, limits) in the admin needs **no restart and no `.env` change**.

## What the bot does

* Customers: the full storefront under the store's own name; welcome / support / rules texts come from the store
  (Admin → نمایندگان → متن‌های ربات, or the reseller's own branding screen).
* Owner (decided by Core): extra **🏪 مدیریت فروشگاه** button and commands `/manage /report /customers /payments /prices`
  — wallet credit and debt state, pending receipts to approve, retail prices.
* Reseller bots do not offer "become a reseller".

Authorization, pricing, wallets, orders and payment review are all decided by Core; this runner holds no business logic.
Bot tokens are redacted from logs. The container healthcheck reads a heartbeat file (`MELORIN_HEARTBEAT_FILE`).

## Development override (optional)

`MELORIN_RESELLER_BOTS_JSON='[{"token":"123:abc","store_slug":"store-a"}]'` (several bots) or
`MELORIN_TELEGRAM_RESELLER_TOKEN` + `MELORIN_STORE_SLUG` (one bot) bypass Core-driven mode; leave them empty in production.
