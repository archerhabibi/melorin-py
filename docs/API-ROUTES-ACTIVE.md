# Active API Route Contract

This file is the executable-alignment companion to the high-level API contract.

- Catalog: `GET /api/v1/stores/main`, `GET /api/v1/stores/by-slug/{slug}`, `GET /api/v1/stores/{store_id}`, `GET /api/v1/stores/{store_id}/catalog`.
- Checkout: `POST /api/v1/stores/{store_id}/checkout/quote`, `POST /api/v1/stores/{store_id}/orders`, `GET /api/v1/orders/{order_id}`.
- Wallet/payment: `GET /api/v1/stores/{store_id}/wallet`, `POST /api/v1/stores/{store_id}/wallet/topups`, `GET /api/v1/payments/{payment_id}`, `GET|POST /api/v1/payments/callbacks/{provider}`.
- Support: `POST|GET /api/v1/stores/{store_id}/tickets`, `GET|POST /api/v1/tickets/{ticket_id}/messages`.
- Admin: `/api/v1/admin/products`, `/panels`, `/servers`, `/payments`, `/orders`, `/orders/{order_id}/refund`, `/reports/summary`, `/reports/orders.csv`, `/audit`.
- Reseller wallet correction is Store-scoped, uses the Store currency, and cannot drive a customer wallet below zero.
