"""T51: finished outbox events / webhook deliveries age out; unfinished rows and fresh rows are never touched."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from _db import make_store, open_schema_engine
from melorin.core.crypto import encrypt
from melorin.core.db import utcnow
from melorin.kernel.models.system import OutboxEvent, SystemSetting
from melorin.kernel.models.webhooks import WebhookDelivery, WebhookEndpoint
from melorin.worker import jobs, retention


@pytest.fixture
async def maker(monkeypatch):
    async with open_schema_engine() as engine:
        m = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(jobs, "session_factory", lambda: m)
        yield m


def _outbox(tag: str, status: str, age_days: int) -> OutboxEvent:
    when = utcnow() - dt.timedelta(days=age_days)
    return OutboxEvent(
        topic="t", payload={}, status=status, dedup_key=tag, created_at=when, processed_at=when if status == "processed" else None
    )


async def _endpoint(s) -> WebhookEndpoint:
    """A real endpoint: ``webhook_deliveries.endpoint_id`` is a foreign key (enforced on PostgreSQL, not on SQLite)."""
    store = await make_store(s)
    endpoint = WebhookEndpoint(store_id=store.id, url="https://h.example.com", events=["*"], secret_enc=encrypt("s"))
    s.add(endpoint)
    await s.flush()
    return endpoint


def _delivery(endpoint: WebhookEndpoint, tag: str, status: str, age_days: int) -> WebhookDelivery:
    when = utcnow() - dt.timedelta(days=age_days)
    return WebhookDelivery(
        endpoint_id=endpoint.id, store_id=endpoint.store_id, event_id=tag, event_type="x", payload={}, status=status, updated_at=when
    )


async def test_purge_finished_removes_only_old_finished_rows(maker):
    async with maker() as s:
        ep = await _endpoint(s)
        s.add_all(
            [
                _outbox("old-done", "processed", 60),
                _outbox("fresh-done", "processed", 2),
                _outbox("old-pending", "pending", 60),
                _outbox("old-processing", "processing", 60),
                _delivery(ep, "old-delivered", "delivered", 60),
                _delivery(ep, "old-failed", "failed", 60),
                _delivery(ep, "fresh-delivered", "delivered", 1),
                _delivery(ep, "old-pending", "pending", 60),
                _delivery(ep, "old-delivering", "delivering", 60),
            ]
        )
        await s.commit()
    async with maker() as s:
        assert await retention.purge_finished(s) == {"outbox_events": 1, "webhook_deliveries": 2}
    async with maker() as s:
        assert {e.dedup_key for e in (await s.scalars(select(OutboxEvent))).all()} == {"fresh-done", "old-pending", "old-processing"}
        assert {d.event_id for d in (await s.scalars(select(WebhookDelivery))).all()} == {
            "fresh-delivered",
            "old-pending",
            "old-delivering",
        }


async def test_retention_windows_are_configurable_and_never_below_one_day(maker):
    async with maker() as s:
        s.add_all([_outbox("three-days", "processed", 3), SystemSetting(key="privacy.outbox_retention_days", value=0)])
        await s.commit()
    async with maker() as s:  # 0 is clamped to 1 day, so a 3-day-old row goes but "now" rows would stay
        assert (await retention.purge_finished(s))["outbox_events"] == 1


async def test_bad_setting_value_falls_back_to_default(maker):
    async with maker() as s:
        s.add_all(
            [
                _outbox("old", "processed", 45),
                _outbox("recent", "processed", 10),
                SystemSetting(key="privacy.outbox_retention_days", value="abc"),
            ]
        )
        await s.commit()
    async with maker() as s:
        assert (await retention.purge_finished(s))["outbox_events"] == 1  # default 30 days
    async with maker() as s:
        assert [e.dedup_key for e in (await s.scalars(select(OutboxEvent))).all()] == ["recent"]


async def test_privacy_retention_job_runs_the_purge(maker):
    async with maker() as s:
        s.add(_outbox("old-done", "processed", 90))
        await s.commit()
    await jobs.privacy_retention_job()
    async with maker() as s:
        assert (await s.scalars(select(OutboxEvent))).all() == []
