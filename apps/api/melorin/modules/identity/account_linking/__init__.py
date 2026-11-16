"""Person / Account / Login-Identity linking and consolidation (docs/25-Person-Account-Linking-Design.md).

One use-case layer shared by the website router, the Telegram bot endpoints and the admin router. Wallet, Orders and Payments keep
owning their own tables: this package only coordinates (``consolidation`` posts through ``melorin.modules.wallet.service``).
"""
