#!/usr/bin/env python3
"""Small, dependency-light load probe (audit T43): N concurrent workers hit read-only endpoints for D seconds and print
latency percentiles and the error rate. It only issues GETs, so it is safe against staging; it refuses to run against a
host that is not given explicitly. Example:

    python scripts/load_probe.py --base-url https://staging.example.com --path /health/ready --path /api/v1/catalog \
        --concurrency 50 --duration 30 --max-p95-ms 800 --max-error-rate 0.01

Exit code 1 when a budget is exceeded, so it can gate a release rehearsal.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time

import httpx


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))]


async def worker(
    client: httpx.AsyncClient,
    paths: list[str],
    stop_at: float,
    out: list[tuple[float, bool]],
    idx: int,
) -> None:
    n = idx
    while time.monotonic() < stop_at:
        path = paths[n % len(paths)]
        n += 1
        started = time.perf_counter()
        try:
            r = await client.get(path)
            ok = r.status_code < 500
        except httpx.HTTPError:
            ok = False
        out.append(((time.perf_counter() - started) * 1000.0, ok))


async def run(
    base_url: str, paths: list[str], concurrency: int, duration: float
) -> list[tuple[float, bool]]:
    out: list[tuple[float, bool]] = []
    limits = httpx.Limits(
        max_connections=concurrency, max_keepalive_connections=concurrency
    )
    async with httpx.AsyncClient(
        base_url=base_url, timeout=15, limits=limits
    ) as client:
        stop_at = time.monotonic() + duration
        await asyncio.gather(
            *(worker(client, paths, stop_at, out, i) for i in range(concurrency))
        )
    return out


def summarize(samples: list[tuple[float, bool]], duration: float) -> dict[str, float]:
    lat = [ms for ms, _ in samples]
    errors = sum(1 for _, ok in samples if not ok)
    return {
        "requests": float(len(samples)),
        "rps": len(samples) / duration if duration else 0.0,
        "p50_ms": percentile(lat, 0.50),
        "p95_ms": percentile(lat, 0.95),
        "p99_ms": percentile(lat, 0.99),
        "mean_ms": statistics.fmean(lat) if lat else 0.0,
        "error_rate": errors / len(samples) if samples else 1.0,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--base-url", required=True)
    ap.add_argument(
        "--path",
        action="append",
        default=[],
        help="GET path; repeat for several (default /health/ready)",
    )
    ap.add_argument("--concurrency", type=int, default=20)
    ap.add_argument("--duration", type=float, default=20.0)
    ap.add_argument("--max-p95-ms", type=float, default=1000.0)
    ap.add_argument("--max-error-rate", type=float, default=0.01)
    a = ap.parse_args(argv)
    paths = a.path or ["/health/ready"]
    samples = asyncio.run(
        run(a.base_url, paths, max(1, a.concurrency), max(1.0, a.duration))
    )
    s = summarize(samples, a.duration)
    print(" ".join(f"{k}={v:.2f}" for k, v in s.items()))
    failed = s["p95_ms"] > a.max_p95_ms or s["error_rate"] > a.max_error_rate
    if failed:
        print("LOAD BUDGET EXCEEDED", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
