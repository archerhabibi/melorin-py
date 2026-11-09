"""T29: bot state/offset files are written atomically and survive a failed write."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tgmain.client import atomic_write_json  # noqa: E402


def test_writes_and_replaces(tmp_path):
    f = tmp_path / "state.json"
    atomic_write_json(f, {"a": 1})
    atomic_write_json(f, {"a": 2})
    assert json.loads(f.read_text()) == {"a": 2}
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]  # no temp leftovers


def test_failed_write_keeps_old_file_and_cleans_temp(tmp_path):
    f = tmp_path / "state.json"
    atomic_write_json(f, {"ok": True})
    with pytest.raises(TypeError):
        atomic_write_json(f, {"bad": object()})
    assert json.loads(f.read_text()) == {"ok": True}
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]
