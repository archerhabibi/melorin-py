"""T04 guard: customer notifications are raised only through events.emit_user_notice, never with a hand-built payload."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "melorin"
HAND_BUILT = re.compile(r"events\.emit\(\s*session,\s*events\.NOTIFY\b")


def test_no_hand_built_notify_payloads():
    offenders = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*.py") if HAND_BUILT.search(p.read_text())]
    assert offenders == [], f"use events.emit_user_notice instead: {offenders}"
