"""The dedicated backup scheduler (T-R14): slots match the old Worker cron and the Worker no longer owns backups."""

import asyncio
import datetime as dt

from melorin.worker import arq_app, backup_main, jobs

UTC = dt.timezone.utc


def test_next_run_is_strictly_in_the_future_and_rolls_over_midnight():
    now = dt.datetime(2026, 11, 10, 2, 0, 0, tzinfo=UTC)
    assert backup_main.next_run(now, 2, 0) == dt.datetime(2026, 11, 11, 2, 0, tzinfo=UTC)
    assert backup_main.next_run(now, 2, 40) == dt.datetime(2026, 11, 10, 2, 40, tzinfo=UTC)


def test_slots_are_the_same_times_the_worker_cron_used():
    slots = {name: (h, m) for name, h, m, _ in backup_main.SCHEDULE}
    assert slots == {"backup": (2, 0), "panel_backup": (2, 40)}
    order = backup_main.upcoming(dt.datetime(2026, 11, 10, 1, 0, tzinfo=UTC))
    assert [name for _, name, _ in order] == ["backup", "panel_backup"]


def test_worker_no_longer_registers_or_schedules_backups():
    assert jobs.backup_job not in arq_app.WorkerSettings.functions
    assert jobs.panel_backup_job not in arq_app.WorkerSettings.functions
    names = {c.name for c in arq_app.WorkerSettings.cron_jobs}
    assert not {n for n in names if "backup" in n}


def test_a_crashing_job_does_not_stop_the_schedule(monkeypatch):
    calls: list[str] = []
    clock = [dt.datetime(2026, 11, 10, 1, 59, 59, tzinfo=UTC)]
    stop = asyncio.Event()

    async def boom():
        calls.append("boom")
        raise RuntimeError("dump failed")

    async def ok():
        calls.append("ok")
        stop.set()
        return "succeeded"

    monkeypatch.setattr(backup_main, "SCHEDULE", (("a", 2, 0, boom), ("b", 2, 10, ok)))

    async def run():
        real_wait = asyncio.wait_for

        async def fast(coro, timeout):
            if timeout:  # jump the clock instead of sleeping
                coro.close()
                clock[0] = clock[0] + dt.timedelta(seconds=timeout)
                raise asyncio.TimeoutError
            return await real_wait(coro, timeout)

        monkeypatch.setattr(backup_main.asyncio, "wait_for", fast)
        await backup_main.run_forever(stop, clock=lambda: clock[0])

    asyncio.run(run())
    assert calls[0] == "boom" and "ok" in calls
