"""Ratchet for audit T10: hand-written ``session.commit()`` in vpn/panelops may only go down.

New code should use ``melorin.core.uow.unit_of_work``. When you migrate a call site, lower its number here (the test also fails
when a file is below its baseline, so the gain is locked in).
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1] / "melorin"

BASELINE = {
    "modules/vpn/account_tools.py": 7,
    "modules/vpn/bulk.py": 12,
    "modules/vpn/governance.py": 2,
    "modules/vpn/manual_assign.py": 1,
    "modules/vpn/panel_admins.py": 4,
    "modules/vpn/panel_events.py": 7,
    "modules/vpn/panel_events_admin.py": 3,
    "modules/vpn/plans.py": 1,
    "modules/vpn/reconcile.py": 3,
    "modules/vpn/service_access.py": 1,
    "modules/vpn/subscription_check.py": 1,
    "modules/vpn/templates.py": 5,
    "modules/panelops/ops_console.py": 3,
    "modules/panelops/settings_drift.py": 2,
    "modules/panelops/sub_branding.py": 2,
}


def _counts() -> dict[str, int]:
    out = {}
    for pkg in ("vpn", "panelops"):
        for path in sorted((ROOT / "modules" / pkg).rglob("*.py")):
            n = len(re.findall(r"\.commit\(\)", path.read_text(encoding="utf-8")))
            if n:
                out[str(path.relative_to(ROOT))] = n
    return out


def test_commit_count_never_grows_and_improvements_are_recorded():
    now = _counts()
    grew = {f: (BASELINE.get(f, 0), n) for f, n in now.items() if n > BASELINE.get(f, 0)}
    assert not grew, f"new hand-written commit(): use core.uow.unit_of_work instead: {grew}"
    shrank = {f: (b, now.get(f, 0)) for f, b in BASELINE.items() if now.get(f, 0) < b}
    assert not shrank, f"lower BASELINE to lock in the improvement: {shrank}"


def test_unit_of_work_commits_on_success_and_rolls_back_on_error():
    import asyncio

    from melorin.core.uow import unit_of_work

    class S:
        def __init__(self):
            self.calls = []

        async def commit(self):
            self.calls.append("commit")

        async def rollback(self):
            self.calls.append("rollback")

    async def run():
        ok, bad = S(), S()
        async with unit_of_work(ok):
            pass
        try:
            async with unit_of_work(bad):
                raise ValueError("x")
        except ValueError:
            pass
        return ok.calls, bad.calls

    assert asyncio.run(run()) == (["commit"], ["rollback"])
