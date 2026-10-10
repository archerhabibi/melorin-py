# I60: J15 Multi-Store Reseller Bots

The reseller Telegram runner no longer has a one-store architecture. It keeps
the existing single-bot configuration for compatibility and adds
`MELORIN_RESELLER_BOTS_JSON`, a list of `{token, store_slug}` entries. One
process can poll all configured reseller bots concurrently, with a separate
offset/state file per bot.

Each update resolves the configured Store through Core, exchanges the Telegram
identity for a Core session with the bot secret, and calls only Store-scoped
Core endpoints. Core remains the authority for membership, owner permissions,
catalog/pricing, the customer's Store wallet, reseller credit/debt limits,
orders, payment review, and VPN provisioning. No panel credentials or financial
logic lives in the runner, and multiple stores owned by the same user stay
isolated by Store ID.
