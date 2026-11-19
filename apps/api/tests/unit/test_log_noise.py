"""The 2-second ``poll_tick`` heartbeat must not flood the logs, while failures and other jobs stay visible (audit V-026)."""

from __future__ import annotations

import logging

from melorin.core.logging import _QuietHeartbeat


def _rec(msg: str, level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord("arq.worker", level, __file__, 1, msg, None, None)


def test_success_lines_of_poll_tick_are_dropped():
    f = _QuietHeartbeat()
    assert not f.filter(_rec("  0.00s → 3d4f:poll_tick()"))
    assert not f.filter(_rec("  0.01s ← 3d4f:poll_tick ●"))


def test_failures_and_other_jobs_are_kept():
    f = _QuietHeartbeat()
    assert f.filter(_rec("  0.01s ! 3d4f:poll_tick failed, TimeoutError"))
    assert f.filter(_rec("poll_tick exploded", logging.ERROR))
    assert f.filter(_rec("  0.20s ← 91ab:expiry_job ●"))
