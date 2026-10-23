"""Phase 3.10 - pin the behaviour of the outbox topic table and the payment-settings helpers after the refactor."""

import types

import pytest

from melorin.core import events
from melorin.core.errors import AppError
from melorin.modules.payments import service as pay
from melorin.worker import runner

# Every topic the former ``elif`` chain handled. A topic missing here would silently be acknowledged without work.
HANDLED_TOPICS = {
    events.ORDER_PAID,
    events.PROVISIONING_FAILED,
    events.ORDER_COMPLETED,
    events.ORDER_DELIVERY,
    events.ORDER_REFUNDED,
    events.VPN_REVOKE,
    events.VPN_RENEWAL_ROLLBACK,
    events.NOTIFY,
    events.EVENT_CENTER,
    events.EVENT_CENTER_DELIVER,  # Telegram Event Center delivery (one queued message per destination)
    events.TICKET_UPDATED,
    events.PAYMENT_SUCCEEDED,
    events.PAYMENT_FAILED,
    events.WALLET_CHANGED,
    events.RESELLER_DEBT,
}


def test_topic_table_covers_exactly_the_previously_handled_topics():
    assert set(runner._TOPIC_HANDLERS) == HANDLED_TOPICS


@pytest.mark.parametrize(
    "topic, payload, name, event_id",
    [
        (events.PAYMENT_SUCCEEDED, {"payment_id": "p1"}, "payment.succeeded", "payment.succeeded:p1"),
        (events.PAYMENT_FAILED, {"payment_id": "p2"}, "payment.failed", "payment.failed:p2"),
        (
            events.WALLET_CHANGED,
            {"wallet_id": "w", "amount": 5, "balance": 9},
            "wallet.changed",
            "wallet.changed:w:5:9",
        ),
        (
            events.RESELLER_DEBT,
            {"store_id": "s", "state": "debt", "balance": -3},
            "reseller.debt",
            "reseller.debt:s:debt:-3",
        ),
    ],
)
async def test_webhook_only_topics_keep_their_idempotency_keys(monkeypatch, topic, payload, name, event_id):
    calls = []

    async def fake_webhook(session, event_name, p, eid):
        calls.append((event_name, p, eid))

    monkeypatch.setattr(runner, "_webhook", fake_webhook)
    await runner._TOPIC_HANDLERS[topic]("session", payload)
    assert calls == [(name, payload, event_id)]


@pytest.mark.parametrize(
    "kind, expected",
    [("vpn_expired", "vpn_account.expired"), ("vpn_near_expiry", "vpn_account.near_expiry")],
)
async def test_notify_topic_fans_out_expiry_kinds_to_webhooks(monkeypatch, kind, expected):
    sent, hooks = [], []

    async def fake_notify(session, p, k, title, body=""):
        sent.append((k, title, body))

    async def fake_webhook(session, event_name, p, eid):
        hooks.append((event_name, eid))

    monkeypatch.setattr(runner, "_notify", fake_notify)
    monkeypatch.setattr(runner, "_webhook", fake_webhook)
    await runner._on_notify("s", {"kind": kind, "store_id": "st", "dedup_key": "d1", "user_id": "u"})
    assert sent == [(kind, "Melorin", "")]
    assert hooks == [(expected, f"{kind}:d1")]


async def test_notify_topic_without_store_or_other_kind_sends_no_webhook(monkeypatch):
    hooks = []

    async def fake_notify(*a, **k):
        return None

    async def fake_webhook(*a, **k):
        hooks.append(a)

    monkeypatch.setattr(runner, "_notify", fake_notify)
    monkeypatch.setattr(runner, "_webhook", fake_webhook)
    await runner._on_notify("s", {"kind": "vpn_expired"})  # no store_id
    await runner._on_notify("s", {"kind": "general", "store_id": "st"})  # other kind
    assert hooks == []


def test_currency_check_only_applies_to_gateway_providers(monkeypatch):
    seen = []
    monkeypatch.setattr(pay, "validate_destination", lambda provider, currency: seen.append((provider, currency)))
    pay._check_currency("manual_card", "IRT")
    assert seen == []
    pay._check_currency("zarinpal", "IRT")
    assert seen == [("zarinpal", "IRT")]


def test_currency_check_maps_value_error_to_app_error(monkeypatch):
    def boom(provider, currency):
        raise ValueError("nope")

    monkeypatch.setattr(pay, "validate_destination", boom)
    with pytest.raises(AppError) as ei:
        pay._check_currency("crypto", "IRT")
    assert ei.value.code == "PAYMENT_CURRENCY_UNSUPPORTED"


def _cfg(enabled=True, public=None, secret_enc=None):
    return types.SimpleNamespace(is_enabled=enabled, public_config=public, secret_enc=secret_enc)


def test_configured_settings_rules_and_order():
    with pytest.raises(AppError) as ei:
        pay._store_configured_settings(_cfg(enabled=False), "manual_card")
    assert ei.value.code == "PAYMENT_METHOD_DISABLED"
    with pytest.raises(AppError) as ei:
        pay._store_configured_settings(_cfg(public={"card_number": "1"}), "manual_card")
    assert ei.value.code == "PAYMENT_DESTINATION_MISSING"
    with pytest.raises(AppError) as ei:
        pay._store_configured_settings(_cfg(public={}), "zarinpal")
    assert ei.value.code == "PAYMENT_DESTINATION_MISSING"
    ok = pay._store_configured_settings(_cfg(public={"card_number": "1", "holder": "h"}), "manual_card")
    assert ok["card.info"] == {"card_number": "1", "holder": "h"}
    assert ok["limits"] == ok["card.info"]
    assert set(ok) == {"card.info", "gateway.manual_card", "destination.manual_card", "limits"}
