# Upstream-bot adapter (`kind = upstream_bot`)

Sells accounts that are fulfilled by a **parent Telegram bot without an API**. Melorin stays the shop (wallet, ledger,
catalog, return policy); the parent bot only fulfils. A dedicated Telegram *user* session chats with the parent bot as a customer.

## Flows (all verified on the parent bot's screenshots / video)
| Melorin action | What the adapter does in the parent bot |
|---|---|
| buy (`create_account`) | `/start` -> main-menu button "خرید اکانت" -> service -> plan (`10 گیگ یک ماهه 60,000 تومان`) -> "تایید خرید" -> delivery message (name + link) |
| live status (`get_account`) | `/start` -> "خریدهای من" -> "جستجوی اکانت" -> send the upstream name -> account screen: status, used, remaining volume, end date (Jalali, converted from Tehran time). Cached for `status_ttl` seconds (60) |
| refund (`revoke_account`, مرجوعی) | account screen -> "مرجوعی اکانت" -> "تایید میکنم" -> success message; the parent bot credits its wallet back (amount is stored) |
| renew (`extend_account`) | account screen -> "تمدید اکانت" -> plan -> confirm. **Off by default** (`renew.enabled`): the screens after the renew button were not in the material; test once by hand before enabling |

Main-menu buttons are never typed from memory: after `/start` the adapter reads the reply keyboard of the parent bot and
presses the button whose text contains the configured label, so emoji and spacing are always exact.

The parent bot names accounts itself; Melorin's username is mapped to the upstream name (Redis + `VpnAccount.panel_ref`,
re-seeded by `seed_adapter` together with the stored subscription URL).

## Setup
1. Use a **separate** Telegram account and fund the parent bot wallet from it.
2. `python scripts/upstream_bot_login.py` -> StringSession.
3. Admin -> Panels -> add: `kind=upstream_bot`, `base_url=https://t.me/<parent_bot>`,
   credentials `{"api_id":..., "api_hash":"...", "session":"..."}`, config `{"max_price": 100000}`.
   Optional config: `service_button`, `menu_buy`, `menu_purchases`, `search_button`, `refund_button`, `refund_confirm_button`,
   `confirm_button`, `plans`, `status_ttl`, `delivery_timeout`, `renew {enabled, renew_button, confirm_button, success_words}`.
4. Map bundles/servers to this panel as for any other panel.

## Safety rules built in
- `max_price` (toman) is mandatory; the confirm prompt amount must equal the chosen plan price and be <= `max_price`, otherwise the purchase is cancelled.
- One flow at a time (Redis lock + process lock). Every flow starts with `/start`, which also clears a half-finished search.
- After the confirm click, a missing answer is `UNKNOWN`, never `TRANSIENT`. Purchases: a `pending` marker lets the retry recover the delivery instead of paying twice. Refunds: a `refund_started` marker; if the account is already gone upstream on retry, the refund is considered done. Renewals: the account screen is re-read and must show a changed expiry.
- A retry for the same Melorin username never buys again; a refund never runs twice.

## Refund rules and the money flow
The parent bot refunds volume accounts only, <= 3 days after purchase, <= 5 % used, at most 3 per day. These are the same numbers
as Melorin's own return policy (`vpn/returns.py`), so a return Melorin allows is normally accepted upstream. Order of events:
Melorin refunds its customer (ledger) -> outbox `vpn.revoke` -> adapter refunds upstream. If the parent bot refuses (for example
usage read differently), the adapter raises a `PERMANENT` error containing the parent bot's own reply; the outbox retries and the event
center reports it, and the upstream cost stays unrecovered until handled by hand.

## Limits
- No suspend/resume: the parent bot does not expose them (`Capabilities.suspend=False`).
- Fragile by nature: if the parent bot changes menu texts, adjust the config; failed attempts and panel health will show it.
- Telegram may limit the user account; keep volume human-like and the account dedicated.
