"""Phase 4.11: the pure domain layer (no DB, no HTTP). These rules decide money and account linking, so every branch is pinned."""

from __future__ import annotations

import pytest

from melorin.domain import currency, identity_link, pricing, referral
from melorin.domain.identity_link import Candidate, Decision, decide


# --- currency -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [("irt", "IRT"), (" usd ", "USD"), ("XTR", "XTR"), ("usdt", "USDT")])
def test_currency_normalize_trims_and_upper_cases_every_allowed_code(raw, expected):
    assert currency.normalize(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "GBP", "BTC", "ir t"])
def test_currency_normalize_rejects_unknown_codes_with_a_stable_error_code(raw):
    with pytest.raises(currency.CurrencyError) as e:
        currency.normalize(raw)
    assert e.value.code == "CURRENCY_UNSUPPORTED" and e.value.message


def test_currency_require_same_returns_the_single_currency_and_ignores_empty_values():
    assert currency.require_same("IRT", "IRT", None, "") == "IRT"


@pytest.mark.parametrize("codes", [("IRT", "USD"), ("IRT", "IRR"), (), (None, "")])
def test_currency_require_same_never_converts_between_currencies(codes):
    with pytest.raises(currency.CurrencyError) as e:
        currency.require_same(*codes)
    assert e.value.code == "CURRENCY_MISMATCH"


# --- identity linking -----------------------------------------------------------------------------------------------


def test_unverified_email_never_links_anything():
    assert decide(email_verified=False, matches=[Candidate("u1")], current_user_id=None) == (Decision.NEW, None)
    assert decide(email_verified=False, matches=[Candidate("u1")], current_user_id="u2") == (Decision.NEW, "u2")


def test_verified_email_with_no_match_creates_a_user_or_leaves_the_signed_in_one_alone():
    assert decide(email_verified=True, matches=[], current_user_id=None) == (Decision.NEW, None)
    # nothing else owns this email, so a signed-in user has nothing to merge: the identity simply stays with them
    assert decide(email_verified=True, matches=[], current_user_id="u1") == (Decision.ALREADY, "u1")


def test_verified_email_that_already_belongs_to_the_current_user_is_a_noop():
    assert decide(email_verified=True, matches=[Candidate("u1")], current_user_id="u1") == (Decision.ALREADY, "u1")


def test_verified_email_matching_one_user_links_a_signed_out_identity():
    assert decide(email_verified=True, matches=[Candidate("u1"), Candidate("u1")], current_user_id=None) == (Decision.LINK, "u1")


def test_two_matching_users_is_a_conflict_that_is_never_auto_merged():
    assert decide(email_verified=True, matches=[Candidate("u1"), Candidate("u2")], current_user_id=None) == (Decision.CONFLICT, None)
    assert decide(email_verified=True, matches=[Candidate("u1"), Candidate("u2")], current_user_id="u1") == (Decision.CONFLICT, None)


def test_signed_in_user_whose_email_belongs_to_someone_else_is_a_conflict_pointing_at_the_other_user():
    assert decide(email_verified=True, matches=[Candidate("u1")], current_user_id="u2") == (Decision.CONFLICT, "u1")


def test_decision_values_are_stable_strings_for_audit_rows():
    assert {d.value for d in identity_link.Decision} == {"link", "new", "already", "conflict"}


# --- pricing / discount / referral ----------------------------------------------------------------------------------


def _d(**kw):
    return pricing.Discount(code="C", **kw)


def _quote(**kw):
    base = dict(store_kind="main", product_id="p", main_price=1000, reseller_price=600, customer_price=None, currency="IRT", discount=None)
    base.update(kw)
    return pricing.quote(**base)


def test_compute_discount_is_percent_plus_fixed_capped_and_never_negative_or_above_price():
    assert pricing.compute_discount(1000, None) == 0
    assert pricing.compute_discount(1000, _d(percent=10)) == 100
    assert pricing.compute_discount(1000, _d(percent=10, fixed=50)) == 150
    assert pricing.compute_discount(1000, _d(percent=50, max_amount=120)) == 120
    assert pricing.compute_discount(1000, _d(fixed=5000)) == 1000  # never more than the price
    assert pricing.compute_discount(0, _d(percent=10, fixed=0)) == 0


def test_main_store_quote_has_no_reseller_cost():
    q = _quote()
    assert q.store_kind == "main" and q.snapshot()["product_id"] == "p"


@pytest.mark.parametrize("customer_price", [None, 0, -5])
def test_reseller_store_without_a_positive_customer_price_cannot_sell(customer_price):
    with pytest.raises(pricing.PricingError) as e:
        _quote(store_kind="reseller", customer_price=customer_price)
    assert e.value.code == "PRICE_NOT_SET"


def test_unknown_store_kind_is_rejected():
    with pytest.raises(pricing.PricingError) as e:
        _quote(store_kind="marketplace")
    assert e.value.code == "BAD_STORE"


def test_negative_main_price_is_rejected():
    with pytest.raises(pricing.PricingError) as e:
        _quote(main_price=-1)
    assert e.value.code == "BAD_PRICE"


def test_platform_funded_coupon_shrinks_the_reseller_cost_but_a_store_funded_one_does_not():
    disc = _d(percent=10)
    funded = _quote(store_kind="reseller", customer_price=1000, discount=disc, platform_funded=True)
    own = _quote(store_kind="reseller", customer_price=1000, discount=disc, platform_funded=False)
    assert funded.snapshot()["reseller_cost"] == 500 and own.snapshot()["reseller_cost"] == 600


def test_platform_funded_cost_floors_at_zero():
    q = _quote(store_kind="reseller", reseller_price=50, customer_price=1000, discount=_d(percent=50), platform_funded=True)
    assert q.snapshot()["reseller_cost"] == 0


def test_platform_funded_coupon_in_another_currency_is_refused_instead_of_converted():
    with pytest.raises(pricing.PricingError) as e:
        _quote(
            store_kind="reseller",
            customer_price=1000,
            currency="USD",
            reseller_currency="IRT",
            discount=_d(percent=10),
            platform_funded=True,
        )
    assert e.value.code == "CURRENCY_MISMATCH"


@pytest.mark.parametrize(
    "net,bp,expected", [(10_000, 500, 500), (999, 100, 9), (0, 500, 0), (-1, 500, 0), (1000, 0, 0), (1000, -5, 0), (3, 3333, 0)]
)
def test_commission_is_floored_basis_points_of_the_net_paid_amount(net, bp, expected):
    assert referral.commission_amount(net, bp) == expected
