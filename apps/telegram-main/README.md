# Main Telegram Bot

Long-poll runner (`runner.py`, httpx only). Transport only: every update is exchanged for a Core session via `/api/v1/auth/telegram/bot` (`X-Bot-Secret`); no DB or business logic lives here.

Commands: `/start` (supports `link_CODE` and `ref_CODE` deep links), `/plans` (quote -> wallet purchase buttons), `/wallet`, `/topup amount` (+ send a receipt photo/PDF), `/orders`, `/accounts`, `/test`, `/tickets`, `/ticket subject | body` (+ reply button), `/notifications`, `/link CODE`, `/me`, `/help`, `/reseller` (two-step reseller request, below), `/cancel` (leave the current step).

**`/reseller` (two steps).** 1) The bot asks for the store name and a short description and files a reseller application with Core (no domain/token yet). 2) After an admin approves the request (Core notifies the applicant in the bot), `/reseller` asks for the store domain and then the bot token; both go to `POST /reseller/applications/{id}/details`, Core validates them (format, uniqueness, Telegram `getMe`) and creates the reseller store. The message carrying the token is deleted from the chat right after it is read, the token is never echoed, logged or kept in the bot's state file (only the domain is), and Core stores it encrypted. In reseller bots the command keeps the old behaviour (a support ticket).

Safety: offset and conversation state are persisted atomically; order/top-up calls send an `Idempotency-Key` derived from the Telegram update/callback id, so replays cannot double-charge; Core 4xx errors are shown to the user, 5xx/transport errors retry the update with backoff.
