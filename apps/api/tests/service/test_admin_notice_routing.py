"""Admin notice routing end to end (2026-11-26): emit -> Event Center tap -> supergroup topic and, for a few kinds, the admin's bot DM.

The rule under test: the admin's bot DM is only for panel / node failures and customers' payments; every other admin notice goes to a
topic of the supergroup. A DM kind is mirrored in the group, a reseller store's events never DM the platform admin, and the DM does not
depend on the group being configured.
"""

from __future__ import annotations

import types
import uuid

import pytest
from sqlalchemy import select

from _db import make_order, make_product, make_store, make_user, open_session
from melorin.core import events
from melorin.core.crypto import encrypt
from melorin.kernel.models.notifications import TelegramEventDestination
from melorin.kernel.models.payments import Payment
from melorin.kernel.models.system import OutboxEvent
from melorin.kernel.models.vpn import Panel
from melorin.modules.eventcenter import rules
from melorin.modules.panelops import panel_notices
from melorin.modules.reseller import onboarding

ADMIN_GROUP, STORE_GROUP = "-1001111111111", "-1002222222222"


async def _world(s, *, admin_group=True):
    main = await make_store(s, kind="main")
    reseller = await make_store(s, kind="reseller", owner=await make_user(s))
    reseller.bot_token_enc = encrypt("123:abc")
    if admin_group:
        s.add(TelegramEventDestination(store_id=None, chat_id=ADMIN_GROUP, topics={}, is_enabled=True))
    s.add(TelegramEventDestination(store_id=reseller.id, chat_id=STORE_GROUP, topics={}, is_enabled=True))
    await s.commit()
    return main, reseller


async def _rows(s, topic):
    return (await s.scalars(select(OutboxEvent).where(OutboxEvent.topic == topic))).all()


async def _tap_queued(s) -> None:
    """What the worker does after the handler of each ``eventcenter.send`` event."""
    for e in await _rows(s, events.EVENT_CENTER):
        await rules.tap(s, e)
    await s.flush()


async def _dms(s) -> list[str]:
    return sorted(r.payload["kind"] for r in await _rows(s, events.ADMIN_ALERT))


async def _group(s) -> list[tuple[str, str]]:
    """(destination chat, topic) of every queued group delivery."""
    out = []
    for r in await _rows(s, events.EVENT_CENTER_DELIVER):
        dest = await s.get(TelegramEventDestination, uuid.UUID(r.payload["destination_id"]))
        out.append((dest.chat_id, r.payload["topic"]))
    return sorted(out)


async def _payment(s, store, *, status="succeeded"):
    user = await make_user(s)
    pay = Payment(
        user_id=user.id, store_id=store.id, purpose="wallet_topup", provider="manual_card", amount=50000, currency="IRT", status=status
    )
    s.add(pay)
    await s.flush()
    return pay


# ----- customers' payments reach the DM -----
async def test_a_customer_payment_in_the_main_store_dms_the_admin_and_is_mirrored_in_the_group():
    async with open_session() as s:
        main, _ = await _world(s)
        pay = await _payment(s, main)
        e = OutboxEvent(topic=events.PAYMENT_SUCCEEDED, payload={"payment_id": str(pay.id), "store_id": str(main.id)})
        s.add(e)
        await s.flush()

        assert await rules.tap(s, e) == 1
        assert await rules.tap(s, e) == 1  # the same event tapped again changes nothing (dedup keys)
        await s.flush()

        assert await _dms(s) == ["payment_succeeded"]
        assert await _group(s) == [(ADMIN_GROUP, "payments")]
        (alert,) = await _rows(s, events.ADMIN_ALERT)
        assert alert.dedup_key == f"adm:{e.id}" and "پرداخت موفق" in alert.payload["text"]


async def test_a_reseller_stores_payment_stays_in_that_stores_group_and_never_dms_the_platform_admin():
    async with open_session() as s:
        _, reseller = await _world(s)
        pay = await _payment(s, reseller)
        e = OutboxEvent(topic=events.PAYMENT_SUCCEEDED, payload={"payment_id": str(pay.id), "store_id": str(reseller.id)})
        s.add(e)
        await s.flush()

        await rules.tap(s, e)
        await s.flush()

        assert await _dms(s) == []
        assert await _group(s) == [(STORE_GROUP, "payments")]


async def test_receipt_review_and_grace_credit_are_payment_dms_but_other_payment_notes_are_group_only():
    async with open_session() as s:
        main, reseller = await _world(s)
        for kind in ("payment_receipt_review", "payment_grace_credited"):
            await events.emit_admin_notice(s, kind, f"{kind}\nمبلغ: 1", store_id=main.id)
        for kind in (
            "payment_failed",
            "payment_sms_matched",
            "payment_sms_confirmed",
            "payment_sms_ambiguous",
            "payment_provisional_blocked",
        ):
            await events.emit_admin_notice(s, kind, f"{kind}\nمبلغ: 1", store_id=main.id)
        await events.emit_admin_notice(s, "payment_receipt_review", "reseller receipt", store_id=reseller.id)  # that store's business
        await s.flush()

        await _tap_queued(s)

        assert await _dms(s) == ["payment_grace_credited", "payment_receipt_review"]
        assert len(await _group(s)) == 7 + 1  # seven in the admin group + the reseller's own group; payments topic everywhere
        assert {topic for _, topic in await _group(s)} == {"payments"}


# ----- panel / node failures reach the DM, nothing else about panels does -----
async def test_panel_unhealthy_and_failing_nodes_dm_the_admin_but_recoveries_do_not():
    async with open_session() as s:
        await _world(s)
        panel = Panel(name="P1", kind="mock", base_url="https://p.invalid")
        s.add(panel)
        await s.flush()
        panel.health_status, panel.last_health_error = "unhealthy", "timeout"
        await panel_notices.notify_panel_health(s, panel, "healthy")
        await panel_notices.notify_panel_nodes(
            s,
            panel,
            [
                {"name": "n1", "from": "healthy", "to": "error", "message": "down"},
                {"name": "n2", "from": "error", "to": "healthy", "message": None},
            ],
        )
        panel.health_status, panel.last_health_error = "healthy", None
        await panel_notices.notify_panel_health(s, panel, "unhealthy")

        await _tap_queued(s)

        assert await _dms(s) == ["node_failed", "panel_unhealthy"]
        assert await _group(s) == [(ADMIN_GROUP, "panels")] * 4  # unhealthy, node failed, node back, panel back: the group has all
        texts = {r.payload["text"] for r in await _rows(s, events.ADMIN_ALERT)}
        assert any("n1" in t for t in texts) and not any("n2" in t for t in texts)  # the failure notice names only the failing node


async def test_settings_drift_and_capacity_are_group_only():
    async with open_session() as s:
        await _world(s)
        panel = Panel(name="P2", kind="mock", base_url="https://p.invalid")
        panel.settings_drift = {"findings": [{"key": "k1", "state": "drift"}]}
        s.add(panel)
        await s.flush()
        await panel_notices.notify_settings_drift(s, panel, 0, 1)
        await panel_notices.notify_settings_drift(s, panel, 1, 0)
        change = types.SimpleNamespace(kind="capacity", new="95", server="srv-1", detail=None)
        await panel_notices.notify_server_capacity(s, panel, [change])

        await _tap_queued(s)

        assert await _dms(s) == []
        assert await _group(s) == [(ADMIN_GROUP, "panels")] * 3


# ----- everything else is a group notice -----
async def test_a_provisioning_failure_is_a_group_notice_with_the_outcome_and_no_dm():
    async with open_session() as s:
        main, _ = await _world(s)
        order = await make_order(
            s, user=await make_user(s), store=main, product=await make_product(s), status="provisioning_failed", number="A100"
        )
        e = OutboxEvent(
            topic=events.PROVISIONING_FAILED,
            payload={"order_id": str(order.id), "store_id": str(main.id), "error": "panel timeout", "auto_refund": False},
        )
        s.add(e)
        await s.flush()

        await rules.tap(s, e)
        await s.flush()

        assert await _dms(s) == []
        assert await _group(s) == [(ADMIN_GROUP, "errors")]
        (deliver,) = await _rows(s, events.EVENT_CENTER_DELIVER)
        assert "A100" in deliver.payload["text"] and "panel timeout" in deliver.payload["text"] and "دستی" in deliver.payload["text"]


async def test_a_refunded_provisioning_failure_says_the_money_is_back():
    async with open_session() as s:
        main, _ = await _world(s)
        order = await make_order(s, user=await make_user(s), store=main, product=await make_product(s), status="refunded", number="B200")
        e = OutboxEvent(
            topic=events.PROVISIONING_FAILED,
            payload={"order_id": str(order.id), "store_id": str(main.id), "error": "x", "auto_refund": True},
        )
        s.add(e)
        await s.flush()
        await rules.tap(s, e)
        (deliver,) = await _rows(s, events.EVENT_CENTER_DELIVER)
        assert "برگشت داده شد" in deliver.payload["text"] and "دستی" not in deliver.payload["text"]


async def test_reseller_application_alerts_go_to_the_admin_topic_once_and_never_dm():
    async with open_session() as s:
        await _world(s)
        for _ in range(2):  # the same event raised twice (a retry): one notice
            await onboarding.alert_admins(
                s, kind="admin_reseller_application", title="🆕 درخواست نمایندگی جدید", body="«فروشگاه»", key="app-1"
            )
        await s.flush()
        (queued,) = await _rows(s, events.EVENT_CENTER)
        assert queued.payload["topic"] == "admin" and queued.payload["kind"] == "admin_reseller_application"

        await _tap_queued(s)

        assert await _dms(s) == []
        assert await _group(s) == [(ADMIN_GROUP, "admin")]
        (deliver,) = await _rows(s, events.EVENT_CENTER_DELIVER)
        assert deliver.payload["text"].startswith("🆕 درخواست نمایندگی جدید\n")


async def test_backup_infra_and_unknown_kinds_are_group_notices():
    async with open_session() as s:
        await _world(s)
        await events.emit_admin_notice(s, "backup_failed", "💾 پشتیبان‌گیری ناموفق بود")
        await events.emit_admin_notice(s, "infra_disk", "disk")
        await events.emit_admin_notice(s, "something_new", "new thing")  # a kind nobody declared is quiet by default
        await s.flush()

        await _tap_queued(s)

        assert await _dms(s) == []
        assert await _group(s) == [(ADMIN_GROUP, "admin"), (ADMIN_GROUP, "backup"), (ADMIN_GROUP, "errors")]


async def test_the_caller_cannot_widen_the_dm_set_by_naming_a_topic():
    async with open_session() as s:
        await _world(s)
        await events.emit_admin_notice(
            s, "backup_failed", "x", topic="payments"
        )  # the topic is the caller's, the DM decision is the kind's
        await _tap_queued(s)
        assert await _dms(s) == [] and await _group(s) == [(ADMIN_GROUP, "payments")]


# ----- the DM and the group are independent -----
async def test_the_dm_does_not_depend_on_the_group_and_the_group_does_not_depend_on_the_dm():
    async with open_session() as s:
        await _world(s, admin_group=False)  # no admin supergroup configured yet
        await events.emit_admin_notice(s, "node_failed", "🟠 نود(های) پنل «P» خطا دارند:\n• n1")
        await events.emit_admin_notice(s, "panel_recovered", "🟢 پنل «P» دوباره سالم شد")
        await s.flush()

        await _tap_queued(s)

        assert await _dms(s) == ["node_failed"]  # the admin still hears about the failure in the bot
        assert await _group(s) == []  # nothing to deliver to: the recovery notice waits for a group, it is not turned into a DM


@pytest.mark.parametrize("kind", ["panel_unhealthy", "backup_failed", "admin_manual_tasks", "unknown"])
async def test_emit_admin_notice_fills_the_topic_from_the_policy(kind):
    from melorin.domain import messaging_policy

    async with open_session() as s:
        await events.emit_admin_notice(s, kind, "text")
        await s.flush()
        (row,) = await _rows(s, events.EVENT_CENTER)
        assert row.payload["topic"] == messaging_policy.admin_route(kind).topic and row.payload["kind"] == kind
