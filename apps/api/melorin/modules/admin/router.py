"""Admin API composition root.

The former 1,900-line router now lives in one module per route family
(overview, products, panels, bundles, payments, orders, directory, tickets,
reseller_applications, settings, coupons, identity_reviews). Paths, methods and
schemas are unchanged; this module only assembles them under ``/admin``.
"""

from fastapi import APIRouter

from melorin.modules.admin.integrations import router as integrations_router
from melorin.modules.admin.resellers import router as resellers_router
from melorin.modules.admin.overview import router as overview_router
from melorin.modules.admin.products import router as products_router
from melorin.modules.admin.panels import router as panels_router
from melorin.modules.admin.bundles import router as bundles_router
from melorin.modules.admin.payments import router as payments_router
from melorin.modules.admin.orders import router as orders_router
from melorin.modules.admin.directory import router as directory_router
from melorin.modules.admin.tickets import router as tickets_router
from melorin.modules.admin.manual_tasks import router as manual_tasks_router
from melorin.modules.admin.reseller_applications import router as reseller_applications_router
from melorin.modules.admin.settings import router as settings_router
from melorin.modules.admin.coupons import router as coupons_router
from melorin.modules.admin.identity_reviews import router as identity_reviews_router

router = APIRouter(prefix="/admin", tags=["admin"])
router.include_router(integrations_router)
router.include_router(resellers_router)
# The route families already carry the /admin prefix and tag; their routes are attached directly (not wrapped) so
# ``router.routes`` lists every admin endpoint with its final path, exactly as before the split.
for _family in (
    overview_router,
    products_router,
    panels_router,
    bundles_router,
    payments_router,
    orders_router,
    directory_router,
    tickets_router,
    reseller_applications_router,
    manual_tasks_router,
    settings_router,
    coupons_router,
    identity_reviews_router,
):
    router.routes.extend(_family.routes)


# Backward-compatible attribute access (``from melorin.modules.admin.router import create_product``) for callers
# and tests written before the split. New code should import from the family module directly.
_FAMILIES = (
    "overview",
    "products",
    "panels",
    "bundles",
    "payments",
    "orders",
    "directory",
    "tickets",
    "reseller_applications",
    "manual_tasks",
    "settings",
    "coupons",
    "identity_reviews",
    "_common",
)


def __getattr__(name: str):
    import importlib

    for family in _FAMILIES:
        module = importlib.import_module(f"melorin.modules.admin.{family}")
        if name in vars(module):
            return getattr(module, name)
    raise AttributeError(name)
