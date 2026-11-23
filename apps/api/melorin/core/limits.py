"""Numeric bounds for client-supplied values: one place, so the API contract stays consistent.

Every integer a client can send must be bounded on both sides. An unbounded one reaches a PostgreSQL INTEGER/BIGINT bind
(``asyncpg: value out of int64 range``) or later arithmetic (``timedelta``, GB -> bytes) and surfaces as an HTTP 500.
``tests/contracts/test_openapi_input_bounds.py`` fails when a request integer is left unbounded.
"""

INT32_MAX = 2**31 - 1  # PostgreSQL INTEGER

# Smallest currency unit: far above any real price, balance or limit, yet ~900k such entries still sum inside BIGINT.
MAX_MONEY = 10**13

# Pagination offset: deeper than any list in the product, and inside INTEGER arithmetic.
MAX_OFFSET = INT32_MAX

# Counts (devices, redemptions, sort order ...): inside INTEGER with head-room for increments.
MAX_COUNT = 10**9

# Durations: 100 years is far below datetime's year-9999 limit, so ``now + timedelta(days=...)`` cannot raise OverflowError.
MAX_DAYS = 36_500

# Traffic quota in GB: 1 PB; multiplied by 1024**3 it stays inside BIGINT bytes.
MAX_TRAFFIC_GB = 1_000_000

# Telegram user ids fit in 52 bits.
MAX_TELEGRAM_ID = 2**52
