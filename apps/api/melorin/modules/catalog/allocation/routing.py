"""WHERE a new VPN account is created: the pure selection rules plus the loaders that apply them (bundle -> panel -> server)."""

from __future__ import annotations

import dataclasses
import uuid
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from melorin.core.errors import AppError
from melorin.domain.order_state import VpnStatus
from melorin.kernel.models.stores import Store
from melorin.modules.vpn.adapters.base import ErrorKind, PanelError
from melorin.kernel.models.vpn import Panel, Server, VpnAccount
from melorin.kernel.models.bundles import Bundle, BundleMember, BundleProduct, StoreBundle
from melorin.modules.vpn.bundles import clean_custom_name
from melorin.modules.catalog.allocation.offers import sellable_bundles


@dataclasses.dataclass(frozen=True)
class Candidate:
    """A server seen through its panel and (optionally) its group membership. Plain data, no ORM."""

    server_id: uuid.UUID
    server_name: str
    panel_id: uuid.UUID
    panel_name: str
    server_enabled: bool
    panel_enabled: bool
    panel_healthy: bool
    allow_test: bool
    product_codes: tuple[str, ...]
    capacity: int
    active_on_server: int
    active_on_panel: int
    member_enabled: bool = True
    member_sort: int = 0
    member_sales_limit: int | None = None
    member_sold: int = 0


def _reject_reason(
    c: Candidate, *, product_code: str, is_test: bool, group_mode: str | None, selected_panel_id: uuid.UUID | None
) -> str | None:
    if not c.server_enabled:
        return "سرور غیرفعال است"
    if not c.panel_enabled:
        return "پنل غیرفعال است"
    if not c.panel_healthy:
        return "پنل سالم نیست"
    if is_test and not c.allow_test:
        return "اکانت تست برای این سرور مجاز نیست"
    if c.product_codes and product_code not in c.product_codes:
        return f"کد محصول {product_code} در لیست این سرور نیست"
    if group_mode is not None:
        if not c.member_enabled:
            return "عضویت پنل در بسته غیرفعال است"
        if c.member_sales_limit is not None and c.member_sold >= c.member_sales_limit:
            return "سقف فروش پنل در بسته تکمیل شده است"
        if selected_panel_id is not None and c.panel_id != selected_panel_id:
            return "پنل انتخاب‌شده نیست"
    if c.active_on_server >= c.capacity:
        return "ظرفیت سرور پر است"
    return None


def select_allocation(
    candidates: list[Candidate],
    *,
    product_code: str,
    is_test: bool,
    group_mode: str | None = None,
    selected_panel_id: uuid.UUID | None = None,
) -> tuple[Candidate | None, list[str]]:
    """Return (best candidate or None, human-readable reason for every rejected server)."""
    reasons: list[str] = []
    eligible: list[Candidate] = []
    for c in candidates:
        why = _reject_reason(c, product_code=product_code, is_test=is_test, group_mode=group_mode, selected_panel_id=selected_panel_id)
        if why:
            reasons.append(f"{c.server_name}: {why}")
        else:
            eligible.append(c)
    if not eligible:
        return None, reasons
    if group_mode is None:
        key = lambda c: (c.active_on_server, str(c.server_id))  # noqa: E731
    else:
        key = lambda c: (c.active_on_panel, c.member_sort, c.active_on_server, str(c.server_id))  # noqa: E731
    return min(eligible, key=key), reasons


def group_policy_violation(group, *, store_access_enabled: bool | None, selected_panel_id: uuid.UUID | None) -> str | None:
    """The one place that says whether a sales bundle may be used for an order. None = allowed.

    ``store_access_enabled`` is None when the store has no explicit row for the group (= allowed).
    """
    if group is None or not group.is_enabled:
        return "بسته فروش انتخاب‌شده فعال نیست."
    if group.sales_limit is not None and group.sold_count >= group.sales_limit:
        return "ظرفیت فروش این بسته تکمیل شده است."
    if store_access_enabled is False:
        return "این بسته برای فروشگاه فعال نیست."
    if group.selection_mode == "manual" and not selected_panel_id:
        return "برای این بسته باید پنل انتخاب شود."
    if group.selection_mode == "automatic" and selected_panel_id:
        return "در بسته انتخاب خودکار، انتخاب پنل مجاز نیست."
    return None


async def _store_access_enabled(session: AsyncSession, store_id: uuid.UUID | None, group_id: uuid.UUID) -> bool | None:
    if not store_id:
        return None
    row = await session.scalar(select(StoreBundle).where(StoreBundle.store_id == store_id, StoreBundle.bundle_id == group_id))
    return None if row is None else bool(row.is_enabled)


async def _only_bundle_for(session: AsyncSession, store_id: uuid.UUID, product) -> uuid.UUID | None:
    """Packages have no default bundle. When the buyer named none and exactly one bundle can sell the package to
    this store, that bundle is used; with several the buyer must choose (``BUNDLE_REQUIRED``)."""
    store = await session.get(Store, store_id)
    if store is None:
        return None
    ids = [v.group.id for v in await sellable_bundles(session, store)]
    if not ids:
        return None
    sold = (
        await session.scalars(
            select(BundleProduct.bundle_id).where(
                BundleProduct.product_id == product.id, BundleProduct.bundle_id.in_(ids), BundleProduct.is_listed.is_(True)
            )
        )
    ).all()
    return sold[0] if len(sold) == 1 else None


async def resolve_order_group(
    session: AsyncSession,
    *,
    store_id: uuid.UUID | None,
    product,
    bundle_id: uuid.UUID | None = None,
    selected_panel_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Order-creation rule shared by every channel: (bundle id, selected panel id) to store on the order.

    An explicit bundle wins, otherwise the product default applies. No bundle at all is an error (there is no
    direct route). An unusable bundle, or a bundle that does not sell the package, raises here, BEFORE payment.
    """
    group_id = bundle_id or getattr(product, "default_bundle_id", None)
    if group_id is None and store_id is not None and not getattr(product, "is_test", False):
        group_id = await _only_bundle_for(session, store_id, product)  # no default bundle: the single bundle that sells it
    if group_id is None:
        raise AppError("BUNDLE_REQUIRED", "برای خرید باید یک بسته فروش انتخاب شود.", 409)
    group = await session.get(Bundle, group_id)
    why = group_policy_violation(
        group, store_access_enabled=await _store_access_enabled(session, store_id, group_id), selected_panel_id=selected_panel_id
    )
    if why:
        raise AppError("BUNDLE_UNAVAILABLE", why, 409)
    if not getattr(product, "is_test", False):
        sold_here = await session.scalar(
            select(BundleProduct.id).where(BundleProduct.bundle_id == group_id, BundleProduct.product_id == product.id)
        )
        if sold_here is None:
            raise AppError("PRODUCT_NOT_IN_BUNDLE", "این پکیج در بسته انتخاب‌شده فروخته نمی‌شود.", 422)
    if selected_panel_id is not None:
        member = await session.scalar(
            select(BundleMember.id).where(
                BundleMember.bundle_id == group_id, BundleMember.panel_id == selected_panel_id, BundleMember.is_enabled.is_(True)
            )
        )
        if member is None:
            raise AppError("PANEL_NOT_IN_GROUP", "پنل انتخاب‌شده عضو فعال این بسته نیست.", 422)
    return group_id, selected_panel_id


def requested_account_name(group, account_name: str | None) -> str | None:
    """The customer-chosen username part for a bundle. Only "custom" bundles take one, and then it is mandatory.

    Returns the cleaned name (``[A-Za-z0-9_-]``, at most 40 chars) or None for automatic bundles; raises when a
    custom bundle got no usable name, BEFORE any money moves.
    """
    if group.naming_mode != "custom":
        return None
    name = clean_custom_name(account_name or "")
    if len(name) < 3:
        raise AppError("ACCOUNT_NAME_REQUIRED", "نام کاربری اکانت را وارد کنید (حداقل ۳ نویسه: حروف انگلیسی، عدد، _ یا -).", 422)
    return name


async def _active_counts(session: AsyncSession, server_ids: list[uuid.UUID], panel_ids: list[uuid.UUID] | None) -> tuple[dict, dict]:
    """Load every load figure in at most two grouped queries, whatever the number of servers."""
    by_server: dict[uuid.UUID, int] = {}
    by_panel: dict[uuid.UUID, int] = {}
    if server_ids:
        rows = await session.execute(
            select(VpnAccount.server_id, func.count())
            .where(VpnAccount.server_id.in_(server_ids), VpnAccount.status.in_([VpnStatus.ACTIVE, VpnStatus.PROVISIONING]))
            .group_by(VpnAccount.server_id)
        )
        by_server = {sid: int(n) for sid, n in rows.all()}
    if panel_ids:
        rows = await session.execute(
            select(VpnAccount.panel_id, func.count())
            .where(VpnAccount.panel_id.in_(panel_ids), VpnAccount.status == VpnStatus.ACTIVE)
            .group_by(VpnAccount.panel_id)
        )
        by_panel = {pid: int(n) for pid, n in rows.all()}
    return by_server, by_panel


def _candidate(server: Server, panel: Panel, member: BundleMember | None, active_server: int, active_panel: int) -> Candidate:
    return Candidate(
        server_id=server.id,
        server_name=server.name,
        panel_id=panel.id,
        panel_name=panel.name,
        server_enabled=bool(server.is_enabled),
        panel_enabled=bool(panel.is_enabled),
        panel_healthy=panel.health_status == "healthy",
        allow_test=bool(server.allow_test),
        product_codes=tuple(server.product_codes or ()),
        capacity=int(server.capacity or 0),
        active_on_server=active_server,
        active_on_panel=active_panel,
        member_enabled=bool(member.is_enabled) if member else True,
        member_sort=int(member.sort or 0) if member else 0,
        member_sales_limit=member.sales_limit if member else None,
        member_sold=int(member.sold_count or 0) if member else 0,
    )


async def resolve_allocation(session: AsyncSession, order, product) -> tuple[Server, Panel, Bundle | None]:
    """Decide (server, panel, group) for a NEW account. Raises PanelError(PERMANENT) with a reason when impossible."""
    group: Bundle | None = None
    group_mode: str | None = None
    if not order.bundle_id:
        raise PanelError(ErrorKind.PERMANENT, "سفارش بدون بسته فروش قابل ساخت نیست.")
    group = await session.get(Bundle, order.bundle_id, with_for_update=True)
    why = group_policy_violation(
        group,
        store_access_enabled=await _store_access_enabled(session, order.store_id, order.bundle_id),
        selected_panel_id=order.selected_panel_id,
    )
    if why:
        raise PanelError(ErrorKind.PERMANENT, why)
    group_mode = group.selection_mode

    members: dict[uuid.UUID, BundleMember] = {}
    query = select(Server, Panel).join(Panel, Panel.id == Server.panel_id)
    selected = order.selected_panel_id if group_mode else None
    if group is not None:
        rows = (await session.scalars(select(BundleMember).where(BundleMember.bundle_id == group.id))).all()
        members = {m.panel_id: m for m in rows}
        if not members:
            raise PanelError(ErrorKind.PERMANENT, "هیچ پنل قابل فروشی در این بسته وجود ندارد.")
        if selected is not None and selected not in members:
            raise PanelError(ErrorKind.PERMANENT, "پنل انتخاب‌شده عضو این بسته نیست.")
        query = query.where(Server.panel_id.in_(list(members)))

    pairs = (await session.execute(query)).all()
    by_server, by_panel = await _active_counts(
        session, [s.id for s, _ in pairs], list({p.id for _, p in pairs}) if group is not None else None
    )
    candidates = [_candidate(s, p, members.get(p.id), by_server.get(s.id, 0), by_panel.get(p.id, 0)) for s, p in pairs]
    chosen, reasons = select_allocation(
        candidates, product_code=product.code, is_test=order.kind == "test", group_mode=group_mode, selected_panel_id=selected
    )
    if chosen is None:
        detail = "؛ ".join(reasons) if reasons else "هیچ سروری تعریف نشده است"
        raise PanelError(ErrorKind.PERMANENT, f"no healthy compatible server | {detail}")
    server = await session.get(Server, chosen.server_id)
    panel = await session.get(Panel, chosen.panel_id)
    return server, panel, group
