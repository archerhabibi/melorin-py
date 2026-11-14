"""Renewal policy constants shared by the account lifecycle and by panel operations.

``vpn_accounts.renewal`` decides what a renewal is; ``panelops.settings_drift`` must know how long a renewal is still
accepted so a panel is never allowed to auto-delete an account earlier. Keeping the number here lets panel operations
read it without importing the account-lifecycle module (see the ``panelops`` import contract in ``pyproject.toml``).
"""

# An account can be renewed until this many days after its expiry date; after that a new account must be bought.
GRACE_DAYS = 10
