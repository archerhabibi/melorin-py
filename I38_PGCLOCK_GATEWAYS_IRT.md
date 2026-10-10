# PGClockBot payment destination integration

PGClockBot's public documentation exposes four payment destination families:
card-to-card, configurable external gateway links, cryptocurrency wallets, and
Telegram Stars. Melorin now has an explicit destination catalog for those
families and uses **IRT as the site default currency** for newly bootstrapped
stores, wallets, products, and reseller stores.

Supported destination currencies are validated without implicit conversion:
`IRT`, `IRR`, `USD`, `EUR`, `USDT`, `AED`, `TRY`, and `XTR` for Stars. Existing
stores keep their stored currency; changing them requires an explicit migration
and financial review.

The catalog is a capability boundary. Automatic settlement still requires
provider credentials and sandbox verification, especially for external gateway,
crypto confirmation, and Telegram Stars callbacks.
