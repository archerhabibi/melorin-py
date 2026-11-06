"""Loyalty club rules (docs/22): pure points, tier, debt and redeem rules - no database involved."""

from __future__ import annotations

import pytest

from melorin.domain import loyalty as L
from melorin.domain.loyalty import LoyaltyError, Program, Reward, Tier

TIERS = [Tier("bronze", 0, 10_000), Tier("silver", 500, 11_000), Tier("gold", 2_000, 12_500)]
PROGRAM = Program(earn_unit=1_000, points_per_unit=1)


# ------------------------------------------------------------------ tiers
@pytest.mark.parametrize(
    ("lifetime", "name"),
    [(0, "bronze"), (499, "bronze"), (500, "silver"), (1_999, "silver"), (2_000, "gold"), (99_999, "gold"), (-5, "bronze")],
)
def test_tier_is_decided_by_lifetime_earned_points(lifetime, name):
    assert L.tier_for(TIERS, lifetime).name == name


def test_tier_lookup_ignores_the_order_the_ladder_was_given_in():
    assert L.tier_for(list(reversed(TIERS)), 600).name == "silver"


def test_no_tiers_means_no_tier_and_the_base_multiplier():
    assert L.tier_for([], 1_000) is None
    assert L.multiplier_for([], 1_000) == L.BASE_MULTIPLIER_BP


def test_next_tier_reports_the_gap_and_ends_at_the_top():
    nxt, missing = L.next_tier(TIERS, 120)
    assert (nxt.name, missing) == ("silver", 380)
    assert L.next_tier(TIERS, 2_000) == (None, 0)


# ------------------------------------------------------------------ earning
def test_points_are_full_steps_of_the_net_paid_amount():
    assert L.order_points(10_999, PROGRAM) == 10  # the partial step earns nothing
    assert L.order_points(999, PROGRAM) == 0


def test_points_per_unit_and_tier_multiplier_apply_in_that_order():
    program = Program(earn_unit=1_000, points_per_unit=3)
    assert L.order_points(10_000, program) == 30
    assert L.order_points(10_000, program, 12_500) == 37  # 30 * 1.25 floored


def test_cap_applies_after_the_multiplier():
    program = Program(earn_unit=1_000, points_per_unit=1, max_points_per_order=15)
    assert L.order_points(100_000, program, 15_000) == 15


@pytest.mark.parametrize("net", [0, -1])
def test_nothing_earned_on_a_free_or_negative_order(net):
    assert L.order_points(net, PROGRAM) == 0


def test_a_misconfigured_program_earns_nothing_instead_of_crashing():
    assert L.order_points(10_000, Program(earn_unit=0, points_per_unit=1)) == 0
    assert L.order_points(10_000, Program(earn_unit=1_000, points_per_unit=0)) == 0


def test_debt_is_recovered_from_new_points_first():
    assert L.offset_with_debt(10, 4) == (6, 4)
    assert L.offset_with_debt(3, 10) == (0, 3)
    assert L.offset_with_debt(10, 0) == (10, 0)
    assert L.offset_with_debt(10, -7) == (10, 0)


def test_reversal_takes_what_the_balance_covers_and_the_rest_becomes_debt():
    assert L.split_reversal(10, 25) == (10, 0)
    assert L.split_reversal(10, 4) == (4, 6)
    assert L.split_reversal(10, 0) == (0, 10)


# ------------------------------------------------------------------ redeeming
def _reward(**kw):
    base = dict(kind="wallet_credit", value=5_000, cost_points=100)
    base.update(kw)
    return Reward(**base)


def test_a_reward_the_customer_can_afford_passes():
    L.check_redeem(_reward(), balance=100, user_redeemed=0)


@pytest.mark.parametrize(
    ("reward", "balance", "used", "code"),
    [
        (_reward(active=False), 500, 0, "LOYALTY_REWARD_INACTIVE"),
        (_reward(stock=3, redeemed=3), 500, 0, "LOYALTY_REWARD_SOLD_OUT"),
        (_reward(per_user_limit=1), 500, 1, "LOYALTY_REWARD_LIMIT"),
        (_reward(cost_points=100), 99, 0, "LOYALTY_NOT_ENOUGH_POINTS"),
    ],
)
def test_redeem_rules_reject_with_their_code(reward, balance, used, code):
    with pytest.raises(LoyaltyError) as exc:
        L.check_redeem(reward, balance, used)
    assert exc.value.code == code


def test_inactive_wins_over_every_other_reason():
    with pytest.raises(LoyaltyError) as exc:
        L.check_redeem(_reward(active=False, stock=0), balance=0, user_redeemed=9)
    assert exc.value.code == "LOYALTY_REWARD_INACTIVE"


# ------------------------------------------------------------------ definition rules
def test_the_default_ladder_is_itself_valid():
    L.validate_tiers(list(L.DEFAULT_TIERS))


@pytest.mark.parametrize(
    ("tiers", "code"),
    [
        ([], "LOYALTY_NO_TIERS"),
        ([Tier("a", 10)], "LOYALTY_TIERS_START"),
        ([Tier("a", 0), Tier("b", 0)], "LOYALTY_TIERS_DUPLICATE"),
        ([Tier("a", 0), Tier("a", 5)], "LOYALTY_TIERS_NAME"),
        ([Tier("  ", 0)], "LOYALTY_BAD_TIER_NAME"),
        ([Tier("a", -1)], "LOYALTY_BAD_TIER_POINTS"),
        ([Tier("a", 0, 9_999)], "LOYALTY_BAD_MULTIPLIER"),
        ([Tier("a", 0, 50_001)], "LOYALTY_BAD_MULTIPLIER"),
        ([Tier("a", 0, 12_000), Tier("b", 5, 11_000)], "LOYALTY_TIERS_MULTIPLIER"),
        ([Tier(f"t{i}", i) for i in range(L.MAX_TIERS + 1)], "LOYALTY_TOO_MANY_TIERS"),
    ],
)
def test_tier_ladder_rules_reject_with_their_code(tiers, code):
    with pytest.raises(LoyaltyError) as exc:
        L.validate_tiers(tiers)
    assert exc.value.code == code


@pytest.mark.parametrize(
    ("program", "code"),
    [
        (Program(0, 1), "LOYALTY_BAD_EARN_UNIT"),
        (Program(1_000, 0), "LOYALTY_BAD_POINTS"),
        (Program(1_000, 1, first_order_bonus=-1), "LOYALTY_BAD_BONUS"),
        (Program(1_000, 1, referral_bonus=-1), "LOYALTY_BAD_BONUS"),
        (Program(1_000, 1, max_points_per_order=0), "LOYALTY_BAD_CAP"),
    ],
)
def test_program_rules_reject_with_their_code(program, code):
    with pytest.raises(LoyaltyError) as exc:
        L.validate_program(program)
    assert exc.value.code == code


def test_a_sane_program_is_accepted():
    L.validate_program(Program(1_000, 2, max_points_per_order=500, first_order_bonus=50, referral_bonus=100))


@pytest.mark.parametrize(
    ("reward", "code"),
    [
        (_reward(kind="gift_card"), "LOYALTY_BAD_REWARD_KIND"),
        (_reward(value=0), "LOYALTY_BAD_REWARD_VALUE"),
        (_reward(cost_points=0), "LOYALTY_BAD_REWARD_COST"),
        (_reward(stock=-1), "LOYALTY_BAD_REWARD_STOCK"),
        (_reward(per_user_limit=0), "LOYALTY_BAD_REWARD_LIMIT"),
    ],
)
def test_reward_rules_reject_with_their_code(reward, code):
    with pytest.raises(LoyaltyError) as exc:
        L.validate_reward(reward)
    assert exc.value.code == code


def test_a_sane_reward_is_accepted():
    L.validate_reward(_reward(stock=10, per_user_limit=2))
