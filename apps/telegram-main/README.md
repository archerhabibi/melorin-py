# Main Telegram Bot

Long-poll runner (`runner.py`, httpx only). Transport only: every update is exchanged for a Core session via `/api/v1/auth/telegram/bot` (`X-Bot-Secret`); no DB or business logic lives here.

Commands: `/start` (supports `link_CODE` and `ref_CODE` deep links), `/plans` (quote -> wallet purchase buttons), `/wallet`, `/topup amount` (+ send a receipt photo/PDF), `/orders`, `/accounts`, `/test`, `/tickets`, `/ticket subject | body` (+ reply button), `/notifications`, `/link CODE`, `/me`, `/help`.

Safety: offset and conversation state are persisted atomically; order/top-up calls send an `Idempotency-Key` derived from the Telegram update/callback id, so replays cannot double-charge; Core 4xx errors are shown to the user, 5xx/transport errors retry the update with backoff.
