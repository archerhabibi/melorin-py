"""The reseller bot's owner referral screen shows only this store's programme and numbers, as Core reports them."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "telegram-main"))

from tgreseller.bot import owner_referral_text  # noqa: E402

RULES = [
    {"kind": "signup_reward", "model": "fixed", "value": 50000, "max_amount": None, "is_active": True, "product_id": None},
    {"kind": "commission", "model": "percent", "value": 1000, "max_amount": 200000, "is_active": True, "product_id": None},
    {"kind": "commission", "model": "percent", "value": 500, "max_amount": None, "is_active": True, "product_id": "p-1"},
    {"kind": "commission", "model": "percent", "value": 9900, "max_amount": None, "is_active": False, "product_id": None},
]
SUMMARY = {"invited": 7, "referrers": 3, "paid_out": 120000, "reversed": 5000, "outstanding_clawback": 2000}


def test_owner_sees_plans_and_numbers_of_his_store():
    text = owner_referral_text(RULES, SUMMARY, "IRT")
    assert "50,000 IRT" in text and "10٪" in text and "200,000" in text
    assert "99" not in text  # the inactive plan is not shown
    assert "طرح‌های اختصاصی محصول: <b>1</b>" in text
    assert "<b>7</b>" in text and "<b>3</b>" in text and "120,000 IRT" in text
    assert "5,000" in text and "2,000" in text


def test_store_without_plan_points_to_setup():
    text = owner_referral_text([], {"invited": 0, "referrers": 0, "paid_out": 0}, "IRT")
    assert "طرح پیش‌فرضی فعال نیست" in text
    assert "برگشت" not in text and "بدهی استرداد" not in text
