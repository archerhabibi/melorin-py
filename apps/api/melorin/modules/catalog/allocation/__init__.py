"""Single allocation core: WHERE a new VPN account is created is decided here and nowhere else.

Vocabulary: a *bundle* (UI: بسته فروش) is a ``Bundle``. Every account is sold through exactly one
bundle; there is no bundle-less route.

The channels (Telegram bot, store website, reseller panel, admin, API) say *what* is bought and, when the
customer is allowed to choose, *which bundle* (and in a manual bundle *which panel*). They never choose a
server. The core validates every choice and decides the rest:

    bundle = the bundle named on the order, else the product's default bundle
    bundle --enabled members--> panel --enabled server with matching product code--> server

A bundle must sell the package (``BundleProduct``), be enabled, have capacity and be open to the store.

Two entry points share the same rules:

* ``resolve_order_group``  - called when an order is CREATED (before any money moves). It applies the
  product default group and rejects an unusable group with a clear error instead of letting a paid
  order fall into manual review.
* ``resolve_allocation``   - called when the order is PROVISIONED. It re-checks the group (state may
  have changed since checkout) and picks the (server, panel).

Everything about the SALE route lives here too, so no channel and no other module decides it:

* ``plan_sale``           - the one entry point for "what does this purchase/renewal/quote mean": bundle,
  panel choice, account name, package membership and the price (a bundle may override the product price).
* the prices: ``main_price`` (store), ``reseller_price`` (cost, may differ per bundle) and the reseller's
  retail price, which has two levels: ``StoreProduct.customer_price`` (the store-wide price of a package)
  and ``StoreBundlePrice`` (the price of that package in ONE bundle, which wins when set). A retail price below
  the reseller price of the bundle being sold is never allowed: it is refused when set, hidden from every
  list and refused again at checkout (``CUSTOMER_PRICE_BELOW_COST``).
* ``sellable_bundles`` / ``bundle_packages`` / ``renewal_offers`` / ``sellable_products`` - what a customer may
  be shown. ``catalog`` and ``orders`` only call these; they hold no bundle, membership or price rule.

Selection itself is a pure function (``select_allocation``) fed by a loader, so the rules can be
unit-tested without a database.

Layout (a one-way stack, lower modules never import higher ones):

* ``offers``          - what a store offers and at what price: sellable bundles/packages, price layers, below-cost rule.
* ``routing``         - WHERE the account is created: pure selection rules + loaders (bundle -> panel -> server).
* ``sale``            - ``plan_sale`` / ``renewal_offers``: the single entry point for a purchase, renewal or quote.
* ``reseller_prices`` - the reseller's price table and the store-wide / per-bundle price setters.

This package re-exports the public names, so callers keep writing ``allocation.plan_sale(...)``.
"""

from __future__ import annotations

from melorin.modules.catalog.allocation.offers import (
    BundleView,
    account_bundle_id,
    below_cost,
    bundle_packages,
    bundle_product,
    effective_prices,
    ensure_customer_price,
    packages_for_bundle,
    reseller_price_floor,
    retail_price,
    sellable_bundles,
    sellable_products,
    sellable_products_priced,
    store_bundle_prices,
    stores_below_cost,
    unit_price,
)
from melorin.modules.catalog.allocation.routing import (
    Candidate,
    group_policy_violation,
    requested_account_name,
    resolve_allocation,
    resolve_order_group,
    select_allocation,
)
from melorin.modules.catalog.allocation.sale import (
    SalePlan,
    plan_sale,
    renewal_offers,
)
from melorin.modules.catalog.allocation.reseller_prices import (
    reseller_price_table,
    set_bundle_price,
    set_customer_price,
    set_prices_batch,
)

__all__ = [
    "BundleView",
    "Candidate",
    "SalePlan",
    "account_bundle_id",
    "below_cost",
    "bundle_packages",
    "bundle_product",
    "effective_prices",
    "ensure_customer_price",
    "group_policy_violation",
    "packages_for_bundle",
    "plan_sale",
    "renewal_offers",
    "requested_account_name",
    "reseller_price_floor",
    "reseller_price_table",
    "resolve_allocation",
    "resolve_order_group",
    "retail_price",
    "select_allocation",
    "sellable_bundles",
    "sellable_products",
    "sellable_products_priced",
    "set_bundle_price",
    "set_customer_price",
    "set_prices_batch",
    "store_bundle_prices",
    "stores_below_cost",
    "unit_price",
]
