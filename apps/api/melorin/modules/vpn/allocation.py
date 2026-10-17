"""Single allocation core: WHERE a new VPN account is created is decided here and nowhere else.

Vocabulary: a *pool* (UI: بسته فروش) is a ``PanelGroup``. Every account is sold through exactly one
pool; there is no pool-less route.

The channels (Telegram bot, store website, reseller panel, admin, API) say *what* is bought and, when the
customer is allowed to choose, *which pool* (and in a manual pool *which panel*). They never choose a
server. The core validates every choice and decides the rest:

    pool = the pool named on the order, else the product's default pool
    pool --enabled members--> panel --enabled server with matching product code--> server

A pool must sell the package (``PoolProduct``), be enabled, have capacity and be open to the store.

Two entry points share the same rules:

* ``resolve_order_group``  - called when an order is CREATED (before any money moves). It applies the
  product default group and rejects an unusable group with a clear error instead of letting a paid
  order fall into manual review.
* ``resolve_allocation``   - called when the order is PROVISIONED. It re-checks the group (state may
  have changed since checkout) and picks the (server, panel).

Everything about the SALE route lives here too, so no channel and no other module decides it:

* ``plan_sale``           - the one entry point for "what does this purchase/renewal/quote mean": pool,
  panel choice, account name, package membership and the price (a pool may override the product price).
* the prices: ``main_price`` (store), ``reseller_price`` (cost, may differ per pool) and the reseller's
  retail price, which has two levels: ``StoreProduct.customer_price`` (the store-wide price of a package)
  and ``StorePoolPrice`` (the price of that package in ONE pool, which wins when set). A retail price below
  the reseller price of the pool being sold is never allowed: it is refused when set, hidden from every
  list and refused again at checkout (``CUSTOMER_PRICE_BELOW_COST``).
* ``sellable_pools`` / ``pool_packages`` / ``renewal_offers`` / ``sellable_products`` - what a customer may
  be shown. ``catalog`` and ``orders`` only call these; they hold no pool, membership or price rule.

Selection itself is a pure function (``select_allocation``) fed by a loader, so the rules can be
unit-tested without a database.
"""

from __future__ import annotations

import dataclasses
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.errors import AppError, NotFound
from melorin.domain.order_state import VpnStatus
from melorin.modules.catalog import service as catalog_service
from melorin.modules.catalog.models import Product, StorePoolPrice, StoreProduct
from melorin.modules.stores.models import Store
from melorin.modules.vpn.adapters.base import ErrorKind, PanelError
from melorin.modules.vpn.models import Panel, Server, VpnAccount
from melorin.modules.vpn.panel_groups import PanelGroup, PanelGroupMember, PoolProduct, StorePanelGroup, clean_custom_name


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


def _reject_reason(c: Candidate, *, product_code: str, is_test: bool, group_mode: str | None, selected_panel_id: uuid.UUID | None) -> str | None:
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
    """The one place that says whether a panel group may be used for an order. None = allowed.

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
    row = await session.scalar(select(StorePanelGroup).where(StorePanelGroup.store_id == store_id, StorePanelGroup.panel_group_id == group_id))
    return None if row is None else bool(row.is_enabled)


async def resolve_order_group(
    session: AsyncSession,
    *,
    store_id: uuid.UUID | None,
    product,
    panel_group_id: uuid.UUID | None = None,
    selected_panel_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Order-creation rule shared by every channel: (pool id, selected panel id) to store on the order.

    An explicit pool wins, otherwise the product default applies. No pool at all is an error (there is no
    direct route). An unusable pool, or a pool that does not sell the package, raises here, BEFORE payment.
    """
    group_id = panel_group_id or getattr(product, "default_panel_group_id", None)
    if group_id is None:
        raise AppError("POOL_REQUIRED", "برای خرید باید یک بسته فروش انتخاب شود.", 409)
    group = await session.get(PanelGroup, group_id)
    why = group_policy_violation(group, store_access_enabled=await _store_access_enabled(session, store_id, group_id), selected_panel_id=selected_panel_id)
    if why:
        raise AppError("PANEL_GROUP_UNAVAILABLE", why, 409)
    if not getattr(product, "is_test", False):
        sold_here = await session.scalar(select(PoolProduct.id).where(PoolProduct.panel_group_id == group_id, PoolProduct.product_id == product.id))
        if sold_here is None:
            raise AppError("PRODUCT_NOT_IN_POOL", "این پکیج در بسته انتخاب‌شده فروخته نمی‌شود.", 422)
    if selected_panel_id is not None:
        member = await session.scalar(
            select(PanelGroupMember.id).where(
                PanelGroupMember.panel_group_id == group_id, PanelGroupMember.panel_id == selected_panel_id, PanelGroupMember.is_enabled.is_(True)
            )
        )
        if member is None:
            raise AppError("PANEL_NOT_IN_GROUP", "پنل انتخاب‌شده عضو فعال این بسته نیست.", 422)
    return group_id, selected_panel_id


def requested_account_name(group, account_name: str | None) -> str | None:
    """The customer-chosen username part for a pool. Only "custom" pools take one, and then it is mandatory.

    Returns the cleaned name (``[A-Za-z0-9_-]``, at most 40 chars) or None for automatic pools; raises when a
    custom pool got no usable name, BEFORE any money moves.
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


def _candidate(server: Server, panel: Panel, member: PanelGroupMember | None, active_server: int, active_panel: int) -> Candidate:
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


async def resolve_allocation(session: AsyncSession, order, product) -> tuple[Server, Panel, PanelGroup | None]:
    """Decide (server, panel, group) for a NEW account. Raises PanelError(PERMANENT) with a reason when impossible."""
    group: PanelGroup | None = None
    group_mode: str | None = None
    if not order.panel_group_id:
        raise PanelError(ErrorKind.PERMANENT, "سفارش بدون بسته فروش قابل ساخت نیست.")
    group = await session.get(PanelGroup, order.panel_group_id, with_for_update=True)
    why = group_policy_violation(
        group,
        store_access_enabled=await _store_access_enabled(session, order.store_id, order.panel_group_id),
        selected_panel_id=order.selected_panel_id,
    )
    if why:
        raise PanelError(ErrorKind.PERMANENT, why)
    group_mode = group.selection_mode

    members: dict[uuid.UUID, PanelGroupMember] = {}
    query = select(Server, Panel).join(Panel, Panel.id == Server.panel_id)
    selected = order.selected_panel_id if group_mode else None
    if group is not None:
        rows = (await session.scalars(select(PanelGroupMember).where(PanelGroupMember.panel_group_id == group.id))).all()
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
    candidates = [
        _candidate(s, p, members.get(p.id), by_server.get(s.id, 0), by_panel.get(p.id, 0)) for s, p in pairs
    ]
    chosen, reasons = select_allocation(candidates, product_code=product.code, is_test=order.kind == "test", group_mode=group_mode, selected_panel_id=selected)
    if chosen is None:
        detail = "؛ ".join(reasons) if reasons else "هیچ سروری تعریف نشده است"
        raise PanelError(ErrorKind.PERMANENT, f"no healthy compatible server | {detail}")
    server = await session.get(Server, chosen.server_id)
    panel = await session.get(Panel, chosen.panel_id)
    return server, panel, group


# ---------------------------------------------------------------- sale route (UI: بسته فروش)
async def pool_product(session: AsyncSession, group_id: uuid.UUID | None, product_id: uuid.UUID) -> PoolProduct | None:
    if group_id is None:
        return None
    return await session.scalar(select(PoolProduct).where(PoolProduct.panel_group_id == group_id, PoolProduct.product_id == product_id))


async def account_pool_id(session: AsyncSession, account) -> uuid.UUID | None:
    """The pool an account was originally sold through (renewals are priced and listed from the same pool)."""
    from melorin.modules.orders.models import Order

    order = await session.get(Order, account.order_id) if getattr(account, "order_id", None) else None
    return order.panel_group_id if order else None


def effective_prices(product: Product, pp: PoolProduct | None) -> tuple[int, int]:
    """(main_price, reseller_price) for a package inside a pool: the pool's override, else the product's own."""
    main = pp.main_price if pp is not None and pp.main_price is not None else product.main_price
    reseller = pp.reseller_price if pp is not None and pp.reseller_price is not None else product.reseller_price
    return main, reseller


def retail_price(sp: StoreProduct | None, pool_price: int | None) -> int | None:
    """What a reseller store charges for one package in one pool: the pool's own price when the reseller set
    one, otherwise the store-wide price of the package. None = no price (the package is not sold there)."""
    return pool_price or (sp.customer_price if sp else None) or None


def _below_cost(price: int | None, reseller_price: int) -> bool:
    return bool(price) and price < reseller_price


def _unit_price(store: Store, product: Product, retail: int | None, pp: PoolProduct | None) -> int:
    if store.kind == "reseller":
        return retail or 0
    return effective_prices(product, pp)[0]


async def store_pool_prices(
    session: AsyncSession, store_id: uuid.UUID, *, group_id: uuid.UUID | None = None
) -> dict[tuple[uuid.UUID, uuid.UUID], int]:
    """The store's own per-pool retail prices as ``{(pool id, product id): price}`` (one query)."""
    q = select(StorePoolPrice).where(StorePoolPrice.store_id == store_id)
    if group_id is not None:
        q = q.where(StorePoolPrice.panel_group_id == group_id)
    return {(r.panel_group_id, r.product_id): int(r.customer_price) for r in (await session.scalars(q)).all()}


@dataclasses.dataclass(frozen=True)
class SalePlan:
    """The core's answer for one sale: where it goes, what name it gets and what it costs."""

    group_id: uuid.UUID | None
    group: PanelGroup | None
    selected_panel_id: uuid.UUID | None
    account_name: str | None
    pool_product: PoolProduct | None
    unit_price: int
    main_price: int
    reseller_price: int

    @property
    def prices(self) -> tuple[int, int]:
        return self.main_price, self.reseller_price


async def plan_sale(
    session: AsyncSession,
    *,
    store: Store,
    product: Product,
    sp: StoreProduct | None,
    kind: str = "purchase",
    account=None,
    panel_group_id: uuid.UUID | None = None,
    selected_panel_id: uuid.UUID | None = None,
    account_name: str | None = None,
    enforce: bool = True,
) -> SalePlan:
    """Decide a sale (or a quote of one) for every channel. Raises BEFORE any money moves.

    * purchase: pool (explicit, else the product default; none = ``POOL_REQUIRED``), package membership,
      panel choice, custom account name, and the pool's price.
    * renewal: the pool the account was originally sold through (none for accounts that predate pools =
      the product's own price). No new pool, panel or name can be chosen.
    * ``enforce=False`` is for price previews that name no pool (coupon check): no validation, the
      product's default pool price.
    """
    if kind == "renewal":
        group_id = await account_pool_id(session, account) if account is not None else None
        selected, name = None, None
    elif enforce:
        group_id, selected = await resolve_order_group(
            session, store_id=store.id, product=product, panel_group_id=panel_group_id, selected_panel_id=selected_panel_id
        )
        name = requested_account_name(await session.get(PanelGroup, group_id), account_name)
    else:
        group_id, selected, name = panel_group_id or product.default_panel_group_id, None, None
    pp = await pool_product(session, group_id, product.id)
    main, reseller = effective_prices(product, pp)
    group = await session.get(PanelGroup, group_id) if group_id else None
    retail = None
    if store.kind == "reseller":
        own = (await store_pool_prices(session, store.id, group_id=group_id)).get((group_id, product.id)) if group_id else None
        retail = retail_price(sp, own)
        if _below_cost(retail, reseller):
            raise AppError("CUSTOMER_PRICE_BELOW_COST", "قیمت فروش نماینده از قیمت همکاری این بسته کمتر است؛ فروش انجام نمی‌شود.", 409)
    return SalePlan(group_id, group, selected, name, pp, _unit_price(store, product, retail, pp), main, reseller)


@dataclasses.dataclass(frozen=True)
class PoolView:
    group: PanelGroup
    panels: list[tuple[uuid.UUID, str]]  # manual pools only: (panel id, label the customer sees)


async def pool_packages(session: AsyncSession, store: Store, group_id: uuid.UUID) -> list[tuple[Product, StoreProduct, PoolProduct, int]]:
    """Packages a customer of ``store`` can buy in one pool, each with the price shown to that customer."""
    q = (
        select(Product, StoreProduct, PoolProduct)
        .join(PoolProduct, (PoolProduct.product_id == Product.id) & (PoolProduct.panel_group_id == group_id))
        .join(StoreProduct, (StoreProduct.product_id == Product.id) & (StoreProduct.store_id == store.id))
        .where(
            Product.is_active.is_(True), Product.archived_at.is_(None), Product.is_test.is_(False),
            StoreProduct.is_enabled.is_(True), StoreProduct.is_listed.is_(True), PoolProduct.is_listed.is_(True),
        )
    )
    out = []
    own = await store_pool_prices(session, store.id, group_id=group_id) if store.kind == "reseller" else {}
    for p, sp, pp in (await session.execute(q)).all():
        retail = None
        if store.kind == "reseller":
            retail = retail_price(sp, own.get((group_id, p.id)))
            if not retail or _below_cost(retail, effective_prices(p, pp)[1]):
                continue
        elif p.currency != store.currency:
            continue
        out.append((p, sp, pp, _unit_price(store, p, retail, pp)))
    out.sort(key=lambda r: (r[2].sort, r[3], r[0].sort))
    return out


async def sellable_pools(session: AsyncSession, store: Store) -> list[PoolView]:
    """Pools a customer of ``store`` may see: enabled, not sold out, open to the store, with a sellable package
    and (manual pools) at least one healthy panel the customer can pick."""
    q = select(PanelGroup).where(PanelGroup.is_enabled.is_(True))
    q = q.outerjoin(StorePanelGroup, (StorePanelGroup.panel_group_id == PanelGroup.id) & (StorePanelGroup.store_id == store.id))
    if store.kind == "reseller":
        q = q.where(PanelGroup.reseller_enabled.is_(True))
    q = q.where(StorePanelGroup.id.is_(None) | StorePanelGroup.is_enabled.is_(True))
    out: list[PoolView] = []
    for g in (await session.scalars(q.order_by(PanelGroup.created_at))).all():
        if g.sales_limit is not None and g.sold_count >= g.sales_limit:
            continue
        if not await pool_packages(session, store, g.id):
            continue
        panels: list[tuple[uuid.UUID, str]] = []
        if g.selection_mode == "manual":
            rows = (await session.execute(
                select(PanelGroupMember, Panel).join(Panel, Panel.id == PanelGroupMember.panel_id)
                .where(PanelGroupMember.panel_group_id == g.id, PanelGroupMember.is_enabled.is_(True), Panel.is_enabled.is_(True), Panel.health_status == "healthy")
                .order_by(PanelGroupMember.sort)
            )).all()
            panels = [(m.panel_id, m.label or f"گزینه {i + 1}") for i, (m, _) in enumerate(rows) if m.sales_limit is None or m.sold_count < m.sales_limit]
            if not panels:
                continue
        out.append(PoolView(g, panels))
    return out


async def packages_for_pool(session: AsyncSession, store: Store, pool_id: uuid.UUID) -> list[tuple[Product, StoreProduct, PoolProduct, int]]:
    if pool_id not in {v.group.id for v in await sellable_pools(session, store)}:
        raise NotFound("بسته فروش")
    return await pool_packages(session, store, pool_id)


async def renewal_offers(session: AsyncSession, store: Store, account) -> list[tuple[Product, int]]:
    """(package, price) a customer may renew ``account`` with: the original pool's packages and prices.
    Accounts that predate pools renew at the product's own price."""
    pool_id = await account_pool_id(session, account)
    if pool_id is None:
        return [(p, _unit_price(store, p, retail_price(sp, None), None)) for p, sp in await sellable_products(session, store)]
    return [(p, price) for p, _sp, _pp, price in await pool_packages(session, store, pool_id)]


async def sellable_products_priced(session: AsyncSession, store: Store) -> list[tuple[Product, StoreProduct, int]]:
    """Flat catalog with the price to show: only products that at least one pool lists and (reseller stores)
    whose retail price covers that pool's reseller price. A reseller package that is priced per pool shows its
    lowest valid pool price. A product in no pool is never shown (there is no pool-less route)."""
    pps: dict[uuid.UUID, list[PoolProduct]] = {}
    for pp in (await session.scalars(select(PoolProduct).where(PoolProduct.is_listed.is_(True)))).all():
        pps.setdefault(pp.product_id, []).append(pp)
    own = await store_pool_prices(session, store.id) if store.kind == "reseller" else {}
    out = []
    for p, sp in await catalog_service.store_catalog(session, store):
        rows = pps.get(p.id, [])
        if store.kind == "reseller":
            prices = []
            for pp in rows:
                retail = retail_price(sp, own.get((pp.panel_group_id, p.id)))
                if retail and not _below_cost(retail, effective_prices(p, pp)[1]):
                    prices.append(retail)
            if prices:
                out.append((p, sp, min(prices)))
        elif rows:
            out.append((p, sp, p.main_price))
    return out


async def sellable_products(session: AsyncSession, store: Store) -> list[tuple[Product, StoreProduct]]:
    """``sellable_products_priced`` without the price, for callers that only need to know what is sellable."""
    return [(p, sp) for p, sp, _price in await sellable_products_priced(session, store)]


async def reseller_price_floor(session: AsyncSession, product: Product) -> int:
    """The lowest customer price a reseller may set: the highest reseller price over the pools selling the product."""
    rows = (await session.scalars(select(PoolProduct).where(PoolProduct.product_id == product.id))).all()
    return max((effective_prices(product, pp)[1] for pp in rows), default=product.reseller_price)


async def ensure_customer_price(session: AsyncSession, product: Product, customer_price: int | None) -> None:
    """Refuse a reseller retail price below the reseller price of any pool that sells the product."""
    if not customer_price:
        return
    floor = await reseller_price_floor(session, product)
    if customer_price < floor:
        raise AppError("CUSTOMER_PRICE_BELOW_COST", f"قیمت فروش نماینده نمی‌تواند از قیمت همکاری بسته‌ها ({floor}) کمتر باشد.", 422)


async def stores_below_cost(session: AsyncSession, product: Product, reseller_price: int, group_id: uuid.UUID | None = None) -> int:
    """How many reseller stores would have this product hidden if a pool's reseller price became ``reseller_price``.

    With ``group_id`` the check is exact for that pool: a store's own price in the pool wins over its store-wide
    price. Without it only the store-wide prices are compared (legacy callers)."""
    rows = (await session.execute(
        select(StoreProduct.store_id, StoreProduct.customer_price).join(Store, Store.id == StoreProduct.store_id).where(
            StoreProduct.product_id == product.id, Store.kind == "reseller")
    )).all()
    own: dict[uuid.UUID, int] = {}
    if group_id is not None:
        own = {r.store_id: int(r.customer_price) for r in (await session.scalars(
            select(StorePoolPrice).where(StorePoolPrice.panel_group_id == group_id, StorePoolPrice.product_id == product.id))).all()}
    hidden = {sid for sid, price in rows if _below_cost(own.get(sid) or price or None, reseller_price)}
    hidden |= {sid for sid, price in own.items() if _below_cost(price, reseller_price)}
    return len(hidden)


# ---------------------------------------------------------------- what a reseller prices (panel + bot)
def _pool_state(price: int | None, cost: int) -> str:
    return "unset" if not price else ("below_cost" if price < cost else "ok")


async def reseller_price_table(session: AsyncSession, store: Store) -> list[dict]:
    """What a reseller sees when pricing: every product the main store enabled for this store and that some
    pool sells. Per product: the store-wide price (``customer_price``), the cost floor over all pools and, in
    ``pools``, one row per pool with its cost (reseller price), the store's own price there, the price that is
    actually charged (``effective_price``, ``source`` = pool | store) and the resulting state.
    The pool-level ``costs`` list is kept for older clients (Telegram bot)."""
    pool_rows = (await session.execute(select(PoolProduct, PanelGroup).join(PanelGroup, PanelGroup.id == PoolProduct.panel_group_id))).all()
    by_product: dict[uuid.UUID, list[tuple[PoolProduct, PanelGroup]]] = {}
    for pp, g in pool_rows:
        by_product.setdefault(pp.product_id, []).append((pp, g))
    own = await store_pool_prices(session, store.id)
    closed = {r.panel_group_id for r in (await session.scalars(
        select(StorePanelGroup).where(StorePanelGroup.store_id == store.id, StorePanelGroup.is_enabled.is_(False)))).all()}
    out = []
    for p, sp in await catalog_service.enabled_for_store(session, store):
        rows = by_product.get(p.id)
        if not rows:
            continue
        costs = [{"pool_id": g.id, "pool_name": g.name, "cost": effective_prices(p, pp)[1]} for pp, g in rows]
        floor = max(c["cost"] for c in costs)
        price = sp.customer_price or None
        pools = []
        for pp, g in sorted(rows, key=lambda r: (r[1].created_at, str(r[1].id))):
            if not g.is_enabled or not g.reseller_enabled:
                continue  # a pool the reseller cannot sell through is not worth pricing
            cost = effective_prices(p, pp)[1]
            mine = own.get((g.id, p.id))
            effective = retail_price(sp, mine)
            pools.append({
                "pool_id": g.id, "pool_name": g.name, "kind_label": g.kind_label, "cost": cost, "price": mine, "effective_price": effective,
                "source": "pool" if mine else ("store" if effective else None), "state": _pool_state(effective, cost),
                "listed": bool(pp.is_listed), "open_for_store": g.id not in closed,
            })
        out.append({
            "product_id": p.id, "code": p.code, "name": p.name, "duration_days": p.duration_days, "traffic_gb": p.traffic_gb,
            "currency": p.currency, "customer_price": price, "cost_floor": floor, "costs": costs, "pools": pools,
            "state": "unset" if price is None else ("below_cost" if price < floor else "ok"),
        })
    return out


async def _priced_product(session: AsyncSession, store: Store, product_id: uuid.UUID) -> tuple[Product, StoreProduct]:
    """The product a reseller may price: enabled for the store by the main store, active, not a test package."""
    if store.kind != "reseller":
        raise AppError("NOT_A_RESELLER_STORE", "قیمت فروش فقط برای فروشگاه نماینده تعیین می‌شود.", 403)
    product = await session.get(Product, product_id)
    sp = await session.scalar(select(StoreProduct).where(StoreProduct.store_id == store.id, StoreProduct.product_id == product_id))
    if not product or not sp or not sp.is_enabled or product.is_test or not product.is_active or product.archived_at is not None:
        raise NotFound("محصول")
    return product, sp


async def set_customer_price(session: AsyncSession, store: Store, product_id: uuid.UUID, customer_price: int | None) -> StoreProduct:
    """The reseller sets the store-wide retail price of one product in ONE store. None or 0 clears it.
    The price must cover the reseller price of every pool that sells the product; a pool can still have its own
    price (``set_pool_price``), which wins there."""
    product, sp = await _priced_product(session, store, product_id)
    if await session.scalar(select(PoolProduct.id).where(PoolProduct.product_id == product_id).limit(1)) is None:
        raise AppError("PRODUCT_NOT_IN_POOL", "این محصول در هیچ بسته‌ای نیست و قابل فروش نیست.", 422)
    await ensure_customer_price(session, product, customer_price)
    sp.customer_price = customer_price or None
    return sp


async def set_pool_price(
    session: AsyncSession, store: Store, group_id: uuid.UUID, product_id: uuid.UUID, customer_price: int | None
) -> int | None:
    """The reseller sets the retail price of one package in ONE pool of this store. None or 0 removes it and the
    pool falls back to the store-wide price. The price must cover THIS pool's reseller price (the cost).
    Returns the stored price (None when cleared)."""
    product, _sp = await _priced_product(session, store, product_id)
    group = await session.get(PanelGroup, group_id)
    if not group or not group.is_enabled or not group.reseller_enabled:
        raise NotFound("بسته فروش")
    pp = await pool_product(session, group_id, product_id)
    if pp is None:
        raise AppError("PRODUCT_NOT_IN_POOL", "این پکیج در بسته انتخاب‌شده فروخته نمی‌شود.", 422)
    row = await session.scalar(select(StorePoolPrice).where(
        StorePoolPrice.store_id == store.id, StorePoolPrice.panel_group_id == group_id, StorePoolPrice.product_id == product_id))
    if not customer_price:
        if row is not None:
            await session.delete(row)
        return None
    cost = effective_prices(product, pp)[1]
    if customer_price < cost:
        raise AppError("CUSTOMER_PRICE_BELOW_COST", f"قیمت فروش در بسته «{group.name}» نمی‌تواند از قیمت همکاری همین بسته ({cost}) کمتر باشد.", 422)
    if row is None:
        session.add(StorePoolPrice(store_id=store.id, panel_group_id=group_id, product_id=product_id, customer_price=customer_price))
    else:
        row.customer_price = customer_price
    return customer_price


async def set_prices_batch(session: AsyncSession, store: Store, items: list[tuple[uuid.UUID | None, uuid.UUID, int | None]]) -> list[tuple[uuid.UUID | None, uuid.UUID, int | None]]:
    """Apply many price edits in one go, all or nothing. ``(pool id or None for the store-wide price, product id, price)``.

    Every item is validated by the same rules as the single edits; if any is refused nothing is written and one
    error lists every refused item. Returns the items whose stored price actually changed (for the audit log)."""
    seen: set[tuple[uuid.UUID | None, uuid.UUID]] = set()
    errors: list[dict] = []
    changed: list[tuple[uuid.UUID | None, uuid.UUID, int | None]] = []
    before_pool = await store_pool_prices(session, store.id)
    for group_id, product_id, price in items:
        if (group_id, product_id) in seen:
            errors.append({"pool_id": group_id, "product_id": product_id, "code": "DUPLICATE_ITEM", "message": "این ردیف بیش از یک بار فرستاده شده است."})
            continue
        seen.add((group_id, product_id))
        try:
            if group_id is None:
                _p, sp = await _priced_product(session, store, product_id)
                old = sp.customer_price or None
                await set_customer_price(session, store, product_id, price)
            else:
                old = before_pool.get((group_id, product_id))
                await set_pool_price(session, store, group_id, product_id, price)
        except AppError as e:
            errors.append({"pool_id": group_id, "product_id": product_id, "code": e.code, "message": e.message})
            continue
        if (old or None) != (price or None):
            changed.append((group_id, product_id, price or None))
    if errors:
        raise AppError("PRICES_INVALID", f"{len(errors)} قیمت معتبر نیست؛ هیچ تغییری ذخیره نشد.", 422, {"errors": [{**e, "pool_id": str(e["pool_id"]) if e["pool_id"] else None, "product_id": str(e["product_id"])} for e in errors]})
    return changed
