import pytest

from melorin.core import ratelimit


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(ratelimit, "_mem", {})
    monkeypatch.setattr(ratelimit, "_last_sweep", 0.0)


@pytest.mark.asyncio
async def test_local_counter_limits_within_window():
    assert [await ratelimit._local_hit("k", 2, 60) for _ in range(3)] == [True, True, False]


@pytest.mark.asyncio
async def test_local_counter_never_exceeds_key_cap(monkeypatch):
    monkeypatch.setattr(ratelimit, "_LOCAL_MAX_KEYS", 50)
    for i in range(500):
        await ratelimit._local_hit(f"ip{i}", 5, 3600)
    assert len(ratelimit._mem) <= 51


@pytest.mark.asyncio
async def test_expired_windows_are_swept(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: clock["t"])
    for i in range(20):
        await ratelimit._local_hit(f"old{i}", 5, 10)
    clock["t"] += 100
    await ratelimit._local_hit("fresh", 5, 10)
    assert list(ratelimit._mem) == ["fresh"]
