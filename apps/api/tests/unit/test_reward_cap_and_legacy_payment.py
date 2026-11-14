"""Reward rule 7 (cap) and the removal of the legacy global payment-destination keys (architecture review 4.4, 4.5)."""

import re
from pathlib import Path

from melorin.domain.commission import commission_amount
from melorin.domain.order_rewards import cap_reward, reward_base

ROOT = Path(__file__).parents[2] / "melorin"


def test_cap_reward_never_exceeds_the_base_and_never_goes_negative():
    assert cap_reward(50, 100) == 50
    assert cap_reward(150, 100) == 100
    assert cap_reward(-5, 100) == 0 and cap_reward(5, 0) == 0


def test_commission_is_capped_at_what_the_customer_paid():
    assert commission_amount(1000, 1000) == 100  # 10%
    assert commission_amount(1000, 12_000) == 1000  # a 120% plan pays at most the net paid
    assert commission_amount(0, 500) == 0


def test_rewards_are_computed_from_what_was_charged():
    assert reward_base(900, is_revenue=True) == 900
    assert reward_base(900, is_revenue=False) == 0


LEGACY_READ = re.compile(r"settings_store\.(?:get|set)\([^)]*[\"'](card\.info|gateway\.zarinpal|destination\.[a-z_]+)[\"']")


def test_legacy_global_payment_destination_keys_are_not_read_or_written():
    """The main store uses ``StorePaymentConfiguration``; the global ``card.info`` / ``gateway.zarinpal`` / ``destination.*``
    keys and the main-store fallback were removed by migration 0056. A new read or write of them fails here."""
    offenders = []
    for p in ROOT.rglob("*.py"):
        text = p.read_text(encoding="utf8")
        if "_main_store_legacy_settings" in text or LEGACY_READ.search(text):
            offenders.append(p.relative_to(ROOT).as_posix())
    assert not offenders, f"legacy payment destination configuration is back: {offenders}"
