# I61: Bot, Store, Owner Mapping

The mapping is now a first-class Core table: `bot_store_bindings`.

Each row contains a stable bot identity (`bot_key`, never the Telegram token),
optional bot username, exactly one Store, exactly one owner, bot kind, status,
and non-secret configuration. Unique constraints prevent one bot or one Store
from being silently assigned twice. Core admin endpoints expose the mapping for
provisioning and audit:

- `GET /api/v1/admin/bot-store-bindings`
- `POST /api/v1/admin/bot-store-bindings`

The creation endpoint validates that a main bot maps to Main Store and a
reseller bot maps to a reseller Store. Telegram runners remain transport-only;
their token configuration is not stored in this table.
