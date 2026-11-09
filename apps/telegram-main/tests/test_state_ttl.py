"""T29/T60: per-chat bot state expires, and the state file without timestamps is still read."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tgmain.client import TransportMixin  # noqa: E402


class Box(TransportMixin):
    def __init__(self, path):
        self.state_file = path
        self.state = self._load_state()


def test_legacy_file_is_read_and_stamped(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"1": {"rs": "name"}}))
    b = Box(f)
    assert b.state == {"1": {"rs": "name"}} and "1" in b.state_at


def test_set_state_keeps_flat_file_and_roundtrips(tmp_path):
    f = tmp_path / "s.json"
    b = Box(f)
    b._set_state(7, {"topup_amount": True})
    raw = json.loads(f.read_text())
    assert raw["7"] == {"topup_amount": True} and "7" in raw["__at__"]  # chat entries stay top-level: old code can still read it
    assert Box(f).state == {"7": {"topup_amount": True}}
    b._set_state(7, None)
    assert "7" not in json.loads(f.read_text())


def test_stale_chats_expire_fresh_ones_stay(tmp_path):
    b = Box(tmp_path / "s.json")
    b._set_state(1, {"a": 1})
    b._set_state(2, {"b": 2})
    b.state_at["1"] -= b.STATE_TTL + 5
    assert b._expire_state() == 1
    assert list(b.state) == ["2"] and list(Box(tmp_path / "s.json").state) == ["2"]
    assert b._expire_state() == 0
