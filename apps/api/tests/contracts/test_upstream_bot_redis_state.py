"""The owner check and purchase-state change must be atomic on a real Redis server."""

import json
import os
import uuid

import pytest
import redis.asyncio as aioredis

from melorin.modules.panel_integrations.adapters.base import ErrorKind, PanelError
from melorin.modules.panel_integrations.adapters.upstream_bot import state

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("operation", ["set", "delete"])
async def test_stale_chat_owner_cannot_overwrite_or_delete_successor_state(monkeypatch, operation):
    url = os.environ.get("MELORIN_REDIS_URL")
    if not url:
        pytest.skip("MELORIN_REDIS_URL not set")
    client = aioredis.from_url(url, decode_responses=True)
    monkeypatch.setattr(state, "_redis", lambda: client)
    namespace = "lease-test-" + uuid.uuid4().hex
    store = state._Store(namespace)
    lock = state._ChatLock(namespace, ttl=30, wait=1)
    account_key = store._k("name")
    successor = {"status": "active", "ref": "new-owner"}
    try:
        with pytest.raises(PanelError) as exc:
            async with lock as lease:
                await store.set("name", {"status": "pending"}, lease=lease)
                await lease.ensure_owned()
                # The lease is replaced after the check but before the old owner's mutation.
                await client.set(lock.key, "replacement-owner")
                await client.set(account_key, json.dumps(successor))
                if operation == "set":
                    await store.set("name", {"status": "revoked"}, lease=lease)
                else:
                    await store.delete("name", lease=lease)
        assert exc.value.kind == ErrorKind.UNKNOWN
        assert json.loads(await client.get(account_key)) == successor
    finally:
        await client.delete(lock.key, account_key)
        state._MEM.pop(account_key, None)
        await client.aclose()


async def test_current_chat_owner_can_write_and_delete_state(monkeypatch):
    url = os.environ.get("MELORIN_REDIS_URL")
    if not url:
        pytest.skip("MELORIN_REDIS_URL not set")
    client = aioredis.from_url(url, decode_responses=True)
    monkeypatch.setattr(state, "_redis", lambda: client)
    namespace = "lease-test-" + uuid.uuid4().hex
    store = state._Store(namespace)
    lock = state._ChatLock(namespace, ttl=30, wait=1)
    account_key = store._k("name")
    try:
        async with lock as lease:
            await store.set("name", {"status": "pending"}, lease=lease)
            assert json.loads(await client.get(account_key)) == {"status": "pending"}
            await store.delete("name", lease=lease)
            assert await client.get(account_key) is None
    finally:
        await client.delete(lock.key, account_key)
        state._MEM.pop(account_key, None)
        await client.aclose()
