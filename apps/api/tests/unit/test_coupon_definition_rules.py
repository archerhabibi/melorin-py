"""Pins the order and codes of ``coupon.validate_definition`` (Phase 3.6 rule table)."""

from __future__ import annotations

import datetime as dt

import pytest

from melorin.domain.coupon import CouponError, CouponRule, validate_definition

_T0 = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


def _rule(**over) -> CouponRule:
    base = dict(code="OFF10", percent_bp=1000, store_id="s1")
    base.update(over)
    return CouponRule(**base)


def test_valid_definitions_pass():
    validate_definition(_rule())
    validate_definition(_rule(percent_bp=0, fixed=500))
    validate_definition(_rule(scope="domain", store_id=None, allowed_store_kinds=("reseller",), funded_by="platform"))
    validate_definition(_rule(creator_type="reseller"), creator_store_id="s1")


@pytest.mark.parametrize(
    ("over", "creator", "code"),
    [
        ({"code": ""}, None, "COUPON_BAD_CODE"),
        ({"code": "x" * 51}, None, "COUPON_BAD_CODE"),
        ({"percent_bp": 10_001}, None, "COUPON_BAD_VALUE"),
        ({"percent_bp": -1}, None, "COUPON_BAD_VALUE"),
        ({"fixed": -5}, None, "COUPON_BAD_VALUE"),
        ({"percent_bp": 0, "fixed": 0}, None, "COUPON_BAD_VALUE"),
        ({"max_discount": 0}, None, "COUPON_BAD_VALUE"),
        ({"starts_at": _T0, "ends_at": _T0}, None, "COUPON_BAD_WINDOW"),
        ({"max_redemptions": 0}, None, "COUPON_BAD_QUOTA"),
        ({"per_customer_limit": 0}, None, "COUPON_BAD_QUOTA"),
        ({"combinable": True}, None, "COUPON_COMBINABLE_UNSUPPORTED"),
        ({"creator_type": "reseller"}, None, "COUPON_SCOPE_FORBIDDEN"),
        ({"creator_type": "reseller"}, "other", "COUPON_SCOPE_FORBIDDEN"),
        ({"creator_type": "reseller", "scope": "domain", "allowed_store_ids": ("s1",)}, "s1", "COUPON_SCOPE_FORBIDDEN"),
        ({"store_id": None}, None, "COUPON_SCOPE_FORBIDDEN"),
        ({"scope": "domain", "store_id": None}, None, "COUPON_SCOPE_FORBIDDEN"),
        # a multi-store coupon is the platform's promotion: it may never be charged to one reseller's margin
        ({"scope": "domain", "store_id": None, "allowed_store_kinds": ("reseller",), "funded_by": "store"}, None, "COUPON_FUNDING_INVALID"),
    ],
)
def test_each_rule_rejects_with_its_code(over, creator, code):
    with pytest.raises(CouponError) as exc:
        validate_definition(_rule(**over), creator_store_id=creator)
    assert exc.value.code == code


def test_first_violation_wins():
    with pytest.raises(CouponError) as exc:
        validate_definition(_rule(code="", percent_bp=0, combinable=True, store_id=None))
    assert exc.value.code == "COUPON_BAD_CODE"
    with pytest.raises(CouponError) as exc:
        validate_definition(_rule(percent_bp=0, combinable=True, store_id=None))
    assert exc.value.code == "COUPON_BAD_VALUE"
    with pytest.raises(CouponError) as exc:
        validate_definition(_rule(combinable=True, store_id=None))
    assert exc.value.code == "COUPON_COMBINABLE_UNSUPPORTED"
