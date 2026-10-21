"""The one entry point for "what does this purchase / renewal / quote mean": bundle, panel choice, account name, package membership and price."""

from __future__ import annotations

import dataclasses
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from melorin.core.errors import AppError
from melorin.modules.catalog import service as catalog_service
from melorin.kernel.models.catalog import Product, StoreProduct
from melorin.kernel.models.stores import Store
from melorin.kernel.models.bundles import Bundle, BundleProduct
from melorin.modules.catalog.allocation.offers import (
    account_bundle_id,
    below_cost,
    bundle_product,
    effective_prices,
    retail_price,
    store_bundle_prices,
    unit_price,
)
from melorin.modules.catalog.allocation.routing import requested_account_name, resolve_order_group


@dataclasses.dataclass(frozen=True)
class SalePlan:
    """The core's answer for one sale: where it goes, what name it gets and what it costs."""

    group_id: uuid.UUID | None
    group: Bundle | None
    selected_panel_id: uuid.UUID | None
    account_name: str | None
    bundle_product: BundleProduct | None
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
    bundle_id: uuid.UUID | None = None,
    selected_panel_id: uuid.UUID | None = None,
    account_name: str | None = None,
    enforce: bool = True,
) -> SalePlan:
    """Decide a sale (or a quote of one) for every channel. Raises BEFORE any money moves.

    * purchase: bundle (explicit, else the product default; none = ``BUNDLE_REQUIRED``), package membership,
      panel choice, custom account name, and the bundle's price.
    * renewal: the bundle the account was originally sold through (none for accounts that predate bundles =
      the product's own price). No new bundle, panel or name can be chosen.
    * ``enforce=False`` is for price previews that name no bundle (coupon check): no validation, the
      product's default bundle price.
    """
    if kind == "renewal":
        group_id = await account_bundle_id(session, account) if account is not None else None
        selected, name = None, None
    elif enforce:
        group_id, selected = await resolve_order_group(
            session, store_id=store.id, product=product, bundle_id=bundle_id, selected_panel_id=selected_panel_id
        )
        name = requested_account_name(await session.get(Bundle, group_id), account_name)
    else:
        group_id, selected, name = bundle_id or product.default_bundle_id, None, None
    pp = await bundle_product(session, group_id, product.id)
    main, reseller = effective_prices(product, pp)
    group = await session.get(Bundle, group_id) if group_id else None
    retail = None
    if store.kind == "reseller":
        own = (await store_bundle_prices(session, store.id, group_id=group_id)).get((group_id, product.id)) if group_id else None
        retail = retail_price(sp, own)
        if kind == "renewal" and not retail:
            raise AppError("RENEWAL_NOT_PRICED", "برای این بسته در این فروشگاه قیمتی تعیین نشده است؛ تمدید فعلاً ممکن نیست.", 409)
        if below_cost(retail, reseller):
            raise AppError("CUSTOMER_PRICE_BELOW_COST", "قیمت فروش نماینده از قیمت همکاری این بسته کمتر است؛ فروش انجام نمی‌شود.", 409)
    return SalePlan(group_id, group, selected, name, pp, unit_price(store, product, retail, pp), main, reseller)


async def renewal_offers(session: AsyncSession, store: Store, account) -> list[tuple[Product, int]]:
    """(package, price) a customer may renew ``account`` with: ONLY the package the account was created from, at that
    package's current price inside the bundle the account was originally sold through. Empty when that package is no
    longer sold to this store (the customer then buys a new account)."""
    try:
        product, sp = await catalog_service.get_sellable(session, store, account.product_id)
        plan = await plan_sale(session, store=store, product=product, sp=sp, kind="renewal", account=account)
    except AppError:
        return []
    return [(product, plan.unit_price)]
