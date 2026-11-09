"""Audit T02: one adapter lifecycle (sync close, async close, no close, failing close, context manager)."""

import pytest

from melorin.modules.vpn import panel_session as ps


class _Async:
    closed = False

    async def close(self):
        self.closed = True


class _Sync:
    closed = False

    def close(self):
        self.closed = True


class _Boom:
    async def close(self):
        raise RuntimeError("boom")


@pytest.mark.parametrize("cls", [_Async, _Sync])
async def test_close_adapter_handles_sync_and_async(cls):
    a = cls()
    await ps.close_adapter(a)
    assert a.closed


async def test_close_adapter_never_raises():
    await ps.close_adapter(_Boom(), "x")
    await ps.close_adapter(object(), "no close attr")


async def test_closer_binds_label():
    a = _Sync()
    await ps.closer("lbl")(a)
    assert a.closed


async def test_panel_session_always_closes(monkeypatch):
    a = _Async()
    monkeypatch.setattr(ps, "build_adapter", lambda panel, server=None, credentials=None: a)
    with pytest.raises(ValueError):
        async with ps.panel_session(object()) as got:
            assert got is a
            raise ValueError("inside")
    assert a.closed
