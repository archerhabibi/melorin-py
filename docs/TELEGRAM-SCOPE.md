# Telegram Scope and Evidence

The Telegram channel is a transport boundary. Core owns identity, StoreContext, catalog, wallet, order, VPN, reseller and ticket rules. The current executable evidence covers authentication/update validation, Core API transport, notification delivery with dedup/retry, and the documented channel boundaries.

The following are deliberately not described as complete without runtime bot deployment evidence: every aiogram command handler, every callback mutation, Telegram Event Center topic provisioning, and full reseller mutation coverage. Production acceptance requires Telegram sandbox tests for duplicate update replay, restart/replay, payment/order idempotency, ticket mutation, and topic delivery.

## Update (bot handlers)

Both runners now implement the command/callback set listed in their READMEs (plain Telegram Bot API over httpx, no aiogram). Covered by offline tests in `apps/api/tests/test_i002_telegram_flows.py` (mocked Telegram + Core): idempotent purchase callback, top-up + receipt state, Core error reporting, reseller Store binding.

Still open (needs sandbox evidence): live Telegram duplicate-update/restart replay, Event Center topic provisioning, reseller write operations beyond payment review, and the test-account order is recorded with channel `web` by Core.

## Update (reseller request from the bot)

`/reseller` in the main bot is a two-step flow: request first, then (after admin approval, status `awaiting_details`) domain + bot token collected in the chat. The token message is deleted after it is read and the token never enters the bot's state file or logs; Core validates and stores it encrypted. Covered offline by `apps/api/tests/test_reseller_telegram_flow.py` and `test_o01_reseller_applications.py`. Still needs sandbox evidence: that Telegram really lets the bot delete the user's message in every chat type (best effort; the flow continues if it cannot).
