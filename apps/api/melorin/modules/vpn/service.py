"""Provisioning orchestration: DB state machine + outbox. External panel calls run in workers."""

import datetime as dt
import logging
import re
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, events, flags, settings_store
from melorin.core.db import utcnow
from melorin.domain.order_state import OrderStatus, VpnStatus
from melorin.modules.catalog.models import Product
from melorin.modules.orders.models import Order
from melorin.modules.stores.models import Store
from melorin.modules.vpn.adapters.base import AccountSpec, ErrorKind, PanelError
from melorin.modules.vpn.adapters.registry import build_adapter
from melorin.modules.vpn import renewal
from melorin.modules.vpn.allocation import resolve_allocation
from melorin.modules.vpn.models import Panel, ProvisioningAttempt, ReconciliationIssue, Server, VpnAccount
from melorin.modules.vpn.bundles import Bundle, BundleMember, clean_custom_name

log = logging.getLogger("melorin.provisioning")


async def _record_bundle_sale(session, order, panel_id):
    if not order.bundle_id or order.kind in ("renewal", "test"):
        return  # renewals reuse an account; test accounts never consume a group's sales quota
    bundle = await session.get(Bundle, order.bundle_id, with_for_update=True)
    if bundle:
        bundle.sold_count += 1
    bp = await session.scalar(
        select(BundleMember).where(BundleMember.bundle_id == order.bundle_id, BundleMember.panel_id == panel_id).with_for_update()
    )
    if bp:
        bp.sold_count += 1


def username(order: Order) -> str:
    return f"m_{order.number.lower()}_{secrets.token_hex(2)}"


async def enqueue(session: AsyncSession, order: Order, *, delay: float = 0) -> None:
    await events.emit(
        session,
        events.ORDER_PAID,
        {"order_id": order.id},
        dedup_key=f"provision:{order.id}:{order.provisioning_attempts}",
        delay_seconds=delay,
    )


# ---------------------------------------------------------------------------
# Provisioning policy: 1 initial attempt + 3 automatic retries (5s, 7s, 10s).
# On exhaustion -> immediate auto-refund.  Admin is ONLY notified, never
# asked to intervene manually.
# ---------------------------------------------------------------------------
_DEFAULT_MAX_ATTEMPTS = 4  # 1 initial + 3 retries
_DEFAULT_BACKOFF = [5, 7, 10]  # seconds before attempt 2, 3, 4


async def _fail(
    session: AsyncSession,
    order: Order,
    message: str,
    *,
    account: VpnAccount | None = None,
) -> str:
    """Handle a provisioning failure for *order*.

    - Retries remain  : mark PROCESSING, schedule a delayed re-enqueue.
    - Retries exhausted: call _give_up() -> auto-refund + admin notify.

    Returns: 'retry_scheduled' | 'refunded' | 'refund_failed'
    """
    max_attempts = int(await settings_store.get(session, "provisioning.max_attempts") or _DEFAULT_MAX_ATTEMPTS)
    delays = await settings_store.get(session, "provisioning.backoff_seconds") or _DEFAULT_BACKOFF
    order.last_error = message

    # If a stub VpnAccount was created but the panel call failed before
    # returning a panel_ref, archive it so the next attempt starts fresh.
    if account is not None and account.status == VpnStatus.PROVISIONING and account.panel_ref is None:
        account.status = VpnStatus.ARCHIVED
        # Mangle the username so UNIQUE does not block the next attempt.
        account.username = account.username[:55] + "_r" + str(order.provisioning_attempts)

    if order.provisioning_attempts < max_attempts:
        delay_idx = min(order.provisioning_attempts - 1, len(delays) - 1)
        delay = float(delays[delay_idx])
        order.status = OrderStatus.PROCESSING
        await session.commit()
        await enqueue(session, order, delay=delay)
        return "retry_scheduled"

    return await _give_up(session, order, message)


async def _give_up(session: AsyncSession, order: Order, message: str) -> str:
    """All retries exhausted: auto-refund immediately and notify admins via outbox.

    Admin is NOT expected to intervene; they receive an informational
    PROVISIONING_FAILED event. The customer money is returned automatically.
    """
    from melorin.modules.orders import service as order_service  # lazy - avoids circular import

    # Capture plain values: after a rollback the ORM instance is expired and
    # touching it in async code would raise MissingGreenlet.
    order_id, store_id = order.id, order.store_id

    order.status = OrderStatus.PROVISIONING_FAILED
    order.needs_review = True  # kept for audit trail; no human action needed
    order.last_error = message

    # Notify admins via outbox (informational only, no action required).
    # Committed together with the status change, BEFORE the refund attempt,
    # so a refund failure can never swallow the alert.
    await events.emit(
        session,
        events.PROVISIONING_FAILED,
        {"order_id": order_id, "store_id": store_id, "error": message, "auto_refund": True},
        dedup_key=f"prov_fail:{order_id}",
        # Short delay: the worker reads the order's final state (refunded or
        # not) to build the Telegram message, so the refund below must be done.
        delay_seconds=10,
    )
    await session.commit()

    # Immediate system refund - no admin required
    try:
        await order_service.auto_refund(session, order_id, reason=message)
    except Exception as exc:  # noqa: BLE001
        # Refund failed (bad state, ledger error, ...). Drop the partial
        # refund work, then persist an audit record so it is visible.
        await session.rollback()
        audit.record(
            session,
            "provisioning.auto_refund_failed",
            actor_type="system",
            entity_type="order",
            entity_id=order_id,
            store_id=store_id,
            data={"reason": str(exc)},
        )
        await session.commit()
        return "refund_failed"

    return "refunded"


async def provision_order(session: AsyncSession, order_id: uuid.UUID) -> str:
    """Called by worker. Claims order with row lock, calls panel outside DB transaction, reconciles result."""
    order = await session.get(Order, order_id, with_for_update=True, populate_existing=True)
    if not order:
        return "missing"
    if order.status not in (OrderStatus.PAID, OrderStatus.PROCESSING, OrderStatus.PROVISIONING):
        return "ignored"
    # A committed provisioning state is the single-writer lease. A second
    # worker must not call the remote panel for the same order concurrently.
    if order.status == OrderStatus.PROVISIONING:
        started = order.updated_at.replace(tzinfo=order.updated_at.tzinfo or dt.UTC) if order.updated_at else utcnow()
        if utcnow() - started < dt.timedelta(minutes=15):
            return "already_claimed"
        order.status = OrderStatus.PROCESSING
    if order.status == OrderStatus.PAID:
        order.status = OrderStatus.PROCESSING
    product = await session.get(Product, order.product_id)
    if not product:
        order.status, order.last_error, order.needs_review = OrderStatus.PROVISIONING_FAILED, "product missing", True
        await session.commit()
        return "failed"
    if not await flags.is_enabled(session, "provisioning", store_id=order.store_id):
        await session.commit()
        return "blocked"
    # Renewals keep their own panel. New accounts are placed by the single allocation core.
    account = await session.get(VpnAccount, order.vpn_account_id) if order.vpn_account_id else None
    if account and account.panel_id and account.server_id:
        panel = await session.get(Panel, account.panel_id)
        server = await session.get(Server, account.server_id)
    else:
        try:
            server, panel, _group = await resolve_allocation(session, order, product)
        except PanelError as e:
            # Allocation failure (no panel/server available).
            # Retry like any transient failure; auto-refund when retries exhausted.
            order.provisioning_attempts += 1
            return await _fail(session, order, e.message)
    order.provisioning_attempts += 1
    attempt = ProvisioningAttempt(
        order_id=order.id,
        vpn_account_id=account.id if account else None,
        attempt_no=order.provisioning_attempts,
        action="extend" if account else "create",
        status="running",
    )
    session.add(attempt)
    order.status = OrderStatus.PROVISIONING
    await session.commit()

    adapter = build_adapter(panel)
    now = utcnow()
    try:
        if account:
            # Renewal = the account becomes exactly what a new account of its package is (core rule: vpn.renewal):
            # package time from now, package volume, usage back to zero. Absolute values, so a retry is harmless.
            pa = await renewal.apply_to_panel(adapter, account, product, now=now)
            expire = renewal.target(product, now=now).expires_at
        else:
            expire = utcnow() + dt.timedelta(days=product.duration_days)
            traffic = product.traffic_gb * 1024**3 if product.traffic_gb else 0
            bundle = await session.get(Bundle, order.bundle_id) if order.bundle_id else None
            if bundle and bundle.naming_mode == "custom":
                generated_name = f"{clean_custom_name(order.requested_account_name)}_{order.number}"
            elif bundle:
                prefix = re.sub(r"[^A-Za-z0-9]", "", panel.name)[:4] or "Pnl"
                store = await session.get(Store, order.store_id)
                generated_name = (
                    f"{prefix}_{product.traffic_gb}G{re.sub(r'[^A-Za-z0-9]', '', (store.name if store else 'S'))[:1]}{order.number}"
                )
            else:
                generated_name = username(order)
            account = VpnAccount(
                username=generated_name[:64],
                user_id=order.user_id,
                store_id=order.store_id,
                order_id=order.id,
                product_id=product.id,
                server_id=server.id,
                panel_id=panel.id,
                status=VpnStatus.PROVISIONING,
                is_test=order.kind == "test",
                expires_at=expire,
                traffic_limit_bytes=traffic,
            )
            session.add(account)
            await session.flush()
            pa = await adapter.create_account(AccountSpec(account.username, expire, traffic, product.max_devices, order.number))
    except PanelError as e:
        attempt.status, attempt.error_kind, attempt.error, attempt.finished_at = ("failed", e.kind, e.message, utcnow())
        if e.kind == ErrorKind.UNKNOWN:
            # A timeout does NOT mean the panel rejected the write. Read back
            # before giving up to avoid duplicating accounts on retry.
            try:
                remote = await adapter.get_account(account.username if account else username(order))
            except PanelError:
                remote = None
            # For a renewal the account already exists on the panel, so "it exists" proves nothing: only a panel that
            # already shows the renewed time/volume counts as success, otherwise the (idempotent) renewal is retried.
            if remote and (order.kind != "renewal" or renewal.landed(remote, product, now=now)):
                # The panel actually succeeded despite the timeout - reconcile.
                if account is None:
                    account = VpnAccount(
                        username=remote.username,
                        user_id=order.user_id,
                        store_id=order.store_id,
                        order_id=order.id,
                        product_id=order.product_id,
                        server_id=server.id,
                        panel_id=panel.id,
                    )
                    session.add(account)
                account.panel_ref, account.status = remote.ref, VpnStatus.ACTIVE
                account.expires_at = remote.expire_at
                account.traffic_limit_bytes = remote.traffic_limit_bytes
                account.traffic_used_bytes = remote.traffic_used_bytes
                account.subscription_url, account.links = remote.subscription_url, remote.links
                attempt.vpn_account_id, attempt.status = account.id, "succeeded"
                order.vpn_account_id = account.id
                order.status, order.completed_at = OrderStatus.COMPLETED, utcnow()
                order.last_error, order.needs_review = None, False
                await events.emit(
                    session,
                    events.ORDER_COMPLETED,
                    {"order_id": order.id, "vpn_account_id": account.id, "store_id": order.store_id},
                    dedup_key=f"order_completed:{order.id}",
                )
                await events.emit(
                    session,
                    events.ORDER_DELIVERY,
                    {"order_id": order.id, "store_id": order.store_id},
                    dedup_key=f"order_delivery:{order.id}",
                )
                await session.commit()
                return "completed_after_reconcile"
        # Both TRANSIENT and unreconciled UNKNOWN errors feed the same
        # retry/give-up logic. _fail() schedules the next attempt or
        # triggers an immediate auto-refund when retries are exhausted.
        # Admin is only notified, never asked to intervene manually.
        return await _fail(session, order, e.message, account=account)
    except Exception as e:
        log.warning("provisioning failed unexpectedly order=%s", order.id, exc_info=True)
        attempt.status = "failed"
        attempt.error_kind, attempt.error, attempt.finished_at = ErrorKind.UNKNOWN, str(e), utcnow()
        return await _fail(session, order, str(e), account=account)

    account.server_id, account.panel_id, account.panel_ref = server.id, panel.id, pa.ref
    account.status = VpnStatus.ACTIVE
    account.expires_at = pa.expire_at
    account.traffic_limit_bytes = pa.traffic_limit_bytes
    account.traffic_used_bytes = pa.traffic_used_bytes
    account.subscription_url, account.links = pa.subscription_url, pa.links
    attempt.vpn_account_id, attempt.status, attempt.finished_at = account.id, "succeeded", utcnow()
    order.vpn_account_id, order.status, order.completed_at = account.id, OrderStatus.COMPLETED, utcnow()
    order.last_error, order.needs_review = None, False
    await _record_bundle_sale(session, order, panel.id)
    audit.record(
        session,
        "provisioning.completed",
        actor_type="system",
        entity_type="vpn_account",
        entity_id=account.id,
        store_id=order.store_id,
        data={"order_id": str(order.id), "panel": panel.kind},
    )
    await events.emit(
        session,
        events.ORDER_COMPLETED,
        {"order_id": order.id, "vpn_account_id": account.id, "store_id": order.store_id},
        dedup_key=f"order_completed:{order.id}",
    )
    # One rich Telegram post (QR + subscription link + wallet balance) instead of a generic notice.
    await events.emit(
        session, events.ORDER_DELIVERY, {"order_id": order.id, "store_id": order.store_id}, dedup_key=f"order_delivery:{order.id}"
    )
    await session.commit()
    return "completed"


async def reconcile(session: AsyncSession, account_id: uuid.UUID) -> str:
    account = await session.get(VpnAccount, account_id)
    if not account or not account.panel_id:
        return "missing"
    panel = await session.get(Panel, account.panel_id)
    adapter = build_adapter(panel)
    try:
        remote = await adapter.get_account(account.username)
    except PanelError as e:
        session.add(ReconciliationIssue(vpn_account_id=account.id, kind="panel_unreachable", details={"error": e.message}))
        await session.commit()
        return "issue"
    if not remote:
        session.add(ReconciliationIssue(vpn_account_id=account.id, kind="missing_on_panel", details={"username": account.username}))
        await session.commit()
        return "issue"
    changed = False
    if account.status == VpnStatus.ACTIVE and remote.status == "disabled":
        account.status = VpnStatus.SUSPENDED
        changed = True
    account.traffic_used_bytes = remote.traffic_used_bytes
    account.subscription_url, account.links = remote.subscription_url, remote.links
    if remote.expire_at:
        account.expires_at = remote.expire_at
    await session.commit()
    return "updated" if changed else "ok"
