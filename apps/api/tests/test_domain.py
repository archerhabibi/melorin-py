from melorin.domain.debt import DebtState, can_afford, state
from melorin.domain.ledger import LedgerError, Line, apply_to_balance, validate_balanced
from melorin.domain.order_state import InvalidTransition, OrderStatus, assert_transition
from melorin.domain.pricing import Discount, quote
from melorin.domain.referral import commission_amount
from melorin.domain.server_selection import ServerCandidate, select_server


def test_balanced_double_entry():
    validate_balanced([Line("wallet:a", -100), Line("revenue", 100)])


def test_unbalanced_rejected():
    try:
        validate_balanced([Line("wallet:a", -100), Line("revenue", 99)])
    except LedgerError as e:
        assert e.code == "LEDGER_UNBALANCED"
    else:
        assert False


def test_customer_cannot_go_negative():
    try:
        apply_to_balance(50, Line("wallet:a", -100, min_balance=0))
    except LedgerError as e:
        assert e.code == "INSUFFICIENT_FUNDS"
    else:
        assert False


def test_reseller_debt_boundary():
    assert can_afford(0, 100, 100)
    assert not can_afford(0, 101, 100)
    assert not can_afford(-100, 1, 100)
    assert state(-80, 100) == DebtState.NEAR
    assert state(-100, 100) == DebtState.REACHED


def test_quote_snapshot_and_discount():
    q = quote(
        store_kind="reseller",
        product_id="p",
        main_price=1000,
        reseller_price=600,
        customer_price=1000,
        currency="IRR",
        discount=Discount("X", percent=10),
    )
    assert q.total == 900 and q.reseller_cost == 600 and q.snapshot()["currency"] == "IRR"


def test_state_machine_rejects_skip():
    assert_transition(OrderStatus.PAID, OrderStatus.PROCESSING)
    try:
        assert_transition(OrderStatus.PAID, OrderStatus.COMPLETED)
    except InvalidTransition:
        pass
    else:
        assert False


def test_server_selection_health_capacity_and_fewest():
    cs = [
        ServerCandidate("a", True, True, 10, 3, None, "mock"),
        ServerCandidate("b", True, True, 10, 1, ("p",), "mock"),
        ServerCandidate("c", False, True, 10, 0, ("p",), "mock"),
    ]
    assert select_server(cs, "p").id == "b"


def test_commission_basis_points():
    assert commission_amount(999, 500) == 49
