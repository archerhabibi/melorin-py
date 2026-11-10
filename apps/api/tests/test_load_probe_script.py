"""T43: the load probe's maths and exit codes (no network)."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("load_probe", Path(__file__).resolve().parents[3] / "scripts" / "load_probe.py")
load_probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(load_probe)


def test_percentile_and_summary():
    assert load_probe.percentile([], 0.95) == 0.0
    assert load_probe.percentile([10, 20, 30, 40, 50], 0.5) == 30
    s = load_probe.summarize([(10.0, True), (20.0, True), (30.0, False), (40.0, True)], duration=2.0)
    assert s["requests"] == 4 and s["rps"] == 2.0 and s["error_rate"] == 0.25 and s["p99_ms"] == 40.0


def test_budget_failure_returns_one(monkeypatch):
    async def fake_run(*a, **k):
        return [(2000.0, True)] * 5

    monkeypatch.setattr(load_probe, "run", fake_run)
    assert load_probe.main(["--base-url", "http://x", "--duration", "1", "--max-p95-ms", "100"]) == 1
    assert load_probe.main(["--base-url", "http://x", "--duration", "1", "--max-p95-ms", "5000"]) == 0
