"""The data-age policy lives in one module; the old names are aliases of it (audit T08)."""

import datetime as dt

from melorin.modules.vpn import freshness, inquiry, live, sync


def test_old_constant_names_are_the_policy_values():
    assert sync.FRESH_FOR == freshness.STORED_FOR == dt.timedelta(minutes=30)
    assert (live.TTL_SECONDS, live.FAIL_TTL_SECONDS) == (freshness.READING_TTL_SECONDS, freshness.READING_FAIL_TTL_SECONDS) == (20.0, 5.0)
    assert (live.MAX_ACCOUNTS, live.CONCURRENCY) == (freshness.READ_MAX_ACCOUNTS, freshness.READ_CONCURRENCY) == (200, 5)
    assert inquiry.REFRESH_TTL_SECONDS == freshness.REFRESH_MIN_INTERVAL_SECONDS == 15.0


def test_stored_copy_freshness_boundary():
    now = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.UTC)
    assert freshness.is_stored_copy_fresh(now - dt.timedelta(minutes=30), now) is True
    assert freshness.is_stored_copy_fresh(now - dt.timedelta(minutes=31), now) is False
    assert freshness.is_stored_copy_fresh(None, now) is False
