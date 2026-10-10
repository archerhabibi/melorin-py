# I39: IRT/IRR compatibility audit

The currency boundary is now explicit:

- **IRT** is the user-facing default for new stores, wallets, products, and
  concurrency smoke data.
- **IRR** remains supported only when a Store or legacy record explicitly uses
  it.
- Wallet, ledger, order, payment, coupon, commission, and reseller operations
  continue to require exact currency matching. No implicit application-level
  conversion is allowed.
- Zarinpal converts IRT to rial at the adapter edge only, using `amount * 10`
  for request/verify, while Melorin records the original IRT amount and
  currency.

Existing IRR records are not rewritten. A migration or financial reconciliation
is required before changing any existing Store currency. Provider sandbox
verification is still required before release.
