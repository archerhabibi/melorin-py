"""The bot's referral screen shows only what Core reports for THIS store (programme, link, count, earnings)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tgmain.ui import referral_text  # noqa: E402

FALLBACK = "https://t.me/fallback_bot?start=ref_X"


def test_programme_link_count_and_earnings_come_from_core():
    data = {
        "links": {"telegram": "https://t.me/shop_bot?start=ref_AB12"},
        "referred_count": 3,
        "program": {
            "enabled": True,
            "currency": "IRT",
            "signup_reward": {"model": "fixed", "value": 50000, "max_amount": None},
            "commission": {"model": "percent", "value": 1000, "max_amount": 200000},
        },
        "commissions": [
            {
                "status": "credited",
                "amount": 30000,
                "offset_amount": 5000,
                "currency": "IRT",
            },
            {
                "status": "reversed",
                "amount": 99999,
                "offset_amount": 0,
                "currency": "IRT",
            },
        ],
    }
    text = referral_text(data, FALLBACK)
    assert "https://t.me/shop_bot?start=ref_AB12" in text
    assert "fallback_bot" not in text
    assert "10٪" in text and "50,000" in text and "200,000" in text
    assert "<b>3</b>" in text
    assert "25,000" in text  # only the credited commission, net of offset


def test_store_without_programme_says_so_and_falls_back_to_bot_link():
    text = referral_text(
        {"program": {"enabled": False}, "referred_count": 0, "commissions": []},
        FALLBACK,
    )
    assert "فعال نیست" in text
    assert FALLBACK in text
    assert "درآمد" not in text


def test_earnings_come_from_cores_total_not_from_the_short_commission_list():
    data = {
        "links": {"telegram": "https://t.me/shop_bot?start=ref_AB12"},
        "referred_count": 80,
        "earned": 123456,
        "program": {"enabled": True, "currency": "IRT"},
        "commissions": [{"status": "credited", "amount": 10, "offset_amount": 0, "currency": "IRT"}],
    }
    text = referral_text(data, FALLBACK)
    assert "123" in text.replace(",", "").replace("٬", "") or "۱۲۳" in text
    assert "10</b>" not in text

