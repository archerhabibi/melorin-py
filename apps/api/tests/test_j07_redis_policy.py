from pathlib import Path

from _source import read_source

ROOT = Path(__file__).resolve().parents[1]


def test_redis_failure_no_longer_globally_returns_429():
    source = read_source(ROOT / "melorin/core/ratelimit.py")
    assert "pipeline(transaction=True)" in source
    assert "local_degraded" not in source  # health owns the public label
    assert "return await _local_hit(key, limit, window)" in source
