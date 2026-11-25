"""Shared purchase state must fail closed when Redis is unavailable or corrupt."""

import json

import pytest

from melorin.modules.panel_integrations.adapters.base import ErrorKind, PanelError
from melorin.modules.panel_integrations.adapters.upstream_bot import state


async def test_failed_shared_read_does_not_fall_back_to_a_stale_local_mapping(monkeypatch):
    class OfflineRedis:
        async def get(self, key):
            raise ConnectionError("offline")

    store = state._Store("failed-read")
    state._MEM[store._k("name")] = json.dumps({"status": "active", "ref": "stale"})
    monkeypatch.setattr(state, "_redis", lambda: OfflineRedis())
    with pytest.raises(PanelError) as exc:
        await store.get("name")
    assert exc.value.kind == ErrorKind.UNKNOWN


async def test_failed_shared_write_does_not_report_success_or_cache_pending(monkeypatch):
    class OfflineRedis:
        async def set(self, key, value, **kwargs):
            return True

        async def eval(self, script, count, *args):
            if count == 2:
                raise ConnectionError("offline")
            return 1

    store = state._Store("failed-write")
    redis = OfflineRedis()
    monkeypatch.setattr(state, "_redis", lambda: redis)
    with pytest.raises(PanelError) as exc:
        async with state._ChatLock("failed-write", ttl=10, wait=1) as lease:
            await store.set("name", {"status": "pending"}, lease=lease)
    assert exc.value.kind == ErrorKind.UNKNOWN
    assert store._k("name") not in state._MEM


async def test_failed_shared_delete_keeps_local_state_and_reports_unknown(monkeypatch):
    class OfflineRedis:
        async def set(self, key, value, **kwargs):
            return True

        async def eval(self, script, count, *args):
            if count == 2:
                raise ConnectionError("offline")
            return 1

    store = state._Store("failed-delete")
    raw = json.dumps({"status": "pending"})
    state._MEM[store._k("name")] = raw
    redis = OfflineRedis()
    monkeypatch.setattr(state, "_redis", lambda: redis)
    with pytest.raises(PanelError) as exc:
        async with state._ChatLock("failed-delete", ttl=10, wait=1) as lease:
            await store.delete("name", lease=lease)
    assert exc.value.kind == ErrorKind.UNKNOWN
    assert state._MEM[store._k("name")] == raw


async def test_inactive_or_other_chat_lease_cannot_change_state(monkeypatch):
    monkeypatch.setattr(state, "_redis", lambda: None)
    store = state._Store("protected-chat")
    inactive = state._ChatLock("protected-chat", ttl=10, wait=1)
    with pytest.raises(PanelError):
        await store.set("name", {"status": "pending"}, lease=inactive)
    async with state._ChatLock("other-chat", ttl=10, wait=1) as wrong_lease:
        with pytest.raises(PanelError):
            await store.set("name", {"status": "pending"}, lease=wrong_lease)
    assert await store.get("name") is None


async def test_failed_name_scan_does_not_treat_a_mapping_as_free(monkeypatch):
    class OfflineRedis:
        async def scan_iter(self, pattern):
            raise ConnectionError("offline")
            yield pattern

    monkeypatch.setattr(state, "_redis", lambda: OfflineRedis())
    with pytest.raises(PanelError) as exc:
        await state._Store("failed-scan").name_taken("upstream-name")
    assert exc.value.kind == ErrorKind.UNKNOWN


@pytest.mark.parametrize("raw", ["invalid-json", "", "[]", '"text"'])
async def test_corrupt_shared_mapping_is_an_unknown_outcome(monkeypatch, raw):
    class CorruptRedis:
        async def get(self, key):
            return raw

    monkeypatch.setattr(state, "_redis", lambda: CorruptRedis())
    with pytest.raises(PanelError) as exc:
        await state._Store("corrupt").get("name")
    assert exc.value.kind == ErrorKind.UNKNOWN
