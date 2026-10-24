# Upstream-bot adapter (`kind = upstream_bot`)

Sells accounts that are fulfilled by a **parent Telegram bot without an API**. Melorin stays the shop (wallet, ledger,
catalog, return policy); the parent bot only fulfils. A dedicated Telegram *user* session chats with the parent bot as a customer.

## Flows (all verified on the parent bot's screenshots / video)
| Melorin action | What the adapter does in the parent bot |
|---|---|
| buy (`create_account`) | `/start` -> main-menu button "خرید اکانت" -> service -> plan (`10 گیگ یک ماهه 60,000 تومان`) -> "تایید خرید" -> delivery message (name + link) |
| live status (`get_account`) | `/start` -> "خریدهای من" -> "جستجوی اکانت" -> send the upstream name -> account screen: status, used, remaining volume, end date (Jalali, converted from Tehran time). Cached for `status_ttl` seconds (60) |
| refund (`revoke_account`, مرجوعی) | account screen -> "مرجوعی اکانت" -> "تایید میکنم" -> success message; the parent bot credits its wallet back (amount is stored) |
| renew (`extend_account`) | account screen -> "تمدید اکانت" -> options (balance message + `حجم اولیه`) -> "تمدید با حجم اولیه <price> تومان" -> confirm "تایید تمدید اکانت" -> "اکانت ... رو با موفقیت تمدید کردم" + "مبلغ ... از حسابت کم کردم". **On by default** (verified on the real screens of 24 Oct 2026); `renew.enabled=false` switches it off |

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
   `confirm_button`, `plans`, `status_ttl`, `delivery_timeout`, `renew {enabled, renew_button, confirm_button, cancel_button, success_words, settle_window}`.
4. Map bundles/servers to this panel as for any other panel.

## Safety rules built in
- `max_price` (toman) is mandatory; the confirm prompt amount must equal the chosen plan price and be <= `max_price`, otherwise the purchase is cancelled.
- One flow at a time (Redis lock + process lock). Every flow starts with `/start`, which also clears a half-finished search.
- After the confirm click, a missing answer is `UNKNOWN`, never `TRANSIENT`. Purchases: a `pending` marker lets the retry recover the delivery instead of paying twice. Refunds: a `refund_started` marker; if the account is already gone upstream on retry, the refund is considered done. Renewals: see "Renewal rules" below.
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

## Renewal rules (verified 24 Oct 2026)
- The parent bot **restarts the package from now**: new expiry = renewal moment + 1 month, usage back to 0, volume = initial volume. Remaining days are **not** added. This is the same promise Core makes (`renewal.describe` -> `remaining_days_replaced`), so no second "raise the limit" call is needed.
- Only **"تمدید با حجم اولیه"** is automated. A request for another volume (`traffic_bytes` != the "حجم اولیه" shown by the parent bot) is `PERMANENT` before anything is paid; "تمدید و افزایش N گیگ" is not guessed because its price/volume meaning is not documented by the parent bot.
- The confirm screen prints **"مبلغ 0 تومان"** although the bot really charges the option price (balance 445,000 -> 385,000 on the recording). The adapter therefore never trusts that amount: the price is taken from the chosen button (`<= max_price`, wallet balance message `>=` price), the confirm prompt must name the same account, and only `0` or the option price is accepted on it. The real charge ("مبلغ ... از حسابت کم کردم") is stored as `renew_charged`; a different charge is logged as an error but the renewal is kept.
- After the confirm click every failure is `UNKNOWN`. A `renew_started` marker makes a retry read the account screen first: a changed expiry or "تاریخ تمدید" = done; unchanged inside `settle_window` (600 s) = `UNKNOWN` again, never a second payment; unchanged after the window = the confirm never took effect, a fresh attempt is allowed.
- Stale buttons ("زمان عملیات منقضی شده") before the confirm are `TRANSIENT`; the flow always restarts from `/start`.
