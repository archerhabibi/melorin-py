# I40: currency/payment contract

Added executable coverage for the IRT/IRR boundary and every PGClockBot-style
payment destination family. The tests prove that:

- IRT is converted to rial only at the Zarinpal adapter boundary.
- Explicit IRR values are sent unchanged.
- Manual card, external gateway, crypto, and Telegram Stars destinations accept
  only their declared currencies.
- A destination/currency mismatch fails before a payment is created.

This closes the application-level audit gap. Real Zarinpal and Telegram Stars
callbacks still require sandbox credentials and runtime evidence.
