"""WHERE a new VPN account is created: the pure selection rules plus the loaders that apply them (bundle -> panel -> server)."""

from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from melorin.core.db import utcnow
from melorin.domain.panel_health import SELLABLE_STATES
from melorin.core.errors import AppError
from melorin.domain.order_state import VpnStatus
from melorin.kernel.models.stores import Store
from melorin.modules.vpn.adapters.base import ErrorKind, PanelError
from melorin.kernel.models.vpn import Panel, ProvisioningAttempt, Server, VpnAccount
from melorin.kernel.models.bundles import Bundle, BundleMember, BundleProduct, StoreBundle
from melorin.modules.vpn.bundles import clean_custom_name
from melorin.modules.catalog.allocation.offers import sellable_bundles
from melorin.modules.vpn.targets import effective_destination, normalize_target, validate_target
from melorin.domain.timeutil import aware as _aware

BALANCING_MODES = ("round_robin", "least_fill", "fill_first")
DEFAULT_BALANCING = "round_robin"
_MIN_DT = dt.datetime.min.replace(tzinfo=dt.UTC)


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
    last_assigned_at: dt.datetime | None = None  # round_robin key: written once per NEW order, never by a renewal
    server_created_at: dt.datetime | None = None  # fill_first tie-break (oldest destination first)
    target_error: str | None = None  # why the stored target is unusable for its panel kind (None = valid or inherited)
    destination_sellable: bool = True  # PG-08 sell-guard: the destination's group/host/node state on the panel (fail-open default)
    destination_reason: str | None = None


def _reject_reason(
    c: Candidate, *, product_code: str, is_test: bool, group_mode: str | None, selected_panel_id: uuid.UUID | None
) -> str | None:
    if not c.server_enabled:
        return "مقصد غیرفعال است"
    if not c.panel_enabled:
        return "پنل غیرفعال است"
    if not c.panel_healthy:
        return "پنل سالم نیست"
    if c.target_error:
        return f"مقصد نامعتبر است: {c.target_error}"
    if not c.destination_sellable:
        return f"مقصد روی پنل قابل فروش نیست: {c.destination_reason or 'سلامت مقصد تأیید نشده'}"
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
        return "ظرفیت مقصد پر است"
    return None


def _rr_key(c: Candidate):
    """Oldest ``last_assigned_at`` first (never assigned = first). Ties: bundle order, then id."""
    at = _aware(c.last_assigned_at)
    return (at is not None, at or _MIN_DT, c.member_sort, str(c.server_id))


def _fill_ratio(c: Candidate) -> float:
    return c.active_on_server / c.capacity if c.capacity > 0 else 1.0


def _least_fill_key(c: Candidate):
    """Emptiest destination first (active / capacity); ties fall back to the round_robin order."""
    return (_fill_ratio(c), *_rr_key(c))


def _fill_first_key(c: Candidate):
    """Lowest bundle ``sort`` until it is full, then the next one; ties: oldest destination, then id."""
    return (c.member_sort, _aware(c.server_created_at) or _MIN_DT, str(c.server_id))


_BALANCING_KEYS = {"round_robin": _rr_key, "least_fill": _least_fill_key, "fill_first": _fill_first_key}


def select_allocation(
    candidates: list[Candidate],
    *,
    product_code: str,
    is_test: bool,
    group_mode: str | None = None,
    selected_panel_id: uuid.UUID | None = None,
    balancing: str = DEFAULT_BALANCING,
) -> tuple[Candidate | None, list[str]]:
    """Return (best candidate or None, human-readable reason for every rejected server).

    Eligibility is applied first (same for every method), then ``balancing`` orders the survivors.
    """
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
    key = _BALANCING_KEYS.get(balancing) or _rr_key
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
    """The customer-chosen username part for a bundle. Only \"custom\" bundles take one, and it is optional.

    Returns the cleaned name (``[A-Za-z0-9_-]``, at most 40 chars), or None when the bundle is automatic OR the customer left
    the name empty (provisioning then falls back to the automatic naming). A name that was typed but is unusable (fewer than
    3 valid characters) is still refused, BEFORE any money moves, so a typo never silently becomes a different name.
    """
    if group.naming_mode != "custom":
        return None
    if account_name is None or not account_name.strip():
        return None
    name = clean_custom_name(account_name)
    if len(name) < 3:
        raise AppError(
            "ACCOUNT_NAME_INVALID",
            "نام کاربری معتبر نیست (حداقل ۳ نویسه: حروف انگلیسی، عدد، _ یا -). یا آن را خالی بگذارید تا نام‌گذاری خودکار انجام شود.",
            422,
        )
    return name


_LOAD_STATUSES = (VpnStatus.ACTIVE, VpnStatus.PROVISIONING)  # one definition of "load" for panel AND server counts


async def _active_counts(session: AsyncSession, server_ids: list[uuid.UUID], panel_ids: list[uuid.UUID] | None) -> tuple[dict, dict]:
    """Load every load figure in at most two grouped queries, whatever the number of servers."""
    by_server: dict[uuid.UUID, int] = {}
    by_panel: dict[uuid.UUID, int] = {}
    if server_ids:
        rows = await session.execute(
            select(VpnAccount.server_id, func.count())
            .where(VpnAccount.server_id.in_(server_ids), VpnAccount.status.in_(_LOAD_STATUSES))
            .group_by(VpnAccount.server_id)
        )
        by_server = {sid: int(n) for sid, n in rows.all()}
    if panel_ids:
        rows = await session.execute(
            select(VpnAccount.panel_id, func.count())
            .where(VpnAccount.panel_id.in_(panel_ids), VpnAccount.status.in_(_LOAD_STATUSES))
            .group_by(VpnAccount.panel_id)
        )
        by_panel = {pid: int(n) for pid, n in rows.all()}
    return by_server, by_panel


def _candidate(server: Server, panel: Panel, member: BundleMember | None, active_server: int, active_panel: int) -> Candidate:
    from melorin.modules.vpn.capacity import effective_load  # PG-08: capacity_source=panel also counts users created outside Melorin

    active_server = effective_load(server, active_server)
    return Candidate(
        server_id=server.id,
        server_name=server.name,
        panel_id=panel.id,
        panel_name=panel.name,
        server_enabled=bool(server.is_enabled),
        panel_enabled=bool(panel.is_enabled),
        panel_healthy=panel.health_status in SELLABLE_STATES,
        allow_test=bool(server.allow_test),
        product_codes=tuple(server.product_codes or ()),
        capacity=int(server.capacity or 0),
        active_on_server=active_server,
        active_on_panel=active_panel,
        member_enabled=bool(member.is_enabled) if member else True,
        member_sort=int(member.sort or 0) if member else 0,
        member_sales_limit=member.sales_limit if member else None,
        member_sold=int(member.sold_count or 0) if member else 0,
        last_assigned_at=server.last_assigned_at,
        server_created_at=server.created_at,
        destination_sellable=bool(server.sellable) if server.sellable is not None else True,
        destination_reason=server.sellable_reason,
        target_error="؛ ".join(
            validate_target(panel.kind, normalize_target(server.target), api_style=(panel.config or {}).get("api_style"))
        )
        or None,
    )


async def _load_destination(
    session: AsyncSession, server_id: uuid.UUID, panel_id: uuid.UUID, group: Bundle
) -> tuple[Server, Panel, Bundle]:
    """Load the chosen server and panel rows; a row that vanished mid-transaction is a retryable failure, not an AttributeError."""
    server = await session.get(Server, server_id)
    panel = await session.get(Panel, panel_id)
    if server is None or panel is None:
        raise PanelError(ErrorKind.TRANSIENT, "سرور یا پنل انتخاب‌شده دیگر در دسترس نیست؛ تخصیص دوباره تلاش می‌شود.")
    return server, panel, group


async def _pin_must_stay(session: AsyncSession, order) -> bool:
    """True when the order may already have an account on its pinned destination, so it must NOT be moved.

    A live account row, or an earlier attempt whose outcome was UNKNOWN (timeout: the panel may have created the user), means
    a second account on another panel could be a duplicate. Only an order that provably never reached a panel may be re-placed.
    """
    live = await session.scalar(
        select(VpnAccount.id).where(VpnAccount.order_id == order.id, VpnAccount.status.in_(_LOAD_STATUSES)).limit(1)
    )
    if live is not None:
        return True
    unknown = await session.scalar(
        select(ProvisioningAttempt.id)
        .where(ProvisioningAttempt.order_id == order.id, ProvisioningAttempt.error_kind == ErrorKind.UNKNOWN)
        .limit(1)
    )
    return unknown is not None


async def resolve_allocation(session: AsyncSession, order, product) -> tuple[Server, Panel, Bundle | None]:
    """Decide (server, panel, group) for a NEW account. Raises PanelError(PERMANENT) with a reason when impossible.

    Only NEW orders come here: a renewal keeps the account's own server and never allocates (see provisioning).

    * The bundle row is locked for the whole transaction, so two orders of one bundle are allocated one after the other
      (PostgreSQL ``FOR UPDATE``; a no-op on SQLite where there is only one writer).
    * The first allocation PINS the server on the order (``allocated_server_id``) and moves ``last_assigned_at`` once.
      Every retry reuses the pin: no turn is wasted and no duplicate account appears on another panel.
    """
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
    if group is None:  # group_policy_violation() already reports a missing bundle; this narrows the type
        raise PanelError(ErrorKind.PERMANENT, "بسته فروش سفارش پیدا نشد.")
    group_mode = group.selection_mode
    balancing = group.balancing if group.balancing in BALANCING_MODES else DEFAULT_BALANCING

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
    is_test = order.kind == "test"

    pinned_id = getattr(order, "allocated_server_id", None)
    if pinned_id is not None:
        pinned = next((c for c in candidates if c.server_id == pinned_id), None)
        if pinned is not None:
            still_ok = (
                _reject_reason(pinned, product_code=product.code, is_test=is_test, group_mode=group_mode, selected_panel_id=selected)
                is None
            )
            if still_ok or await _pin_must_stay(session, order):
                return await _load_destination(session, pinned.server_id, pinned.panel_id, group)
        elif await _pin_must_stay(session, order):
            raise PanelError(ErrorKind.TRANSIENT, "مقصد ثابت‌شده‌ی سفارش دیگر در بسته نیست و نباید جابه‌جا شود.")
        # the pinned destination is unusable and provably unused: allocate again below (a fresh turn)

    chosen, reasons = select_allocation(
        candidates, product_code=product.code, is_test=is_test, group_mode=group_mode, selected_panel_id=selected, balancing=balancing
    )
    if chosen is None:
        detail = "؛ ".join(reasons) if reasons else "هیچ مقصدی تعریف نشده است"
        raise PanelError(ErrorKind.PERMANENT, f"no healthy compatible server | {detail}")
    server, panel, group = await _load_destination(session, chosen.server_id, chosen.panel_id, group)
    order.allocated_server_id = server.id
    server.last_assigned_at = utcnow()
    return server, panel, group


def placement_snapshot(*, order, group: Bundle | None, panel: Panel, server: Server, remote_ref: str | None) -> dict:
    """Immutable audit snapshot stored on the account at creation. Destination keys only: never credentials, tokens or other config."""
    return {
        "v": 1,
        "allocated_at": utcnow().replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "bundle_id": str(order.bundle_id) if order.bundle_id else None,
        "balancing": (group.balancing if group is not None else None) or DEFAULT_BALANCING,
        "selected_by": "manual" if order.selected_panel_id else "automatic",
        "panel": {"id": str(panel.id), "name": panel.name, "kind": panel.kind},
        "server": {"id": str(server.id), "name": server.name},
        "target": effective_destination(panel.kind, panel.config, server.target),
        "remote_ref": remote_ref,
    }
