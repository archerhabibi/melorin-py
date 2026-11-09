"""Audit T08 step 1: one freshness policy; the readers take their numbers from it (values unchanged)."""

import datetime as dt

from melorin.modules.vpn import inquiry, live, panel_freshness, sync


def test_policy_values_are_unchanged():
    assert panel_freshness.LIVE_TTL_S == 20.0 and panel_freshness.LIVE_FAIL_TTL_S == 5.0
    assert panel_freshness.REFRESH_GATE_S == 15.0
    assert panel_freshness.SYNC_FRESH_FOR == dt.timedelta(minutes=30)


def test_readers_use_the_shared_policy():
    assert live.TTL_SECONDS == panel_freshness.LIVE_TTL_S
    assert live.FAIL_TTL_SECONDS == panel_freshness.LIVE_FAIL_TTL_S
    assert inquiry.REFRESH_TTL_SECONDS == panel_freshness.REFRESH_GATE_S
    assert sync.FRESH_FOR == panel_freshness.SYNC_FRESH_FOR


class _Boom:
    closed = False

    async def close(self):
        self.closed = True
        raise RuntimeError("close failed")


async def test_live_read_never_leaks_adapter_close_failure(monkeypatch):
    adapter = _Boom()

    class _P:
        id = "p1"

    async def get_account(name):
        return None

    adapter.get_account = get_account
    monkeypatch.setattr(live, "build_adapter", lambda panel: adapter)
    monkeypatch.setattr(live, "seed_adapter", lambda a, acc: a)

    class _A:
        id = "a1"
        username = "u"

    out = await live._read_panel(_P(), [_A()])
    assert out == {"a1": None} and adapter.closed
