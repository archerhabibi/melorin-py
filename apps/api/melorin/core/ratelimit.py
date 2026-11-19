"""Fixed-window rate limiting with an explicit Redis outage policy.

Redis is the coordination store for the counters. What happens while it is unreachable depends on the environment
(documented in docs/18-OPERATIONS-DEPLOYMENT-DR.md, "Redis failure"):

* development/test: a process-local, bounded counter is used (logged once), so a laptop without Redis still works.
* staging/production (``require_redis_rate_limit=true``, the default): FAIL CLOSED. Every rate-limited endpoint
  answers 503 DEPENDENCY_UNAVAILABLE (with Retry-After; NOT 429, the client did nothing wrong), and that includes every login/code/refresh endpoint, so NOBODY CAN SIGN IN until Redis is
  back. This is deliberate: a per-process fallback would multiply every limit by the number of API workers and let a
  brute-force attacker through exactly when the platform is degraded. Already-issued sessions keep working.

Plan Redis restarts like a short login outage (alert ``MelorinRedisUnavailable`` fires). There is no switch to relax
this outside development: Settings refuses ``require_redis_rate_limit=false`` in staging/production (see core/config.py).
"""

import ipaddress
import logging
import time

from fastapi import Request
from melorin.core.errors import AppError, DependencyUnavailable
from melorin.core.redis import get_redis
from melorin.core.config import get_settings
from melorin.core.proxy import resolve_client_ip

# Process-local fallback counters: key -> [count, window_start (monotonic), window_seconds]. Bounded (see _LOCAL_MAX_KEYS) so a flood of
# distinct IPs/keys cannot grow memory without limit while Redis is down in development.
_mem: dict[str, list] = {}
_LOCAL_MAX_KEYS = 10_000
_LOCAL_SWEEP_INTERVAL = 30.0
_last_sweep = 0.0
log = logging.getLogger("melorin.ratelimit")
_redis_degraded = False


def _sweep_local(now: float) -> None:
    """Drop expired windows; if still over the cap, evict the oldest entries (never grows past _LOCAL_MAX_KEYS)."""
    global _last_sweep
    if now - _last_sweep < _LOCAL_SWEEP_INTERVAL and len(_mem) < _LOCAL_MAX_KEYS:
        return
    _last_sweep = now
    for k in [k for k, (_, start, win) in _mem.items() if now - start > win]:
        del _mem[k]
    overflow = len(_mem) - _LOCAL_MAX_KEYS
    if overflow > 0:
        for k, _ in sorted(_mem.items(), key=lambda kv: kv[1][1])[:overflow]:
            del _mem[k]


async def _local_hit(key: str, limit: int, window: int) -> bool:
    now = time.monotonic()
    _sweep_local(now)
    slot = _mem.get(key)
    if slot is None or now - slot[1] > window:
        slot = _mem[key] = [0, now, window]
    slot[0] += 1
    return slot[0] <= limit


async def hit(key: str, limit: int, window: int) -> bool:
    global _redis_degraded
    r = get_redis()
    if r is not None:
        try:
            now = time.time()
            bucket = int(now // window)
            k, prev_k = f"rl:{key}:{bucket}", f"rl:{key}:{bucket - 1}"
            # Sliding window (weighted two-bucket): no 2x burst at the window boundary. INCR+EXPIRE are one transaction,
            # so a crash cannot leave an immortal key; the previous bucket is read in the same round trip.
            async with r.pipeline(transaction=True) as pipe:
                n, _, prev = await pipe.incr(k).expire(k, window * 2).get(prev_k).execute()
            weight = 1.0 - (now % window) / window
            est = int(n) + int(int(prev or 0) * weight)
            _redis_degraded = False
            return est <= limit
        except Exception as exc:
            # Redis unavailable: fall back below (process-local counter, or fail closed in staging/production).
            if not _redis_degraded:  # log the transition once, not on every request
                log.warning("rate-limit redis unavailable, using fallback policy: %s", type(exc).__name__)
            _redis_degraded = True
    settings = get_settings()
    if settings.env in {"staging", "production"} and settings.require_redis_rate_limit:
        # Authentication limits must remain globally enforceable. A local
        # fallback would multiply the limit across API workers.
        raise DependencyUnavailable("redis")
    return await _local_hit(key, limit, window)


def _collapse_ipv6(ip: str) -> str:
    """An IPv6 subscriber owns a whole /64: key limits by it, or one host rotates through 2^64 addresses."""
    if ":" not in ip:
        return ip
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.version == 6 and not addr.ipv4_mapped:
        return str(ipaddress.ip_network(f"{addr}/64", strict=False).network_address) + "/64"
    return str(addr.ipv4_mapped) if addr.version == 6 else ip


def client_ip(request: Request) -> str:
    direct = request.client.host if request.client else "?"
    return _collapse_ipv6(resolve_client_ip(direct, request.headers.get("x-forwarded-for", ""), get_settings().trusted_proxy_ips))


def RateLimit(name: str, limit: int, window: int = 60):  # noqa: N802
    async def dep(request: Request):
        ip = client_ip(request)
        if not await hit(f"{name}:{ip}", limit, window):
            raise AppError("RATE_LIMITED", "تعداد درخواست‌ها زیاد است. کمی بعد تلاش کنید.", 429)

    return dep
