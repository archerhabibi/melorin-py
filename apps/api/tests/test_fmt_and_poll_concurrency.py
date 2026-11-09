"""Audit T12 (one money formatter) and T27 (bounded parallelism in poll_tick)."""

import asyncio

from melorin.domain.fmt import money, money_by_currency
from melorin.worker import arq_app


def test_money_formats_thousands_and_optional_currency():
    assert money(1200000) == "1,200,000"
    assert money(1200000, "IRT") == "1,200,000 IRT"
    assert money(None) == "0"
    assert money(0, "IRT") == "0 IRT"


def test_money_by_currency_joins_nonzero_parts_and_never_mixes():
    assert money_by_currency([("IRT", 1200000), ("USD", 30)]) == "1,200,000 IRT + 30 USD"
    assert money_by_currency([("IRT", 0)]) == "۰"
    assert money_by_currency([]) == "۰"


async def test_bounded_never_exceeds_the_cap():
    gate = asyncio.Semaphore(3)
    running = peak = 0

    async def work():
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1

    await asyncio.gather(*(arq_app._bounded(gate, work()) for _ in range(20)))
    assert peak == 3
    assert arq_app.MAX_PARALLEL_DELIVERIES >= 1
