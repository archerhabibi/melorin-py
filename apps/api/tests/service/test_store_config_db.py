"""The main store's payment destination lives in StorePaymentConfiguration like every other store's (no global fallback)."""

from __future__ import annotations

import json
import uuid

import pytest

from _db import make_store, open_session
from melorin.core.crypto import decrypt
from melorin.core.errors import AppError
from melorin.modules.payments import service as pay
from melorin.modules.payments import store_config

ACTOR = uuid.uuid4()


def test_legacy_rows_convert_only_complete_destinations():
    rows = store_config.legacy_rows(
        {
            "card.info": {"card_number": "6037", "holder": "Ali", "bank": "melli"},
            "gateway.zarinpal": {"merchant_id": "m-1", "sandbox": True, "access_token": "t"},
        }
    )
    assert rows == [
        ("manual_card", {"card_number": "6037", "holder": "Ali", "bank": "melli"}, {}),
        ("zarinpal", {"sandbox": True}, {"merchant_id": "m-1", "access_token": "t"}),
    ]
    assert store_config.legacy_rows({"card.info": {"card_number": "", "holder": ""}, "gateway.zarinpal": {}}) == []


def test_legacy_keys_are_reserved():
    for key in ("card.info", "gateway.zarinpal", "destination.crypto"):
        assert store_config.is_legacy_key(key)
    assert not store_config.is_legacy_key("referral.commission_bp")


async def test_main_store_without_a_configuration_is_disabled_not_falling_back():
    async with open_session() as s:
        main = await make_store(s, kind="main")
        for provider in ("manual_card", "zarinpal"):
            with pytest.raises(AppError) as ei:
                await pay.store_payment_settings(s, main, provider)
            assert ei.value.code == "PAYMENT_METHOD_DISABLED"


async def test_main_store_uses_its_own_configuration():
    async with open_session() as s:
        main = await make_store(s, kind="main")
        await store_config.upsert(
            s, store_id=main.id, provider="manual_card", is_enabled=True,
            public_config={"card_number": "6037", "holder": "Ali"}, secret=None, actor_id=ACTOR, actor_type="admin",
        )
        await s.flush()
        got = await pay.store_payment_settings(s, main, "manual_card")
        assert got["card.info"]["card_number"] == "6037"


async def test_zarinpal_edit_keeps_the_stored_access_token_and_view_hides_secrets():
    async with open_session() as s:
        main = await make_store(s, kind="main")
        kw = dict(store_id=main.id, provider="zarinpal", is_enabled=True, public_config={"sandbox": False}, actor_id=ACTOR, actor_type="admin")
        await store_config.upsert(s, secret={"merchant_id": "m-1", "access_token": "tok"}, **kw)
        row = await store_config.upsert(s, secret={"merchant_id": "m-2"}, **kw)
        await s.flush()
        assert json.loads(decrypt(row.secret_enc)) == {"access_token": "tok", "merchant_id": "m-2"}
        view = store_config.admin_view(row)
        assert view["merchant_id"] == "m-2" and view["has_secret"] is True
        assert "tok" not in json.dumps(view)
        # secret=None keeps whatever is stored
        row = await store_config.upsert(s, secret=None, **kw)
        assert json.loads(decrypt(row.secret_enc))["access_token"] == "tok"


def test_only_card_and_zarinpal_are_editable_for_the_main_store():
    store_config.require_main_store_provider("manual_card")
    with pytest.raises(AppError):
        store_config.require_main_store_provider("crypto")
