"""The reseller bot's usage screen shows only what Core read from the panel just now; a silent panel shows no number."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "telegram-main"))

from tgreseller.bot import OWNER_COMMANDS, OWNER_HELP, owner_usage_text  # noqa: E402

GB = 2**30
REPORT = {
    "live": True,
    "note": None,
    "complete": True,
    "accounts": {"total": 12, "active": 9, "on_hold": 1, "limited": 1, "expired": 1, "disabled": 0, "other": 0},
    "usage": {"total_used_bytes": 42 * GB},
    "near_expiry": 3,
    "near_expiry_days": 3,
    "near_exhaustion": 2,
    "near_exhaustion_percent": 90,
    "top_consumers": [
        {"username": "alice_1", "used_bytes": 9 * GB, "limit_bytes": 10 * GB, "percent": 90, "status": "active"},
        {"username": "bob_2", "used_bytes": 5 * GB, "limit_bytes": 0, "percent": None, "status": "active"},
    ],
    "panels": [{"name": "P1", "ok": True}],
}


def test_screen_shows_counts_total_top_and_the_two_warnings():
    text = owner_usage_text(REPORT)
    assert "اکانت‌ها: <b>12</b>" in text and "فعال: 9" in text and "اتمام حجم: 1" in text and "منقضی: 1" in text
    assert "<b>42.0</b> گیگابایت" in text
    assert "نزدیک انقضا (تا 3 روز): <b>3</b>" in text and "نزدیک اتمام حجم (از 90٪): <b>2</b>" in text
    assert "1. <code>alice_1</code> · 9.0 از 10.0 گیگ (90٪)" in text
    assert "2. <code>bob_2</code> · 5.0 گیگ (نامحدود)" in text
    assert "disabled" not in text and "سایر" not in text  # zero buckets are not listed


def test_silent_panel_shows_the_unavailable_text_and_no_number():
    text = owner_usage_text({"live": False, "note": "اطلاعات زنده از پنل موقتاً در دسترس نیست.", "panels": [{"name": "P1", "ok": False}]})
    assert "موقتاً در دسترس نیست" in text
    assert not any(ch.isdigit() for ch in text.replace("<b>", "").replace("</b>", ""))


def test_incomplete_totals_say_at_least_and_a_partial_panel_note_is_shown():
    text = owner_usage_text({**REPORT, "complete": False, "note": "بعضی پنل‌ها پاسخ ندادند؛ اعداد فقط از پنل‌هایی است که جواب دادند."})
    assert "حداقل 42.0" in text and "بعضی پنل‌ها پاسخ ندادند" in text


def test_usernames_are_escaped_and_no_connection_detail_can_be_shown():
    rep = {**REPORT, "top_consumers": [{"username": "<b>x</b>", "used_bytes": GB, "limit_bytes": 0, "percent": None, "status": "active"}]}
    text = owner_usage_text(rep)
    assert "<code>&lt;b&gt;x&lt;/b&gt;</code>" in text
    for forbidden in ("http", "vless", "ip"):
        assert forbidden not in text.lower().replace("<code>", "").replace("گیگابایت", "")


def test_command_and_help_are_listed_for_owners_only():
    assert ("usage", "📈 گزارش مصرف") in OWNER_COMMANDS and "/usage" in OWNER_HELP
