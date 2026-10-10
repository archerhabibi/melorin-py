# Reseller Telegram Bot

Reuses the main runner and supports either one reseller Store through `MELORIN_STORE_SLUG` plus `MELORIN_TELEGRAM_RESELLER_TOKEN`, or multiple stores through `MELORIN_RESELLER_BOTS_JSON`:

```json
[{"token":"123:abc","store_slug":"store-a"},{"token":"456:def","store_slug":"store-b"}]
```

Each bot has isolated Telegram offset/state and resolves its Store through Core. Customers get the full storefront. Store owners additionally get `/report`, `/customers` and `/payments`. Authorization, membership, wallet isolation, pricing, orders and payment review are decided by Core; this runner never holds panel credentials or performs business logic.
