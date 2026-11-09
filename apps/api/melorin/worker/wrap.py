"""One uniform wrapper for every worker job (audit P5: "decorator/wrapper یکسان: قفل، timeout، متریک، سیاست خطا").

All 23 jobs (22 periodic ``*_job`` + ``poll_tick``) go through :func:`tracked_job`. It is behaviour-preserving for the
job itself: the return value and any exception are passed through unchanged. What it adds, identically for each job:

* **lock** - a Redis ``SET NX EX`` lock per job name so a slow run is never overlapped by the next tick (ARQ's
  ``unique=True`` only de-duplicates one scheduled slot). Fail-open: no Redis, or a Redis error, means "run anyway".
* **timeout** - optional ``asyncio.wait_for`` budget (off by default; ARQ's ``job_timeout`` stays the hard limit).
* **metrics** - ``melorin_job_runs_total{job,outcome}`` (ok / error / timeout / skipped), the duration histogram
  ``melorin_job_duration_seconds{job}`` and the gauge ``melorin_job_last_success_timestamp{job}`` for staleness alerts.
* **error policy** - one place that logs the failure (with traceback) and re-raises.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from melorin.core import metrics
from melorin.core.redis import get_redis

log = logging.getLogger("melorin.jobs")

LOCK_PREFIX = "melorin:job:lock:"
DEFAULT_LOCK_TTL = 130  # a little above ARQ's default job_timeout (120 s)

_RELEASE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"


async def _acquire(name: str, ttl: int) -> tuple[bool, str | None]:
    """``(may_run, token)``. Fail-open: any Redis problem lets the job run (the lock is a guard, not a gate)."""
    try:
        redis = get_redis()
        if redis is None:
            return True, None
        token = uuid.uuid4().hex
        if await redis.set(LOCK_PREFIX + name, token, nx=True, ex=ttl):
            return True, token
        return False, None
    except Exception:  # noqa: BLE001 - lock infrastructure must never stop a job
        log.warning("job %s: lock backend unavailable, running without a lock", name)
        return True, None


async def _release(name: str, token: str | None) -> None:
    if token is None:
        return
    try:
        redis = get_redis()
        if redis is not None:
            await redis.eval(_RELEASE, 1, LOCK_PREFIX + name, token)
    except Exception:  # noqa: BLE001 - the TTL frees the lock anyway
        log.warning("job %s: could not release lock (it expires on its own)", name)


def tracked_job(
    fn: Callable[..., Awaitable[Any]] | None = None,
    *,
    lock: bool = True,
    lock_ttl: int = DEFAULT_LOCK_TTL,
    timeout: float | None = None,
) -> Any:
    """Decorate an async worker job. Usable as ``@tracked_job`` or ``@tracked_job(lock_ttl=910)``."""

    def decorate(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        name = func.__name__

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            token: str | None = None
            if lock:
                may_run, token = await _acquire(name, lock_ttl)
                if not may_run:
                    metrics.inc("melorin_job_runs_total", job=name, outcome="skipped")
                    log.info("job %s skipped: previous run still holds the lock", name)
                    return None
            started = time.monotonic()
            outcome = "ok"
            try:
                coro = func(*args, **kwargs)
                return await (asyncio.wait_for(coro, timeout) if timeout else coro)
            except TimeoutError:
                outcome = "timeout" if timeout else "error"
                log.exception("job %s failed: %s", name, outcome)
                raise
            except BaseException as exc:
                outcome = "error"
                log.exception("job %s failed: %s", name, type(exc).__name__)
                raise
            finally:
                elapsed = time.monotonic() - started
                metrics.inc("melorin_job_runs_total", job=name, outcome=outcome)
                metrics.observe("melorin_job_duration_seconds", elapsed, job=name)
                if outcome == "ok":
                    metrics.set_gauge("melorin_job_last_success_timestamp", time.time(), job=name)
                await _release(name, token)

        return wrapper

    return decorate(fn) if fn is not None else decorate
