"""scripts/host_watch.sh: the watchdog that lives outside the stack (audit V-006)."""

import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "host_watch.sh"


def _fake_docker(bin_dir: Path, rows: list[str]) -> None:
    body = "#!/bin/sh\ncase \"$1\" in\n  info) exit 1 ;;\n  ps) for i in " + " ".join(str(i) for i in range(len(rows))) + "; do echo c$i; done ;;\n  inspect) case \"$(echo \"$@\" | grep -o 'c[0-9]*$')\" in\n"
    for i, row in enumerate(rows):
        body += f"    c{i}) echo '{row}' ;;\n"
    body += "  esac ;;\nesac\n"
    f = bin_dir / "docker"
    f.write_text(body)
    f.chmod(f.stat().st_mode | stat.S_IXUSR)


def _run(tmp: Path, now: int, rows: list[str], **env: str) -> str:
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    _fake_docker(bin_dir, rows)
    e = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOST_WATCH_DRY_RUN": "1",
        "HOST_WATCH_STATE_DIR": str(tmp / "state"),
        "HOST_WATCH_NOW": str(now),
        "HOST_WATCH_DISK_PCT": "101",  # never fires on the CI machine
        "HOST_WATCH_MEM_MIN_PCT": "0",
        "MELORIN_DOMAIN": "localhost",
        "MELORIN_ADMIN_DOMAIN": "localhost",
        **env,
    }
    out = subprocess.run(["bash", str(SCRIPT)], cwd=ROOT, env=e, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_dead_main_bot_is_reported_after_grace_then_resolved(tmp_path):
    dead = ["telegram-main exited none -", "api running healthy -"]
    assert "SEND" not in _run(tmp_path, 1_000_000, dead)  # first sight: inside the grace window
    out = _run(tmp_path, 1_000_000 + 11 * 60, dead)
    assert "telegram-main" in out and "SEND" in out
    assert "api" not in out.replace("telegram-main", "")  # a healthy service is never mentioned
    again = _run(tmp_path, 1_000_000 + 12 * 60, dead)  # repeat only after HOST_WATCH_REPEAT_H
    assert "SEND" not in again
    fixed = _run(tmp_path, 1_000_000 + 13 * 60, ["telegram-main running healthy -", "api running healthy -"])
    assert "برطرف شد" in fixed


def test_unhealthy_api_is_reported_and_one_shot_jobs_are_ignored(tmp_path):
    rows = ["api running unhealthy -", "migrate exited none -", "backup exited none -"]
    _run(tmp_path, 2_000_000, rows)
    out = _run(tmp_path, 2_000_000 + 11 * 60, rows)
    assert "api" in out and "migrate" not in out and "backup" not in out


def test_disk_threshold(tmp_path):
    out = _run(tmp_path, 3_000_000, ["api running healthy -"], HOST_WATCH_DISK_PCT="0")
    assert "دیسک" in out
