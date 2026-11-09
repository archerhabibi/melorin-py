"""Every ``*_job`` in worker.jobs goes through the one shared wrapper; it never alters results or errors."""

import inspect

import pytest

from melorin.worker import jobs
from melorin.worker.wrap import tracked_job


def test_every_job_is_wrapped():
    names = [n for n, f in inspect.getmembers(jobs, inspect.iscoroutinefunction) if n.endswith("_job")]
    assert names
    assert all(hasattr(getattr(jobs, n), "__wrapped__") for n in names), names


@pytest.mark.asyncio
async def test_wrapper_passes_result_and_reraises():
    @tracked_job
    async def ok_job(ctx=None):
        return 7

    @tracked_job
    async def bad_job(ctx=None):
        raise ValueError("boom")

    assert await ok_job() == 7
    with pytest.raises(ValueError):
        await bad_job()
