"""M7.1: pure money rules - coupon, commission/clawback, ledger invariants, reseller debt and order state machine."""

import datetime as dt

import pytest

from melorin.domain import commission, debt
from melorin.domain.coupon import CouponError, CouponRule, CouponUse, discount_amount, evaluate, in_scope, pick_one, validate_definition
from melorin.domain.ledger import LedgerError, Line, apply_to_balance, reversal, validate_balanced
from melorin.domain.order_state import REFUNDABLE, RETRYABLE, TRANSITIONS, InvalidTransition, OrderStatus, assert_transition

NOW = dt.datetime(2026, 1, 10, tzinfo=dt.UTC)


def use(**kw):
    base = dict(store_id="s1", store_kind="main", product_id="p1", amount=100_000, currency="IRT", now=NOW)
    base.update(kw)
    return CouponUse(**base)


def rule(**kw):
    base = dict(code="OFF", store_id="s1", percent_bp=1000)
    base.update(kw)
    return CouponRule(**base)


# ---------------------------------------------------------------- coupons


def test_percent_discount_is_integer_math_and_capped_by_max_discount():
    assert evaluate(rule(percent_bp=1000), use()) == 10_000
    assert evaluate(rule(percent_bp=5000, max_discount=7_000), use()) == 7_000


def test_discount_never_exceeds_eligible_amount_or_goes_negative():
    assert discount_amount(rule(percent_bp=0, fixed=500_000), 100_000) == 100_000
    assert discount_amount(rule(), 0) == 0
    assert discount_amount(rule(), -5) == 0


@pytest.mark.parametrize(
    ("kw", "use_kw", "code"),
    [
        ({"status": "disabled"}, {}, "COUPON_INVALID"),
        ({"store_id": "other"}, {}, "COUPON_INVALID"),
        ({"starts_at": NOW + dt.timedelta(days=1)}, {}, "COUPON_NOT_STARTED"),
        ({"ends_at": NOW}, {}, "COUPON_EXPIRED"),
        ({"product_ids": ("p2",)}, {}, "COUPON_NOT_APPLICABLE"),
        ({"currency": "USD"}, {}, "COUPON_NOT_APPLICABLE"),
        ({"min_amount": 200_000}, {}, "COUPON_MIN_AMOUNT"),
        ({"max_redemptions": 3, "redemptions": 3}, {}, "COUPON_EXHAUSTED"),
        ({"per_customer_limit": 1}, {"customer_redemptions": 1}, "COUPON_CUSTOMER_LIMIT"),
    ],
)
def test_coupon_rejections(kw, use_kw, code):
    with pytest.raises(CouponError) as exc:
        evaluate(rule(**kw), use(**use_kw))
    assert exc.value.code == code


def test_coupon_validity_window_accepts_naive_datetimes_as_utc():
    r = rule(starts_at=dt.datetime(2026, 1, 1), ends_at=dt.datetime(2026, 2, 1))
    assert evaluate(r, use()) == 10_000


def test_domain_scope_is_admin_only_and_matches_store_or_kind():
    admin = rule(scope="domain", store_id=None, allowed_store_kinds=("reseller",))
    assert in_scope(admin, "x", "reseller") and not in_scope(admin, "x", "main")
    forged = rule(scope="domain", creator_type="reseller", store_id=None, allowed_store_ids=("x",))
    assert not in_scope(forged, "x", "reseller")


@pytest.mark.parametrize(
    ("kw", "code"),
    [
        ({"code": ""}, "COUPON_BAD_CODE"),
        ({"percent_bp": 10_001}, "COUPON_BAD_VALUE"),
        ({"percent_bp": 0, "fixed": 0}, "COUPON_BAD_VALUE"),
        ({"max_discount": 0}, "COUPON_BAD_VALUE"),
        ({"starts_at": NOW, "ends_at": NOW}, "COUPON_BAD_WINDOW"),
        ({"max_redemptions": 0}, "COUPON_BAD_QUOTA"),
        ({"per_customer_limit": 0}, "COUPON_BAD_QUOTA"),
        ({"combinable": True}, "COUPON_COMBINABLE_UNSUPPORTED"),
        ({"store_id": None}, "COUPON_SCOPE_FORBIDDEN"),
        ({"scope": "domain", "store_id": None}, "COUPON_SCOPE_FORBIDDEN"),
    ],
)
def test_coupon_definition_validation(kw, code):
    with pytest.raises(CouponError) as exc:
        validate_definition(rule(**kw))
    assert exc.value.code == code


def test_reseller_coupon_must_belong_to_creator_store():
    r = rule(creator_type="reseller", store_id="s1")
    validate_definition(r, creator_store_id="s1")
    with pytest.raises(CouponError) as exc:
        validate_definition(r, creator_store_id="s2")
    assert exc.value.code == "COUPON_SCOPE_FORBIDDEN"


def test_only_one_distinct_coupon_code_per_purchase():
    assert pick_one([" off ", "OFF", ""]) == "OFF"
    assert pick_one([]) is None
    with pytest.raises(CouponError) as exc:
        pick_one(["A", "B"])
    assert exc.value.code == "COUPON_NOT_COMBINABLE"


# ------------------------------------------------------------- commission


def test_commission_fixed_percent_and_cap():
    assert commission.amount_for(commission.Plan("commission", "fixed", 500), 10_000) == 500
    assert commission.amount_for(commission.Plan("commission", "percent", 1500), 10_000) == 1_500
    assert commission.amount_for(commission.Plan("commission", "percent", 5000, max_amount=1_000), 10_000) == 1_000


@pytest.mark.parametrize("net", [0, -1])
def test_commission_is_zero_without_a_positive_net_payment(net):
    assert commission.amount_for(commission.Plan("commission", "fixed", 500), net) == 0


def test_commission_is_zero_for_inactive_unknown_or_missing_plan():
    assert commission.amount_for(None, 100) == 0
    assert commission.amount_for(commission.Plan("commission", "fixed", 5, active=False), 100) == 0
    assert commission.amount_for(commission.Plan("commission", "weird", 5), 100) == 0
    assert commission.amount_for(commission.Plan("commission", "fixed", 0), 100) == 0


def test_product_specific_plan_wins_over_default():
    default = commission.Plan("commission", "fixed", 1)
    specific = commission.Plan("commission", "fixed", 9)
    plans = [(None, default), ("p1", specific)]
    assert commission.pick_plan(plans, "p1", "commission") is specific
    assert commission.pick_plan(plans, "p2", "commission") is default
    assert commission.pick_plan(plans, "p1", "signup_reward") is None


def test_clawback_never_overdraws_and_is_recovered_from_future_commission():
    assert commission.split_reversal(1_000, 400) == (400, 600)
    assert commission.split_reversal(1_000, -50) == (0, 1_000)
    assert commission.offset_with_outstanding(500, 600) == (0, 500)
    assert commission.offset_with_outstanding(500, 200) == (300, 200)
    assert commission.offset_with_outstanding(500, -10) == (500, 0)


# ----------------------------------------------------------------- ledger


def test_ledger_rejects_empty_unbalanced_zero_and_float_lines():
    with pytest.raises(LedgerError) as exc:
        validate_balanced([])
    assert exc.value.code == "LEDGER_EMPTY"
    with pytest.raises(LedgerError) as exc:
        validate_balanced([Line("a", 5), Line("b", -4)])
    assert exc.value.code == "LEDGER_UNBALANCED"
    with pytest.raises(LedgerError) as exc:
        validate_balanced([Line("a", 0), Line("b", 0)])
    assert exc.value.code == "LEDGER_ZERO_LINE"
    with pytest.raises(LedgerError) as exc:
        validate_balanced([Line("a", 1.5), Line("b", -1.5)])
    assert exc.value.code == "LEDGER_NOT_INTEGER"
    validate_balanced([Line("a", 5), Line("b", -5)])


def test_debit_below_minimum_balance_is_rejected_but_reversal_may_overdraw():
    debit = Line("w", -100, "w1", 0)
    with pytest.raises(LedgerError) as exc:
        apply_to_balance(50, debit)
    assert exc.value.code == "INSUFFICIENT_FUNDS"
    assert apply_to_balance(100, debit) == 0
    (rev,) = reversal([Line("w", 100, "w1", 0)])
    assert rev.amount == -100 and rev.min_balance is None
    assert apply_to_balance(50, rev) == -50


# -------------------------------------------------------- reseller debt


def test_reseller_debt_limit_boundaries():
    assert debt.can_afford(0, 500, 500) is True
    assert debt.can_afford(0, 501, 500) is False
    assert debt.can_afford(-500, 1, 500) is False  # limit already reached
    assert debt.min_balance(500) == -500
    assert debt.state(-500, 500) == debt.DebtState.REACHED
    assert debt.state(-400, 500) == debt.DebtState.NEAR
    assert debt.state(-100, 500) == debt.DebtState.OK
    assert debt.state(10, 0) == debt.DebtState.OK


# ------------------------------------------------------ order state machine


def test_every_status_has_a_transition_entry_and_targets_exist():
    assert set(TRANSITIONS) == set(OrderStatus)
    for targets in TRANSITIONS.values():
        assert targets <= set(OrderStatus)


@pytest.mark.parametrize("terminal", [OrderStatus.CANCELLED, OrderStatus.REFUNDED])
def test_terminal_states_cannot_be_left(terminal):
    for dst in OrderStatus:
        with pytest.raises(InvalidTransition):
            assert_transition(terminal, dst)


def test_a_paid_order_cannot_be_cancelled_directly_and_refund_goes_through_refund_pending():
    with pytest.raises(InvalidTransition):
        assert_transition("paid", "cancelled")
    with pytest.raises(InvalidTransition):
        assert_transition("completed", "refunded")
    assert_transition("completed", "refund_pending")
    assert_transition("refund_pending", "refunded")


def test_refundable_and_retryable_sets_are_consistent_with_the_state_machine():
    for status in REFUNDABLE:
        assert OrderStatus.REFUND_PENDING in TRANSITIONS[status]
    for status in RETRYABLE:
        assert OrderStatus.PROCESSING in TRANSITIONS[status]
