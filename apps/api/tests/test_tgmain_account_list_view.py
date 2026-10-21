"""Phase 3.12 - the main bot's account list screen is built by two pure helpers (was one CC-36 method)."""

import importlib
from pathlib import Path

import pytest

BOT_DIR = Path(__file__).resolve().parents[2] / "telegram-main"


@pytest.fixture
def acc(monkeypatch):
    monkeypatch.syspath_prepend(str(BOT_DIR))
    return importlib.import_module("tgmain.handlers.accounts")


CUSTOMER = {"title": "T", "owner": False}
OWNER = {"title": "T", "owner": True}


def _rows(n):
    return [{"id": f"i{k}", "username": f"u{k}", "days_left": None if k == 0 else k, "health": None, "is_own": False} for k in range(n)]


def test_head_counts_search_note_and_hint(acc):
    head = acc._list_head(OWNER, {"total": 3, "note": "n"}, None, False, _rows(1))
    assert head[0].endswith("3 اکانت") and any("ℹ️ n" in h for h in head)
    assert "QR یکی" in head[-1] and "تمدید" in head[-1]
    searched = acc._list_head(OWNER, {"total": 3, "note": "n"}, "x", False, _rows(1))
    assert any("🔎" in h for h in searched) and not any("ℹ️" in h for h in searched)  # the note is hidden while searching


def test_head_empty_state_depends_on_whether_a_filter_or_search_is_active(acc):
    assert acc._list_head(CUSTOMER, {}, None, False, [])[-1] == "هنوز اکانتی نساخته‌اید."
    assert acc._list_head(CUSTOMER, {}, None, True, [])[-1] == "نتیجه‌ای پیدا نشد."
    assert acc._list_head(CUSTOMER, {}, "q", False, [])[-1] == "نتیجه‌ای پیدا نشد."


def test_buttons_paging_search_and_menu_row(acc):
    first = acc._list_buttons(CUSTOMER, {}, "-", None, _rows(2), 0, True)
    data = [cb for row in first for _, cb in row]
    assert "acl:-:1" in data and "acl:-:-1" not in data  # next only on the first page
    assert data[-2:] == ["acs:1", "menu:home"]
    mid = acc._list_buttons(OWNER, {}, "-", "q", _rows(1), 2, False)
    data = [cb for row in mid for _, cb in row]
    assert "oacl:-:1" in data and "oacq:1" in data and "menu:home" not in data  # owners: prefix, clear-search, no menu


def test_account_button_marks_unlimited_and_customer_name_only_for_owner_views(acc):
    a = {"id": "x", "username": "u", "days_left": None, "health": "bad", "customer_name": "N" * 20, "is_own": False}
    ((label, cb),) = acc._account_button(OWNER, a)
    assert "♾" in label and ("N" * 14) in label and ("N" * 15) not in label and cb == "oaccount:x"
    ((label, cb),) = acc._account_button(CUSTOMER, a)
    assert "N" not in label and cb == "account:x"
