from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_release_checker_tracks_current_head_and_history_location():
    checker = (ROOT / "scripts/check_release_matrix.py").read_text()
    assert "docs/history/I33_DOCUMENTATION_STATUS.md" in checker
    assert "0011_backfill_main_products" in checker


def test_telegram_healthcheck_is_copied_into_both_images():
    for name in ("apps/telegram-main/Dockerfile", "apps/telegram-reseller/Dockerfile"):
        assert "telegram_healthcheck.py" in (ROOT / name).read_text()
