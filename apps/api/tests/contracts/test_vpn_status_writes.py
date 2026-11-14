"""Account status has one writer: ``set_vpn_status`` (guarded by the lifecycle table)."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[2] / "melorin"
PATTERN = re.compile(r"\b(account|acc|vpn_account)\.status\s*=(?!=)")
ALLOWED = {"domain/order_state.py", "modules/panel_integrations/adapters/mock.py"}


def test_no_direct_account_status_assignment():
    bad = []
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT).as_posix()
        if rel in ALLOWED:
            continue
        for n, line in enumerate(p.read_text(encoding="utf8").splitlines(), 1):
            if PATTERN.search(line):
                bad.append(f"{rel}:{n}")
    assert not bad, f"use set_vpn_status: {bad}"


CALL = re.compile(r"\bset_vpn_status\(")


def test_every_status_write_names_its_source():
    """A status write without ``source=`` could not be audited or checked against ``SOURCE_TARGETS``."""
    bad = []
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT).as_posix()
        if rel == "domain/order_state.py":
            continue
        for n, line in enumerate(p.read_text(encoding="utf8").splitlines(), 1):
            if CALL.search(line) and "import" not in line and "source=" not in line:
                bad.append(f"{rel}:{n}")
    assert not bad, f"pass source=VpnSource.X: {bad}"
