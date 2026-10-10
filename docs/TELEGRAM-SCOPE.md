# Telegram Scope and Evidence

The Telegram channel is a transport boundary. Core owns identity, StoreContext, catalog, wallet, order, VPN, reseller and ticket rules. The current executable evidence covers authentication/update validation, Core API transport, notification delivery with dedup/retry, and the documented channel boundaries.

The following are deliberately not described as complete without runtime bot deployment evidence: every aiogram command handler, every callback mutation, Telegram Event Center topic provisioning, and full reseller mutation coverage. Production acceptance requires Telegram sandbox tests for duplicate update replay, restart/replay, payment/order idempotency, ticket mutation, and topic delivery.

## Update (bot handlers)

Both runners now implement the command/callback set listed in their READMEs (plain Telegram Bot API over httpx, no aiogram). Covered by offline tests in `apps/api/tests/test_i002_telegram_flows.py` (mocked Telegram + Core): idempotent purchase callback, top-up + receipt state, Core error reporting, reseller Store binding.

Still open (needs sandbox evidence): live Telegram duplicate-update/restart replay, Event Center topic provisioning, reseller write operations beyond payment review, and the test-account order is recorded with channel `web` by Core.
