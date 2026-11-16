from pathlib import Path

from _source import read_source

ROOT = Path(__file__).resolve().parents[4]


def test_release_checker_tracks_current_head_and_history_location():
    checker = read_source(ROOT / "scripts/check_release_matrix.py")
    assert "docs/06-ARCHITECTURE-DECISIONS.md" in checker
    assert "0001_initial_baseline" in checker


def test_telegram_healthcheck_is_copied_into_both_images():
    for name in ("apps/telegram-main/Dockerfile", "apps/telegram-reseller/Dockerfile"):
        assert "telegram_healthcheck.py" in (ROOT / name).read_text()
