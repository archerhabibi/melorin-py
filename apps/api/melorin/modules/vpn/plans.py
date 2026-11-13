"""Prepaid renewal ("append") and plan change (PG-09).

Two renewal behaviours, chosen explicitly by the buyer and shown identically in the bot and on the site:

* ``replace`` (default, today's rule, ``vpn.renewal``): the package restarts NOW. Days still left are replaced, not added.
* ``queue`` (this module): the buyer pays now for the NEXT package; the panel starts it by itself when the current one ends
  (``next_plan``), so nothing that was already paid for is burned. Needs a panel that supports ``next_plan_ops`` and a
  panel template mapped to the package (:mod:`melorin.modules.vpn.templates`).

Honest wording on purpose: the panel switches to the queued package when the current one ends **by time or by volume**,
whichever comes first. When the volume ends first, the days still left on the old package are not carried over (the panel's
rule), so the offer states "starts when the current package ends" and never promises a date.

Rules:

* One queue slot per account (``vpn_accounts.queued_plan``); a second prepaid renewal is refused until the first one started.
* Only a live, running account (active, has an end date, not waiting for its first connection) can queue; an expired or
  quota-exhausted account is renewed with ``replace``, which is what that situation needs.
* The queue call is absolute (``next_plan = {template, add_remaining_traffic=false}``), so a retry or a timed-out call that is
  repeated changes nothing; :func:`queued_landed` settles a timed-out call without paying twice.
* The slot is released when the panel no longer reports a queued plan (:func:`settle_from_remote`): the package started.
* Plan change on an existing account (:func:`change_plan`) is admin-only, needs a reason and a mapped template, and is audited.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.domain.order_state import VpnStatus
from melorin.kernel.models.catalog import Product
from melorin.kernel.models.vpn import Panel, VpnAccount
from melorin.modules.panel_integrations.adapters.lifecycle import close_adapter
from melorin.modules.panel_integrations import capabilities as panel_caps
from melorin.modules.vpn import live, notices, sync, templates
from melorin.modules.panel_integrations.adapters.base import ErrorKind, PanelError, supports
from melorin.modules.panel_integrations.adapters.registry import build_adapter, seed_adapter

log = logging.getLogger("melorin.vpn.plans")

REPLACE, QUEUE = "replace", "queue"
MODES = (REPLACE, QUEUE)


def normalize_mode(mode: str | None) -> str:
    mode = (mode or REPLACE).strip().lower()
    if mode not in MODES:
        raise AppError("BAD_RENEWAL_MODE", "نوع تمدید نامعتبر است (replace یا queue).", 400)
    return mode


# ------------------------------------------------------------------------------------------------------------- eligibility
@dataclasses.dataclass(frozen=True)
class QueueCheck:
    ok: bool
    code: str | None = None
    message: str | None = None
    template_id: int | None = None

    def raise_if_not_ok(self) -> None:
        if not self.ok:
            raise AppError(self.code or "QUEUE_NOT_AVAILABLE", self.message or "تمدید پیش‌خرید برای این اکانت ممکن نیست.", 409)


def _no(code: str, message: str) -> QueueCheck:
    return QueueCheck(False, code, message)


async def check_queueable(session: AsyncSession, account: VpnAccount, product: Product, *, now: dt.datetime | None = None) -> QueueCheck:
    """May ``account`` prepay its next package right now? (Ownership/window/open-renewal checks stay with ``renewal.check_renewable``.)"""
    now = sync.aware(now) or utcnow()
    if account.queued_plan:
        return _no("RENEWAL_ALREADY_QUEUED", "پکیج بعدی این اکانت از قبل خریداری شده و پس از پایان پکیج فعلی شروع می‌شود.")
    # Cheap, panel-free refusals first: a package that cannot be queued here never costs a panel call.
    panel = await session.get(Panel, account.panel_id) if account.panel_id else None
    if panel is None or not panel_caps.capabilities_of(panel).has("next_plan_ops"):
        return _no("QUEUE_UNSUPPORTED", "پنل این اکانت از تمدید پیش‌خرید پشتیبانی نمی‌کند.")
    template_id = await templates.template_id_for(session, panel.id, product.id)
    if template_id is None:
        return _no("QUEUE_NO_TEMPLATE", "برای این پکیج روی پنل هنوز تمپلیتی تنظیم نشده است؛ تمدید پیش‌خرید فعال نیست.")
    # R9: "is it running right now?" is the PANEL's answer (live reading). A panel that cannot answer fails closed, but as a
    # refusal of this one mode (the customer still sees the page and the normal renewal), never as a 503 for the whole page.
    reading = (await live.read(session, [account])).get(account.id)
    if reading is None:
        return _no("PANEL_UNAVAILABLE", "پنل در حال حاضر پاسخ نمی‌دهد؛ چند دقیقه بعد دوباره تلاش کنید.")
    on_hold = reading.remote_status == "on_hold"
    expires = sync.aware(reading.expires_at)
    if account.status != VpnStatus.ACTIVE or on_hold or expires is None or expires <= now:
        return _no(
            "QUEUE_NOT_APPLICABLE",
            "تمدید پیش‌خرید فقط برای اکانت فعالِ در حال استفاده ممکن است؛ برای این اکانت از تمدید معمولی استفاده کنید.",
        )
    return QueueCheck(True, template_id=template_id)


def describe_queue(account: VpnAccount, product: Product, *, now: dt.datetime | None = None) -> dict:
    """The promise shown before payment for a prepaid renewal. No invented date: the package starts when the current one ends."""
    now = sync.aware(now) or utcnow()
    expires = sync.aware(account.sold_expires_at)  # what was sold; the pre-payment promise is about the package, not a usage figure
    left = max(0, (expires - now).days) if expires and expires > now else 0
    return {
        "mode": QUEUE,
        "starts": "when_current_ends",  # by time or by volume, whichever comes first (the panel's rule)
        "duration_days": int(product.duration_days),
        "traffic_gb": int(product.traffic_gb or 0),  # 0 = unlimited
        "current_expires_at": expires,
        "remaining_days_kept": left,  # days left on the current package are used up first, not replaced
        "earliest_end_estimate": expires + dt.timedelta(days=int(product.duration_days)) if expires else None,
    }


# ------------------------------------------------------------------------------------------------------------- the queue call
def queued_landed(remote, template_id: int) -> bool:
    """Does the panel already show ``template_id`` as the account's queued package? (Settles a timed-out call.)"""
    plan = getattr(remote, "next_plan", None)
    return bool(getattr(remote, "next_plan_reported", False) and plan and int(plan.get("user_template_id") or 0) == int(template_id))


async def apply_queue(adapter, account: VpnAccount, template_id: int):
    """Queue the package on the panel and make sure the panel really shows it. Absolute value: safe to repeat."""
    pa = await adapter.set_next_plan(account.username, template_id=int(template_id), add_remaining_traffic=False)
    if not queued_landed(pa, template_id):
        pa = await adapter.get_account(account.username)
    if pa is None or not queued_landed(pa, template_id):
        raise PanelError(ErrorKind.TRANSIENT, "pasarguard: the queued package is not visible on the panel yet")
    return pa


def mark_queued(
    account: VpnAccount, *, template_id: int, product_id: uuid.UUID, order_id: uuid.UUID, now: dt.datetime | None = None
) -> None:
    account.queued_plan = {
        "template_id": int(template_id),
        "product_id": str(product_id),
        "order_id": str(order_id),
        "queued_at": (sync.aware(now) or utcnow()).isoformat(),
    }


async def clear_queue_on_panel(adapter, account: VpnAccount) -> None:
    """Drop a queued package (refund of a prepaid renewal). Nothing to do when none is queued."""
    await adapter.clear_next_plan(account.username)
    account.queued_plan = None


async def settle_from_remote(
    session: AsyncSession, account: VpnAccount, remote, *, now: dt.datetime | None = None, notify: bool = True
) -> bool:
    """Release the queue slot once the panel no longer reports a queued package: it started. Returns True when it did.

    Only a panel that really reports ``next_plan`` can say "nothing queued"; for any other panel the field is unknown and the
    slot is left alone. The caller commits.
    """
    if not account.queued_plan or not getattr(remote, "next_plan_reported", False) or getattr(remote, "next_plan", None):
        return False
    started = account.queued_plan
    account.queued_plan = None
    if hasattr(remote, "traffic_limit_bytes"):  # the queued package became the running one: that is the entitlement now (R10)
        sync.record_sale(account, getattr(remote, "expire_at", None), remote.traffic_limit_bytes)
    notices.reset_for_renewal(account)  # the queued package is a fresh period: warn again before ITS end
    if notify:
        await notices.queued_plan_started(session, account)
    audit.record(
        session,
        "vpn_account.queued_plan_started",
        actor_type="system",
        entity_type="vpn_account",
        entity_id=account.id,
        store_id=account.store_id,
        data={"username": account.username, "plan": started},
    )
    return True


# ------------------------------------------------------------------------------------------------------------- plan change
MIN_REASON = 3


async def change_plan(
    session: AsyncSession, account: VpnAccount, product: Product, *, admin_id: uuid.UUID, reason: str, role: str = "admin"
) -> VpnAccount:
    """Move an existing account to ``product``'s template (admin only): groups, volume and time become the new package's.

    The account then belongs to the new package (its renewals use it). A queued prepaid package is dropped (it was bought for
    the old one). Money is NOT handled here: an upgrade the customer pays for goes through a normal order; this is the support tool.
    """
    if role != "admin":
        raise AppError("FORBIDDEN", "این امکان برای شما فعال نیست.", 403)
    reason = (reason or "").strip()
    if len(reason) < MIN_REASON:
        raise AppError("REASON_REQUIRED", "برای تغییر پلن، دلیل را بنویسید.", 400)
    if account.archived_at is not None or account.status not in (
        VpnStatus.ACTIVE,
        VpnStatus.SUSPENDED,
        VpnStatus.EXPIRED,
        VpnStatus.LIMITED,
    ):
        raise AppError("TOOL_UNAVAILABLE", "این اکانت در وضعیتی نیست که بتوان پلن آن را تغییر داد.", 409)
    if account.product_id == product.id:
        raise AppError("SAME_PLAN", "اکانت از قبل روی همین پکیج است.", 409)
    panel = await session.get(Panel, account.panel_id) if account.panel_id else None
    if panel is None or not panel_caps.capabilities_of(panel).has("next_plan_ops"):
        raise AppError("TOOL_UNAVAILABLE", "پنل این اکانت از تغییر پلن پشتیبانی نمی‌کند.", 409)
    template_id = await templates.template_id_for(session, panel.id, product.id)
    if template_id is None:
        raise AppError("QUEUE_NO_TEMPLATE", "برای پکیج مقصد روی پنل تمپلیتی تنظیم نشده است.", 409)
    adapter = build_adapter(panel)
    seed_adapter(adapter, account)
    if not supports(adapter, "next_plan_ops"):
        await close_adapter(adapter)
        raise AppError("TOOL_UNAVAILABLE", "پنل این اکانت از تغییر پلن پشتیبانی نمی‌کند.", 409)
    before = {"product_id": str(account.product_id), "expires_at": account.sold_expires_at.isoformat() if account.sold_expires_at else None,
              "traffic_limit_bytes": account.sold_traffic_bytes}  # fmt: skip
    try:
        pa = await adapter.apply_template(account.username, template_id)
        if account.queued_plan:
            await adapter.clear_next_plan(account.username)
            account.queued_plan = None
    except PanelError as exc:
        raise templates._panel_error(exc) from exc
    finally:
        await close_adapter(adapter)
    old_product = account.product_id
    account.product_id = product.id
    await sync.apply_remote(session, account, pa, notify=False)
    sync.record_sale(account, pa.expire_at, pa.traffic_limit_bytes)  # R10: the new package is what was sold
    notices.reset_for_renewal(account)
    audit.record(
        session,
        "vpn_account.plan_changed",
        actor_id=admin_id,
        actor_type="admin",
        entity_type="vpn_account",
        entity_id=account.id,
        store_id=account.store_id,
        data={"role": role, "username": account.username, "reason": reason[:300], "from_product": str(old_product),
              "to_product": str(product.id), "template_id": template_id, "before": before,
              "after": {"expires_at": account.sold_expires_at.isoformat() if account.sold_expires_at else None,
                        "traffic_limit_bytes": account.sold_traffic_bytes}},
    )  # fmt: skip
    await session.commit()
    return account
