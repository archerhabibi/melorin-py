"""The one place that says how fresh a panel reading must be (audit T08).

Melorin does not own an account's usage/expiry/status - the panel does (mediator rule). Several modules read it, and each used
to carry its own number. They keep their own *mechanics* (cache vs. rate gate vs. stored timestamp) but all take their *policy*
from here, so "how stale may this be?" has exactly one answer per purpose.

* ``LIVE_TTL_S`` / ``LIVE_FAIL_TTL_S`` - ``live.py``: an in-memory reading for display; a failed read is retried sooner than a hit expires.
* ``REFRESH_GATE_S``                    - ``inquiry.refresh_from_panel``: at most one display-path reconcile per account per window.
* ``SYNC_FRESH_FOR``                    - ``sync.is_fresh``: how long ``last_synced_at`` counts as current for the status bucket.

Money paths (``strict=True``) ignore every one of these on purpose: they always ask the panel.
"""

import datetime as dt

LIVE_TTL_S = 20.0
LIVE_FAIL_TTL_S = 5.0
REFRESH_GATE_S = 15.0
SYNC_FRESH_FOR = dt.timedelta(minutes=30)
