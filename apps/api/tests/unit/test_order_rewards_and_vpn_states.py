import pytest

from melorin.domain.order_rewards import REVERSE_ORDER, SETTLE_ORDER, RewardEngine, reward_base
from melorin.domain.order_state import VPN_TRANSITIONS, InvalidTransition, VpnStatus, assert_vpn_transition


def test_reward_order_is_fixed_and_reversed_on_refund():
    assert SETTLE_ORDER == (RewardEngine.REFERRAL, RewardEngine.LOYALTY)
    assert REVERSE_ORDER == (RewardEngine.LOYALTY, RewardEngine.REFERRAL)


def test_reward_base_is_the_charged_total():
    assert reward_base(90_000, is_revenue=True) == 90_000
    assert reward_base(0, is_revenue=True) == 0
    assert reward_base(50_000, is_revenue=False) == 0


def test_every_vpn_status_has_a_transition_row():
    assert set(VPN_TRANSITIONS) == set(VpnStatus)


def test_vpn_guard():
    assert_vpn_transition("active", "suspended")
    assert_vpn_transition("expired", "active")
    assert_vpn_transition("active", "active")
    with pytest.raises(InvalidTransition):
        assert_vpn_transition("archived", "active")
    with pytest.raises(InvalidTransition):
        assert_vpn_transition("revoked", "active")
