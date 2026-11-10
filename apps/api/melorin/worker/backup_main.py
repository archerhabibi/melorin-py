"""Dedicated backup scheduler: the ``backup`` container's entrypoint (T-R14).

The ARQ Worker used to run ``backup_job`` / ``panel_backup_job``, which meant the process that serves business jobs also needed
rclone, age and pg_dump, a writable home directory and a 15-minute runtime. They now run here, in their own container, so a
stuck dump can never delay expiry, reconciliation or panel polling and the Worker can run with a read-only root filesystem.

The job functions themselves are unchanged (lock, metrics, ``BackupRun`` row, Event Center notice); only the scheduler moved.
Times are UTC, the same slots the Worker cron used: local backup 02:00, panel backup 02:40.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import signal
from collections.abc import Awaitable, Callable

from sqlalchemy.exc import SQLAlchemyError

from melorin.core.config import get_settings
from melorin.worker import jobs

log = logging.getLogger("melorin.backup")

# (name, hour, minute, job) in UTC
SCHEDULE: tuple[tuple[str, int, int, Callable[..., Awaitable[object]]], ...] = (
    ("backup", 2, 0, jobs.backup_job),
    ("panel_backup", 2, 40, jobs.panel_backup_job),
)


def next_run(now: dt.datetime, hour: int, minute: int) -> dt.datetime:
    """Next UTC occurrence of ``hour:minute`` strictly after ``now``."""
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += dt.timedelta(days=1)
    return candidate


def upcoming(now: dt.datetime) -> list[tuple[dt.datetime, str, Callable[..., Awaitable[object]]]]:
    return sorted((next_run(now, h, m), name, fn) for name, h, m, fn in SCHEDULE)


async def run_forever(stop: asyncio.Event, clock: Callable[[], dt.datetime] | None = None) -> None:
    now_fn = clock or (lambda: dt.datetime.now(dt.timezone.utc))
    while not stop.is_set():
        when, name, fn = upcoming(now_fn())[0]
        delay = max(0.0, (when - now_fn()).total_seconds())
        log.info("next %s at %s UTC (in %.0f s)", name, when.isoformat(timespec="minutes"), delay)
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
            return
        except asyncio.TimeoutError:
            pass
        try:
            result = await fn()
            log.info("%s finished: %s", name, result)
        except (OSError, RuntimeError, ValueError, LookupError, SQLAlchemyError):  # a failed run must not stop tomorrow's schedule
            log.exception("%s crashed", name)


async def main() -> None:
    get_settings()  # fail fast on bad configuration, like the API and Worker
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await run_forever(stop)


if __name__ == "__main__":
    asyncio.run(main())
