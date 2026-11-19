"""Customer-facing payment instructions must never carry operator secrets (audit V-15, Critical).

Defence in depth, three layers: (1) ``service._store_configured_settings`` builds ``destination.*`` from the PUBLIC config
only; (2) the destination adapter drops secret-looking keys from whatever it is given; (3) ``payment_out`` scrubs rows that
were stored before the fix. Keys are matched by NAME, recursively, case-insensitively.
"""

import re
from typing import Any

_SECRET_KEY = re.compile(
    r"(secret|token|passw|passphrase|private|seed|mnemonic|api[_-]?key|access[_-]?key|signing|hmac|webhook|credential|authorization|bearer)",
    re.I,
)


def strip_secrets(value: Any) -> Any:
    """Return a copy of ``value`` without any dict entry whose key looks like a credential."""
    if isinstance(value, dict):
        return {k: strip_secrets(v) for k, v in value.items() if not (isinstance(k, str) and _SECRET_KEY.search(k))}
    if isinstance(value, list):
        return [strip_secrets(v) for v in value]
    return value
