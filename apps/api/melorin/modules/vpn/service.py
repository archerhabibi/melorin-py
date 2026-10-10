"""Provisioning orchestration: DB state machine + outbox. External panel calls run in workers."""
import datetime as dt
import secrets
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit, events, flags, settings_store
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.domain.order_state import OrderStatus, VpnStatus
from melorin.modules.catalog.models import Product
from melorin.modules.orders.models import Order
from melorin.modules.system.models import OutboxEvent
from melorin.modules.vpn.adapters.base import AccountSpec, ErrorKind, PanelError
from melorin.modules.vpn.adapters.registry import build_adapter
from melorin.modules.vpn.models import Panel, ProvisioningAttempt, ReconciliationIssue, Server, VpnAccount


async def choose_server(session: AsyncSession, product: Product, *, is_test: bool) -> tuple[Server, Panel] | None:
    rows = (await session.execute(select(Server, Panel).join(Panel, Panel.id == Server.panel_id).where(Server.is_enabled.is_(True), Panel.is_enabled.is_(True), Server.allow_test.is_(True) if is_test else True))).all()
    # Health is cached and maintained by health job. Unknown health is not eligible.
    candidates = []
    for server, panel in rows:
        if panel.health_status != "healthy":
            continue
        if server.product_codes and product.code not in server.product_codes:
            continue
        active = await session.scalar(select(func.count()).select_from(VpnAccount).where(VpnAccount.server_id == server.id, VpnAccount.status.in_([VpnStatus.ACTIVE, VpnStatus.PROVISIONING]))) or 0
        if active < server.capacity:
            candidates.append((active, str(server.id), server, panel))
    if not candidates:
        return None
    _, _, server, panel = min(candidates)
    return server, panel


def username(order: Order) -> str:
    return f"m_{order.number.lower()}_{secrets.token_hex(2)}"


async def enqueue(session: AsyncSession, order: Order, *, delay: float = 0) -> None:
    await events.emit(session, events.ORDER_PAID, {"order_id": order.id}, dedup_key=f"provision:{order.id}:{order.provisioning_attempts}", delay_seconds=delay)


async def provision_order(session: AsyncSession, order_id: uuid.UUID) -> str:
    """Called by worker. Claims order with row lock, calls panel outside DB transaction, reconciles result."""
    order = await session.get(Order, order_id, with_for_update=True, populate_existing=True)
    if not order:
        return "missing"
    if order.status not in (OrderStatus.PAID, OrderStatus.PROCESSING, OrderStatus.PROVISIONING):
        return "ignored"
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
    # For an existing renewal account, use its panel. New accounts need server selection.
    account = await session.get(VpnAccount, order.vpn_account_id) if order.vpn_account_id else None
    if account and account.panel_id and account.server_id:
        panel = await session.get(Panel, account.panel_id)
        server = await session.get(Server, account.server_id)
    else:
        chosen = await choose_server(session, product, is_test=order.kind == "test")
        if not chosen:
            order.status = OrderStatus.MANUAL_REVIEW
            order.needs_review = True
            order.last_error = "no healthy compatible server"
            await session.commit()
            await events.emit(session, events.PROVISIONING_FAILED, {"order_id": order.id, "store_id": order.store_id}, dedup_key=f"prov_fail:{order.id}:no_server")
            return "manual_review"
        server, panel = chosen
    order.provisioning_attempts += 1
    attempt = ProvisioningAttempt(order_id=order.id, vpn_account_id=account.id if account else None, attempt_no=order.provisioning_attempts, action="extend" if account else "create", status="running")
    session.add(attempt)
    order.status = OrderStatus.PROVISIONING
    await session.commit()

    adapter = build_adapter(panel)
    try:
        if account:
            # Renewal increases time and volume from the product snapshot, independently of current panel values.
            old_exp = account.expires_at or utcnow()
            expire = max(old_exp, utcnow()) + dt.timedelta(days=product.duration_days)
            # 0 is unlimited. Renewal must never convert it to a finite limit.
            traffic = 0 if account.traffic_limit_bytes == 0 else account.traffic_limit_bytes + (product.traffic_gb * 1024**3 if product.traffic_gb else 0)
            pa = await adapter.extend_account(account.username, expire_at=expire, traffic_bytes=traffic)
        else:
            expire = utcnow() + dt.timedelta(days=product.duration_days)
            traffic = product.traffic_gb * 1024**3 if product.traffic_gb else 0
            account = VpnAccount(username=username(order), user_id=order.user_id, store_id=order.store_id, order_id=order.id, product_id=product.id, server_id=server.id, panel_id=panel.id, status=VpnStatus.PROVISIONING, is_test=order.kind == "test", expires_at=expire, traffic_limit_bytes=traffic)
            session.add(account)
            await session.flush()
            pa = await adapter.create_account(AccountSpec(account.username, expire, traffic, product.max_devices, order.number))
    except PanelError as e:
        attempt.status, attempt.error_kind, attempt.error, attempt.finished_at = "failed", e.kind, e.message, utcnow()
        order.last_error = e.message
        if e.kind == ErrorKind.UNKNOWN:
            # A timeout does not mean the panel rejected the write. Read back
            # before marking manual review, otherwise retries can duplicate.
            try:
                remote = await adapter.get_account(account.username if account else username(order))
            except PanelError:
                remote = None
            if remote:
                if account is None:
                    account = VpnAccount(username=remote.username, user_id=order.user_id, store_id=order.store_id, order_id=order.id, product_id=order.product_id, server_id=server.id, panel_id=panel.id)
                    session.add(account)
                account.panel_ref, account.status = remote.ref, VpnStatus.ACTIVE
                account.expires_at, account.traffic_limit_bytes, account.traffic_used_bytes = remote.expire_at, remote.traffic_limit_bytes, remote.traffic_used_bytes
                account.subscription_url, account.links = remote.subscription_url, remote.links
                attempt.vpn_account_id, attempt.status = account.id, "succeeded"
                order.vpn_account_id, order.status, order.completed_at = account.id, OrderStatus.COMPLETED, utcnow()
                order.last_error, order.needs_review = None, False
                await events.emit(session, events.ORDER_COMPLETED, {"order_id": order.id, "vpn_account_id": account.id, "store_id": order.store_id}, dedup_key=f"order_completed:{order.id}")
                await session.commit()
                return "completed_after_reconcile"
        max_attempts = int(await settings_store.get(session, "provisioning.max_attempts") or 5)
        if e.kind == ErrorKind.TRANSIENT and order.provisioning_attempts < max_attempts:
            order.status = OrderStatus.PROCESSING
            backoff = (await settings_store.get(session, "provisioning.backoff_seconds") or [15, 60, 300, 900, 1800])[min(order.provisioning_attempts - 1, 4)]
            await session.commit()
            await enqueue(session, order, delay=float(backoff))
        else:
            order.status, order.needs_review = OrderStatus.PROVISIONING_FAILED, True
            await session.commit()
            await events.emit(session, events.PROVISIONING_FAILED, {"order_id": order.id, "store_id": order.store_id, "error": e.message}, dedup_key=f"prov_fail:{order.id}")
        return "failed"
    except Exception as e:
        attempt.status, attempt.error_kind, attempt.error, attempt.finished_at = "failed", ErrorKind.UNKNOWN, str(e), utcnow()
        order.status, order.needs_review, order.last_error = OrderStatus.PROVISIONING_FAILED, True, str(e)
        await session.commit()
        await events.emit(session, events.PROVISIONING_FAILED, {"order_id": order.id, "store_id": order.store_id}, dedup_key=f"prov_fail:{order.id}")
        return "failed"

    account.server_id, account.panel_id, account.panel_ref = server.id, panel.id, pa.ref
    account.status = VpnStatus.ACTIVE
    account.expires_at = pa.expire_at
    account.traffic_limit_bytes = pa.traffic_limit_bytes
    account.traffic_used_bytes = pa.traffic_used_bytes
    account.subscription_url, account.links = pa.subscription_url, pa.links
    attempt.vpn_account_id, attempt.status, attempt.finished_at = account.id, "succeeded", utcnow()
    order.vpn_account_id, order.status, order.completed_at = account.id, OrderStatus.COMPLETED, utcnow()
    order.last_error, order.needs_review = None, False
    audit.record(session, "provisioning.completed", actor_type="system", entity_type="vpn_account", entity_id=account.id, store_id=order.store_id, data={"order_id": str(order.id), "panel": panel.kind})
    await events.emit(session, events.ORDER_COMPLETED, {"order_id": order.id, "vpn_account_id": account.id, "store_id": order.store_id}, dedup_key=f"order_completed:{order.id}")
    await events.emit(session, events.NOTIFY, {"user_id": order.user_id, "store_id": order.store_id, "kind": "vpn_account", "title": "اکانت شما آماده شد", "body": "اکانت VPN شما با موفقیت ساخته شد."}, dedup_key=f"notify:account:{account.id}")
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
        account.status = VpnStatus.SUSPENDED; changed = True
    account.traffic_used_bytes = remote.traffic_used_bytes
    account.subscription_url, account.links = remote.subscription_url, remote.links
    if remote.expire_at:
        account.expires_at = remote.expire_at
    await session.commit()
    return "updated" if changed else "ok"
