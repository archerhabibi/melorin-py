# Active API Route Contract

This file is the executable-alignment companion to the high-level API contract.

- Website login via Telegram bot (`docs/TELEGRAM-WEB-LOGIN.md`): browser `POST /api/v1/auth/telegram/web/sessions`, `POST …/sessions/{id}/poll`, `POST …/sessions/{id}/cancel`; bot runner (`X-Bot-Secret`) `POST …/web/bot/inspect`, `POST …/web/bot/decide`.
- Catalog: `GET /api/v1/stores/main`, `GET /api/v1/stores/by-slug/{slug}`, `GET /api/v1/stores/{store_id}`, `GET /api/v1/stores/{store_id}/catalog`.
- Checkout: `POST /api/v1/stores/{store_id}/checkout/quote`, `POST /api/v1/stores/{store_id}/orders`, `GET /api/v1/orders/{order_id}`.
- Wallet/payment: `GET /api/v1/stores/{store_id}/wallet`, `POST /api/v1/stores/{store_id}/wallet/topups`, `GET /api/v1/payments/{payment_id}`, `GET|POST /api/v1/payments/callbacks/{provider}`.
- Support: `POST|GET /api/v1/stores/{store_id}/tickets`, `GET|PATCH /api/v1/tickets/{ticket_id}` (customer edit: subject, priority, close/re-open), `GET|POST /api/v1/tickets/{ticket_id}/messages`, `PATCH /api/v1/tickets/{ticket_id}/messages/{message_id}` (author edit, stamped with `edited_at`).
- Admin ticket desk: `GET /api/v1/admin/tickets?status=&priority=&store_id=&q=`, `GET|PATCH /api/v1/admin/tickets/{ticket_id}`, `POST /api/v1/admin/tickets/{ticket_id}/messages` (`internal: true` = staff-only note, no customer notification), `PATCH /api/v1/admin/tickets/{ticket_id}/messages/{message_id}`.
- Admin: `/api/v1/admin/products`, `/panels`, `/servers`, `/payments`, `/orders`, `/orders/{order_id}/refund`, `/reports/summary`, `/reports/orders.csv`, `/audit`.
- Admin safe delete: `DELETE /api/v1/admin/products/{id}`, `/panels/{id}`, `/servers/{id}`, `/panel-groups/{id}`. Unused rows are removed (a panel takes its empty servers and group memberships with it); anything with orders/accounts, or still referenced (server product list, coupon scope, commission rule, a product's default group, the last panel of a manual group) answers `409` with a Persian reason, and the admin disables it instead. The remote VPN panel is never contacted. Audited as `*.deleted`.
- Reseller wallet correction is Store-scoped, uses the Store currency, and cannot drive a customer wallet below zero.
