"""panel_session: one lifecycle for panel adapters (audit T02)."""

import pytest

from melorin.modules.vpn import panel_session as ps
from melorin.modules.vpn.adapters.base import ErrorKind, PanelError


class _AsyncAdapter:
    def __init__(self, boom=False):
        self.closed, self.boom = 0, boom

    async def close(self):
        self.closed += 1
        if self.boom:
            raise RuntimeError("close failed")


class _SyncAdapter:
    closed = 0

    def close(self):
        self.closed += 1


@pytest.mark.asyncio
async def test_close_handles_async_sync_missing_and_failing():
    a, s = _AsyncAdapter(), _SyncAdapter()
    await ps.close_adapter(a)
    await ps.close_adapter(s)
    await ps.close_adapter(object())  # no close(): no error
    await ps.close_adapter(_AsyncAdapter(boom=True))  # a failing close is logged, never raised
    assert (a.closed, s.closed) == (1, 1)


@pytest.mark.asyncio
async def test_session_builds_and_always_closes(monkeypatch):
    adapter = _AsyncAdapter()
    seen = {}

    def fake_build(panel, server=None, *, credentials=None):
        seen.update(panel=panel, server=server, credentials=credentials)
        return adapter

    monkeypatch.setattr("melorin.modules.vpn.adapters.registry.build_adapter", fake_build)
    with pytest.raises(ValueError):
        async with ps.panel_session("P", "S", credentials={"k": 1}) as got:
            assert got is adapter
            raise ValueError("boom")
    assert adapter.closed == 1
    assert seen == {"panel": "P", "server": "S", "credentials": {"k": 1}}


def test_panel_failure_mapping():
    perm = ps.panel_failure(PanelError(ErrorKind.PERMANENT, "secret detail"), rejected="X")
    assert (perm.code, perm.status, perm.message) == ("PANEL_REJECTED", 409, "X")
    transient = ps.panel_failure(PanelError(ErrorKind.TRANSIENT, "secret detail"), rejected="X")
    assert (transient.code, transient.status) == ("PANEL_UNAVAILABLE", 503)
    assert "secret" not in transient.message
