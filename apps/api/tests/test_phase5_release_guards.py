"""Phase 5 (infra and release) regression guards. Static: they read the repo files, no Docker needed."""

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _load_guard():
    spec = importlib.util.spec_from_file_location("check_ops_p0", ROOT / "scripts/check_ops_p0.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ops_baseline_guard_passes():
    done = subprocess.run([sys.executable, str(ROOT / "scripts/check_ops_p0.py")], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_lock_parser_flags_unhashed_and_unpinned(tmp_path):
    guard = _load_guard()
    lock = tmp_path / "requirements.txt"
    lock.write_text("good==1.0 \\\n    --hash=sha256:aa \\\n    --hash=sha256:bb\n    # via -r requirements.in\nbare==2.0\nloose>=3\n")
    problems = guard.lock_problems(lock)
    assert any("no hash for bare==2.0" in p for p in problems)
    assert any("not an exact pin" in p for p in problems)
    assert not any("good" in p for p in problems)


def test_lock_parser_rejects_empty_file(tmp_path):
    lock = tmp_path / "requirements.txt"
    lock.write_text("# nothing here\n")
    assert _load_guard().lock_problems(lock)


def test_runtime_lock_has_no_dev_tooling_but_dev_lock_does():
    guard = _load_guard()
    assert guard.runtime_lock_dev_leaks(ROOT / "apps/api/requirements.txt") == []
    assert "pytest" in guard.runtime_lock_dev_leaks(ROOT / "apps/api/requirements-dev.txt")


def test_runtime_lock_keeps_tzdata_for_zoneinfo():
    # slim images ship no /usr/share/zoneinfo; admin timeseries resolves user time zones with zoneinfo
    assert "\ntzdata==" in (ROOT / "apps/api/requirements.txt").read_text()
