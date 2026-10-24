# Upstream-bot adapter (`kind = upstream_bot`)

Sells accounts that are fulfilled by a **parent Telegram bot without an API**. Melorin stays the shop (wallet, ledger,
catalog, refunds); the parent bot only fulfils. A dedicated Telegram *user* session chats with the parent bot as a customer.

## Flow (verified on the parent bot's purchase screens)
`خرید اکانت` -> service button (`سرویس اقتصادی`) -> plan button (`10 گیگ یک ماهه 60,000 تومان`) -> confirm prompt
(`تایید خرید` / `انصراف`) -> delivery message (`نام اکانت`, `لینک اکانت`). The plan is chosen from the order's volume and
duration; the delivered name and subscription link are stored on the `VpnAccount` (`panel_ref`, `subscription_url`).

## Setup
1. Use a **separate** Telegram account, fund the parent bot wallet from it.
2. `python scripts/upstream_bot_login.py` -> StringSession.
3. Admin -> Panels -> add: `kind=upstream_bot`, `base_url=https://t.me/<parent_bot>`,
   credentials `{"api_id":..., "api_hash":"...", "session":"..."}`, config `{"max_price": 100000}`.
   Optional config: `service_button`, `menu_buy`, `confirm_button`, `plans`, `delivery_timeout`, `renew`.
4. Map bundles/servers to this panel as for any other panel.

## Safety rules built in
- `max_price` (toman) is mandatory; the confirm prompt amount must equal the chosen plan price and be <= `max_price`, otherwise the purchase is cancelled.
- The chat is serialised (Redis lock): one flow at a time.
- After the confirm click a missing delivery message is `UNKNOWN`, never `TRANSIENT`: the `pending` marker lets `get_account` / the retry recover the delivery instead of paying twice.
- A retry for the same Melorin username never buys again.

## Limits (be honest with customers)
- **Refund (مرجوعی):** the parent bot states purchases are non-refundable. `revoke_account` only releases the local mapping; Melorin refunds the customer from its own ledger, the upstream cost is lost.
- **Renewal:** works only if `config.renew` is configured (`menu`, `renew_button`, `confirm_button`, `success_words`). That flow was **not** in the supplied screenshots and is unverified; without it renewals go to manual review.
- No suspend/resume/usage: the parent bot does not expose them (`Capabilities.suspend=False`).
- Fragile by nature: if the parent bot changes its menu texts, adjust the config; the health job and failed attempts will show it.
- Telegram may limit the user account; keep volume human-like and the account dedicated.
