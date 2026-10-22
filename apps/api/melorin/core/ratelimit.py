"""Fixed-window rate limiting with an explicit Redis outage policy.

Redis is the coordination store for the counters. What happens while it is unreachable depends on the environment
(documented in docs/RUNBOOK.md, "Redis failure"):

* development/test: a process-local, bounded counter is used (logged once), so a laptop without Redis still works.
* staging/production (``require_redis_rate_limit=true``, the default): FAIL CLOSED. Every rate-limited endpoint
  answers 429 RATE_LIMITED, and that includes every login/code/refresh endpoint, so NOBODY CAN SIGN IN until Redis is
  back. This is deliberate: a per-process fallback would multiply every limit by the number of API workers and let a
  brute-force attacker through exactly when the platform is degraded. Already-issued sessions keep working.

Plan Redis restarts like a short login outage (alert ``MelorinRedisUnavailable`` fires). There is no switch to relax
this outside development: Settings refuses ``require_redis_rate_limit=false`` in staging/production (see core/config.py).
"""

import logging
import time
from collections import defaultdict

from fastapi import Request
from melorin.core.errors import AppError
from melorin.core.redis import get_redis
from melorin.core.config import get_settings
from melorin.core.proxy import resolve_client_ip

_mem: dict[str, list] = defaultdict(lambda: [0, 0.0])
log = logging.getLogger("melorin.ratelimit")
_redis_degraded = False


async def _local_hit(key: str, limit: int, window: int) -> bool:
    slot = _mem[key]
    now = time.time()
    if now - slot[1] > window:
        slot[0], slot[1] = 0, now
    slot[0] += 1
    return slot[0] <= limit


async def hit(key: str, limit: int, window: int) -> bool:
    global _redis_degraded
    r = get_redis()
    if r is not None:
        try:
            k = f"rl:{key}:{int(time.time()) // window}"
            # Redis-py pipelines execute INCR and EXPIRE as one Redis
            # transaction, so a crash cannot leave an immortal rate-limit key.
            async with r.pipeline(transaction=True) as pipe:
                n, _ = await pipe.incr(k).expire(k, window).execute()
            _redis_degraded = False
            return n <= limit
        except Exception as exc:
            # Redis unavailable: fall back below (process-local counter, or fail closed in staging/production).
            if not _redis_degraded:  # log the transition once, not on every request
                log.warning("rate-limit redis unavailable, using fallback policy: %s", type(exc).__name__)
            _redis_degraded = True
    settings = get_settings()
    if settings.env in {"staging", "production"} and settings.require_redis_rate_limit:
        # Authentication limits must remain globally enforceable. A local
        # fallback would multiply the limit across API workers.
        return False
    return await _local_hit(key, limit, window)


def client_ip(request: Request) -> str:
    direct = request.client.host if request.client else "?"
    return resolve_client_ip(direct, request.headers.get("x-forwarded-for", ""), get_settings().trusted_proxy_ips)


def RateLimit(name: str, limit: int, window: int = 60):  # noqa: N802
    async def dep(request: Request):
        ip = client_ip(request)
        if not await hit(f"{name}:{ip}", limit, window):
            raise AppError("RATE_LIMITED", "تعداد درخواست‌ها زیاد است. کمی بعد تلاش کنید.", 429)

    return dep
