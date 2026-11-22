"""One uniform wrapper for every worker job (audit P5: "decorator/wrapper یکسان: قفل، timeout، متریک، سیاست خطا").

All 23 jobs (22 periodic ``*_job`` + ``poll_tick``) go through :func:`tracked_job`. It is behaviour-preserving for the
job itself: the return value and any exception are passed through unchanged. What it adds, identically for each job:

* **lock** - a Redis ``SET NX EX`` lock per job name so a slow run is never overlapped by the next tick (ARQ's
  ``unique=True`` only de-duplicates one scheduled slot). Fail-closed: when the lock state cannot be confirmed (Redis
  absent, erroring or timing out, even after a short bounded retry) the job body does not run; ``JobLockUnavailableError``
  is raised to the caller (ARQ records the failure) and counted as ``lock_error`` (alert ``MelorinJobLockUnavailable``).
* **timeout** - optional ``asyncio.wait_for`` budget (off by default; ARQ's ``job_timeout`` stays the hard limit).
* **metrics** - ``melorin_job_runs_total{job,outcome}`` (ok / error / timeout / skipped / lock_error), the duration histogram
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


def item_failed(job: str) -> None:
    """Count one per-item failure that a job deliberately isolates (T-W06 / T-R15).

    Jobs loop over panels/accounts/stores and must not let one bad item stop the rest, so they catch ``Exception`` per
    item. That used to be invisible: the job still reported ``outcome="ok"``. This counter makes it visible
    (``melorin_job_item_failures_total{job}``) and feeds the ``MelorinJobItemFailures`` alert. The traceback is still
    logged by the caller; ``job`` is a fixed low-cardinality label, never an id.
    """
    metrics.inc("melorin_job_item_failures_total", job=job)


DEFAULT_LOCK_TTL = 130  # a little above ARQ's default job_timeout (120 s)
LOCK_ACQUIRE_ATTEMPTS = 3  # a Redis blip must not cost a once-a-day job (the nightly backup) its whole day
LOCK_RETRY_DELAY = 0.25  # seconds; grows linearly (0.25, 0.5) so the worst case stays far below ARQ's job_timeout


class JobLockUnavailableError(RuntimeError):
    """A job was refused because its distributed overlap guard is unavailable (state unknown, so never \"unlocked\").

    A ``RuntimeError`` on purpose: the standalone backup scheduler already treats it as a failed run that must not stop
    tomorrow's schedule.
    """


_RELEASE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"


async def _acquire_once(name: str, ttl: int) -> tuple[bool, str | None]:
    """One attempt: ``(True, token)`` got the lock, ``(False, None)`` another run holds it; raises if the state is unknown."""
    try:
        redis = get_redis()
        if redis is None:
            raise JobLockUnavailableError("Redis is not configured")
        token = uuid.uuid4().hex
        if await redis.set(LOCK_PREFIX + name, token, nx=True, ex=ttl):
            return True, token
        return False, None
    except JobLockUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001 - an unknown lock state must never be treated as unlocked
        raise JobLockUnavailableError(f"Redis could not confirm the lock ({type(exc).__name__})") from exc


async def _acquire(name: str, ttl: int) -> tuple[bool, str | None]:
    """Acquire the overlap guard, retrying a few times when Redis errors. A *held* lock is an answer, never retried.

    A missing configuration is not transient, so it is refused at once.
    """
    for attempt in range(1, LOCK_ACQUIRE_ATTEMPTS + 1):
        try:
            return await _acquire_once(name, ttl)
        except JobLockUnavailableError as exc:
            if attempt == LOCK_ACQUIRE_ATTEMPTS or exc.__cause__ is None:
                raise
            await asyncio.sleep(LOCK_RETRY_DELAY * attempt)
    raise AssertionError("unreachable")  # pragma: no cover


def assert_lock_backend_configured() -> None:
    """Worker start-up check: with no Redis URL every guarded job would be refused, so stop loudly instead of idling."""
    if get_redis() is None:
        raise JobLockUnavailableError("MELORIN_REDIS_URL is required: guarded worker jobs are refused without a lock backend")


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

    if lock and timeout and lock_ttl <= timeout:
        # the guard would expire while the job is still allowed to run, so a second copy could start next to it
        raise ValueError(f"lock_ttl ({lock_ttl}s) must exceed timeout ({timeout}s)")

    def decorate(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        name = func.__name__

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            token: str | None = None
            if lock:
                try:
                    may_run, token = await _acquire(name, lock_ttl)
                except JobLockUnavailableError as exc:
                    metrics.inc("melorin_job_runs_total", job=name, outcome="lock_error")
                    log.error("job %s refused, not run: %s", name, exc)  # no traceback: this repeats every tick during an outage
                    raise
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
