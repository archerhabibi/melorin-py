from collections import defaultdict

import pytest

from melorin.core import ratelimit


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.expirations = {}

    async def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key, seconds):
        self.expirations[key] = seconds

    def pipeline(self, transaction=True):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.key = None
        self.seconds = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def incr(self, key):
        self.key = key
        return self

    def expire(self, key, seconds):
        self.seconds = seconds
        return self

    async def execute(self):
        self.redis.values[self.key] = self.redis.values.get(self.key, 0) + 1
        self.redis.expirations[self.key] = self.seconds
        return [self.redis.values[self.key], True]


@pytest.mark.asyncio
async def test_redis_rate_limit_is_atomic_and_sets_expiry(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(ratelimit, "get_redis", lambda: fake)
    monkeypatch.setattr(ratelimit.time, "time", lambda: 120)

    assert await ratelimit.hit("auth:203.0.113.10", 2, 60)
    assert await ratelimit.hit("auth:203.0.113.10", 2, 60)
    assert not await ratelimit.hit("auth:203.0.113.10", 2, 60)
    assert fake.expirations["rl:auth:203.0.113.10:2"] == 60


@pytest.mark.asyncio
async def test_redis_outage_uses_bounded_local_limiter(monkeypatch):
    class Down:
        def pipeline(self, transaction=True):
            raise RuntimeError("redis unavailable")

    monkeypatch.setattr(ratelimit, "get_redis", lambda: Down())
    monkeypatch.setattr(ratelimit, "_mem", defaultdict(lambda: [0, 0.0]))
    assert await ratelimit.hit("auth:203.0.113.20", 1, 60)
    assert not await ratelimit.hit("auth:203.0.113.20", 1, 60)
