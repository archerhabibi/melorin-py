"""How old may panel data be? One place for the answer (audit T08).

Before this module the rule was spread over three files with three names: ``sync.FRESH_FOR`` (is the stored copy recent enough to trust),
``live.TTL_SECONDS`` / ``FAIL_TTL_SECONDS`` / ``MAX_ACCOUNTS`` (how long one live reading is reused and how many accounts one call reads) and
``inquiry.REFRESH_TTL_SECONDS`` (how often one account may be refreshed on a tap). The old names stay as aliases of these values so nothing
that imports them changes; the numbers are unchanged. Pure constants and one helper: this module imports nothing from ``vpn``.
"""

from __future__ import annotations

import datetime as dt

# The copy stored on VpnAccount (last_synced_at): a read younger than this is trusted by ``expiry_job`` and is not repeated by the worker.
STORED_FOR = dt.timedelta(minutes=30)

# A live reading (``live.read``) is reused this long; "the panel could not answer" is remembered for less, so a tap retries soon but never
# once per tap.
READING_TTL_SECONDS = 20.0
READING_FAIL_TTL_SECONDS = 5.0

# One live call never reads more than this many accounts, and a panel gets this many parallel single-user reads.
READ_MAX_ACCOUNTS = 200
READ_CONCURRENCY = 5

# A display path may refresh the same account at most this often (money paths pass ``strict`` and are never skipped).
REFRESH_MIN_INTERVAL_SECONDS = 15.0


def is_stored_copy_fresh(synced_at: dt.datetime | None, now: dt.datetime) -> bool:
    """``synced_at`` and ``now`` must both be timezone-aware."""
    return synced_at is not None and now - synced_at <= STORED_FOR
