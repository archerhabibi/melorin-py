"""One uniform wrapper for every periodic worker job (audit: "wrapper یکسان برای job ها").

Behaviour-preserving: the job's return value and raised exceptions are unchanged. The wrapper only adds
uniform start/finish/failure logging, a duration histogram and an outcome counter, so every job is
observable the same way.
"""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from melorin.core import metrics

log = logging.getLogger("melorin.jobs")


def tracked_job(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    name = fn.__name__

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        try:
            result = await fn(*args, **kwargs)
        except BaseException as exc:
            metrics.inc("melorin_job_runs_total", job=name, outcome="error")
            metrics.observe("melorin_job_duration_seconds", time.monotonic() - started, job=name)
            log.exception("job %s failed: %s", name, type(exc).__name__)
            raise
        metrics.inc("melorin_job_runs_total", job=name, outcome="ok")
        metrics.observe("melorin_job_duration_seconds", time.monotonic() - started, job=name)
        log.debug("job %s ok in %.3fs", name, time.monotonic() - started)
        return result

    return wrapper
